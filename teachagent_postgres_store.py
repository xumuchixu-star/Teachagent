from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - optional dependency in local workspace
    psycopg = None
    dict_row = None
    Jsonb = None


ROOT = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = ROOT / "docs" / "db" / "teachagent_postgres_mvp.sql"
DEFAULT_ENV_PATHS = (
    ROOT / ".env",
    ROOT / ".env.local",
    ROOT / "app" / ".env",
    ROOT / "app" / ".env.local",
)
_ENV_LOADED = False

QUESTION_KIND_VALUES = {"seed_example", "wrong_question", "practice_question"}
EVENT_TYPE_VALUES = {"diagnosis", "coach", "review", "binding", "student_choice"}
ERROR_TYPE_VALUES = {
    "concept_gap",
    "missing_strategy",
    "misreading",
    "calculation",
    "careless",
}
REVIEW_STATE_VALUES = {"new", "learning", "review", "stable"}
QUESTION_RESULT_VALUES = {"unseen", "correct", "wrong", "partial"}
SPEAKER_VALUES = {"assistant", "student", "system"}


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            text = normalize_text(item)
            if text:
                result.append(text)
        return result
    text = normalize_text(value)
    return [text] if text else []


def unique_str_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = normalize_text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def coerce_json_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def coerce_json_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def isoformat_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = normalize_text(value)
    return text


def _strip_wrapping_quotes(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1]
    return text


def load_teachagent_env(*, override: bool = False) -> None:
    global _ENV_LOADED
    if _ENV_LOADED and not override:
        return
    for path in DEFAULT_ENV_PATHS:
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_key = key.strip()
            if not env_key:
                continue
            if not override and env_key in os.environ:
                continue
            os.environ[env_key] = _strip_wrapping_quotes(value)
    _ENV_LOADED = True


def database_url_from_env() -> str | None:
    load_teachagent_env()
    return (
        normalize_text(os.getenv("TEACHAGENT_DATABASE_URL"))
        or normalize_text(os.getenv("DATABASE_URL"))
    )


def require_psycopg() -> None:
    if psycopg is None or dict_row is None or Jsonb is None:
        raise ImportError(
            "psycopg is required for TeachAgentPostgresStore. "
            "Install it with `python3 -m pip install psycopg[binary]`."
        )


def jsonb(value: Any) -> Any:
    require_psycopg()
    return Jsonb(value)


def speaker_from_message(value: Any) -> str:
    text = normalize_text(value) or "assistant"
    return text if text in SPEAKER_VALUES else "assistant"


def infer_question_kind(*, question_uid: str, source_type: str | None, question_state: dict[str, Any]) -> str:
    explicit = normalize_text(question_state.get("question_kind"))
    if explicit in QUESTION_KIND_VALUES:
        return explicit
    if question_uid.startswith("wq_"):
        return "wrong_question"
    if source_type in {"manual_entry", "diagnosis_transfer", "coach_transfer", "binder_import"}:
        return "wrong_question"
    return "seed_example"


def extract_extra_fields(payload: dict[str, Any], known_keys: set[str]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in known_keys
    }


@dataclass(frozen=True)
class PostgresStoreConfig:
    database_url: str
    application_name: str = "teachagent"
    connect_timeout: int = 10

    @classmethod
    def from_env(cls) -> "PostgresStoreConfig":
        database_url = database_url_from_env()
        if database_url is None:
            raise ValueError(
                "Missing database URL. Set TEACHAGENT_DATABASE_URL or DATABASE_URL."
            )
        application_name = (
            normalize_text(os.getenv("TEACHAGENT_DB_APPLICATION_NAME"))
            or "teachagent"
        )
        raw_timeout = normalize_text(os.getenv("TEACHAGENT_DB_CONNECT_TIMEOUT"))
        connect_timeout = int(raw_timeout or 10)
        return cls(
            database_url=database_url,
            application_name=application_name,
            connect_timeout=connect_timeout,
        )


class TeachAgentPostgresStore:
    def __init__(self, config: PostgresStoreConfig | None = None) -> None:
        self.config = config or PostgresStoreConfig.from_env()

    @property
    def schema_path(self) -> Path:
        return DEFAULT_SCHEMA_PATH

    def apply_schema(self, *, schema_path: Path | None = None) -> dict[str, Any]:
        path = Path(schema_path or self.schema_path).expanduser().resolve()
        schema_sql = path.read_text(encoding="utf-8")
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(schema_sql)
        return {
            "schema_path": str(path),
        }

    @contextmanager
    def connection(self) -> Iterator[Any]:
        require_psycopg()
        conn = psycopg.connect(
            self.config.database_url,
            row_factory=dict_row,
            connect_timeout=self.config.connect_timeout,
            application_name=self.config.application_name,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ping(self) -> dict[str, Any]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT current_database() AS database_name, current_user AS current_user, now() AS checked_at"
                )
                row = cur.fetchone()
        return {
            "database_name": row["database_name"],
            "current_user": row["current_user"],
            "checked_at": isoformat_or_none(row["checked_at"]),
        }

    def get_student(self, student_uid: str) -> dict[str, Any] | None:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, student_uid, display_name, grade_level, status, metadata, created_at, updated_at
                    FROM students
                    WHERE student_uid = %s
                    """,
                    (student_uid,),
                )
                row = cur.fetchone()
        return self._student_row_to_dict(row) if row else None

    def get_or_create_student(
        self,
        student_uid: str,
        *,
        display_name: str | None = None,
        grade_level: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                row = self._ensure_student(
                    cur,
                    student_uid=student_uid,
                    display_name=display_name,
                    grade_level=grade_level,
                    metadata=metadata,
                )
        return self._student_row_to_dict(row)

    def list_students(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH review_question_counts AS (
                      SELECT student_id, COUNT(*) AS question_count
                      FROM student_question_states
                      GROUP BY student_id
                    ),
                    question_meta AS (
                      SELECT
                        student_id,
                        COUNT(*) FILTER (WHERE question_kind = 'wrong_question') AS wrongbook_question_count,
                        MAX(updated_at) AS questions_updated_at
                      FROM student_questions
                      GROUP BY student_id
                    ),
                    custom_node_meta AS (
                      SELECT
                        owner_student_id AS student_id,
                        COUNT(*) AS custom_node_count,
                        MAX(updated_at) AS custom_nodes_updated_at
                      FROM knowledge_nodes
                      WHERE source_scope = 'student_custom'
                      GROUP BY owner_student_id
                    )
                    SELECT
                      s.student_uid,
                      s.display_name,
                      s.grade_level,
                      s.status,
                      s.created_at,
                      s.updated_at,
                      COALESCE(rqc.question_count, 0) AS question_count,
                      COALESCE(qm.wrongbook_question_count, 0) AS wrongbook_question_count,
                      COALESCE(cnm.custom_node_count, 0) AS custom_node_count,
                      GREATEST(
                        s.updated_at,
                        COALESCE(srs.updated_at, s.updated_at),
                        COALESCE(smp.updated_at, s.updated_at),
                        COALESCE(qm.questions_updated_at, s.updated_at),
                        COALESCE(cnm.custom_nodes_updated_at, s.updated_at)
                      ) AS last_activity_at
                    FROM students s
                    LEFT JOIN review_question_counts rqc ON rqc.student_id = s.id
                    LEFT JOIN question_meta qm ON qm.student_id = s.id
                    LEFT JOIN custom_node_meta cnm ON cnm.student_id = s.id
                    LEFT JOIN student_review_states srs ON srs.student_id = s.id
                    LEFT JOIN student_memory_profiles smp ON smp.student_id = s.id
                    ORDER BY last_activity_at DESC, s.student_uid
                    """
                )
                rows = cur.fetchall()

        if limit is not None and limit >= 0:
            rows = rows[:limit]

        return [
            {
                "student_id": str(row["student_uid"]),
                "display_name": row["display_name"],
                "grade_level": row["grade_level"],
                "status": row["status"],
                "question_count": int(row["question_count"] or 0),
                "wrongbook_question_count": int(row["wrongbook_question_count"] or 0),
                "custom_node_count": int(row["custom_node_count"] or 0),
                "created_at": isoformat_or_none(row["created_at"]),
                "updated_at": isoformat_or_none(row["updated_at"]),
                "last_activity_at": isoformat_or_none(row["last_activity_at"]),
            }
            for row in rows
        ]

    def count_knowledge_nodes(self, *, source_scope: str | None = None) -> int:
        with self.connection() as conn:
            with conn.cursor() as cur:
                if source_scope is None:
                    cur.execute("SELECT COUNT(*) AS node_count FROM knowledge_nodes")
                else:
                    cur.execute(
                        """
                        SELECT COUNT(*) AS node_count
                        FROM knowledge_nodes
                        WHERE source_scope = %s
                        """,
                        (source_scope,),
                    )
                row = cur.fetchone()
        return int((row or {}).get("node_count") or 0)

    def upsert_knowledge_nodes(
        self,
        nodes: list[dict[str, Any]],
        *,
        owner_student_uid: str | None = None,
    ) -> int:
        owner_student_id: int | None = None
        source_scope = "system"
        if owner_student_uid is not None:
            source_scope = "student_custom"
        with self.connection() as conn:
            with conn.cursor() as cur:
                if owner_student_uid is not None:
                    owner_student = self._ensure_student(cur, student_uid=owner_student_uid)
                    owner_student_id = int(owner_student["id"])
                for node in nodes:
                    self._upsert_knowledge_node(
                        cur,
                        node,
                        owner_student_id=owner_student_id,
                        source_scope=source_scope,
                    )
        return len(nodes)

    def save_custom_node(self, student_uid: str, node_payload: dict[str, Any]) -> dict[str, Any]:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._ensure_student(cur, student_uid=student_uid)
                row = self._upsert_knowledge_node(
                    cur,
                    node_payload,
                    owner_student_id=int(student["id"]),
                    source_scope="student_custom",
                )
        return self._knowledge_node_row_to_dict(row)

    def load_custom_nodes(self, student_uid: str) -> dict[str, Any]:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._get_student_by_uid(cur, student_uid)
                if student is None:
                    return {"nodes": []}
                cur.execute(
                    """
                    SELECT node_id, parent_node_id, name, level, is_leaf, node_kind, review_role,
                           binding_role, path, path_text, aliases, common_errors, typing_source,
                           source_scope, created_at, updated_at
                    FROM knowledge_nodes
                    WHERE owner_student_id = %s AND source_scope = 'student_custom'
                    ORDER BY path_text NULLS LAST, node_id
                    """,
                    (student["id"],),
                )
                rows = cur.fetchall()
        return {"nodes": [self._knowledge_node_row_to_dict(row) for row in rows]}

    def save_question_note(self, student_uid: str, question_uid: str, note: str) -> dict[str, Any]:
        student_uid = normalize_text(student_uid)
        question_uid = normalize_text(question_uid)
        if student_uid is None or question_uid is None:
            raise ValueError("student_uid and question_uid are required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._ensure_student(cur, student_uid=student_uid)
                question_row = self._ensure_student_question(
                    cur,
                    student_id=int(student["id"]),
                    question_uid=question_uid,
                    question_kind="wrong_question",
                    source_type="manual_entry",
                    stem="",
                    note=note,
                    payload={},
                )
                cur.execute(
                    """
                    UPDATE student_questions
                    SET note = %s
                    WHERE id = %s
                    RETURNING question_uid, note, updated_at
                    """,
                    (note.strip(), question_row["id"]),
                )
                row = cur.fetchone()
        return {
            "question_id": row["question_uid"],
            "note": row["note"] or "",
            "updated_at": isoformat_or_none(row["updated_at"]),
        }

    def load_question_notes(self, student_uid: str) -> dict[str, str]:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._get_student_by_uid(cur, student_uid)
                if student is None:
                    return {}
                cur.execute(
                    """
                    SELECT question_uid, note
                    FROM student_questions
                    WHERE student_id = %s
                      AND note IS NOT NULL
                      AND btrim(note) <> ''
                    ORDER BY question_uid
                    """,
                    (student["id"],),
                )
                rows = cur.fetchall()
        return {
            str(row["question_uid"]): str(row["note"] or "")
            for row in rows
        }

    def save_review_state(
        self,
        review_state: dict[str, Any],
        *,
        replace_existing: bool = True,
    ) -> dict[str, Any]:
        student_uid = normalize_text(review_state.get("student_id"))
        if student_uid is None:
            raise ValueError("review_state.student_id is required")
        knowledge_states = coerce_json_list(review_state.get("knowledge_point_states"))
        question_states = coerce_json_list(review_state.get("example_question_states"))
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._ensure_student(cur, student_uid=student_uid)
                student_id = int(student["id"])
                cur.execute(
                    """
                    INSERT INTO student_review_states (
                      student_id,
                      record_uid,
                      generated_at,
                      review_plan,
                      notes
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (student_id) DO UPDATE
                    SET record_uid = EXCLUDED.record_uid,
                        generated_at = EXCLUDED.generated_at,
                        review_plan = EXCLUDED.review_plan,
                        notes = EXCLUDED.notes
                    RETURNING student_id
                    """,
                    (
                        student_id,
                        normalize_text(review_state.get("record_id")) or f"review_state.{student_uid}",
                        normalize_text(review_state.get("generated_at")) or datetime.now().isoformat(),
                        jsonb(coerce_json_object(review_state.get("review_plan"))),
                        jsonb(coerce_json_object(review_state.get("notes"))),
                    ),
                )
                cur.fetchone()

                active_node_ids: list[str] = []
                for raw_node_state in knowledge_states:
                    node_state = raw_node_state if isinstance(raw_node_state, dict) else {}
                    node_id = normalize_text(node_state.get("node_id"))
                    if node_id is None:
                        continue
                    active_node_ids.append(node_id)
                    cur.execute(
                        """
                        INSERT INTO student_node_states (
                          student_id,
                          node_id,
                          state,
                          mastery,
                          stability,
                          first_seen_at,
                          last_reviewed_at,
                          next_review_at,
                          correct_count,
                          wrong_count,
                          source_batch_ids,
                          priority_note,
                          manual_priority_bias,
                          manual_skip_until,
                          session_priority_boost,
                          session_priority_until,
                          session_priority_reason
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (student_id, node_id) DO UPDATE
                        SET state = EXCLUDED.state,
                            mastery = EXCLUDED.mastery,
                            stability = EXCLUDED.stability,
                            first_seen_at = EXCLUDED.first_seen_at,
                            last_reviewed_at = EXCLUDED.last_reviewed_at,
                            next_review_at = EXCLUDED.next_review_at,
                            correct_count = EXCLUDED.correct_count,
                            wrong_count = EXCLUDED.wrong_count,
                            source_batch_ids = EXCLUDED.source_batch_ids,
                            priority_note = EXCLUDED.priority_note,
                            manual_priority_bias = EXCLUDED.manual_priority_bias,
                            manual_skip_until = EXCLUDED.manual_skip_until,
                            session_priority_boost = EXCLUDED.session_priority_boost,
                            session_priority_until = EXCLUDED.session_priority_until,
                            session_priority_reason = EXCLUDED.session_priority_reason
                        """,
                        (
                            student_id,
                            node_id,
                            self._normalized_review_state_value(node_state.get("state")),
                            float(node_state.get("mastery", 0.0) or 0.0),
                            float(node_state.get("stability", 0.0) or 0.0),
                            normalize_text(node_state.get("first_seen_at")),
                            normalize_text(node_state.get("last_reviewed_at")),
                            normalize_text(node_state.get("next_review_at")),
                            int(node_state.get("correct_count", 0) or 0),
                            int(node_state.get("wrong_count", 0) or 0),
                            normalize_str_list(node_state.get("source_batch_ids")),
                            normalize_text(node_state.get("priority_note")),
                            float(node_state.get("manual_priority_bias", 0.0) or 0.0),
                            normalize_text(node_state.get("manual_skip_until")),
                            float(node_state.get("session_priority_boost", 0.0) or 0.0),
                            normalize_text(node_state.get("session_priority_until")),
                            normalize_text(node_state.get("session_priority_reason")),
                        ),
                    )

                if replace_existing:
                    if active_node_ids:
                        cur.execute(
                            """
                            DELETE FROM student_node_states
                            WHERE student_id = %s
                              AND node_id <> ALL(%s)
                            """,
                            (student_id, active_node_ids),
                        )
                    else:
                        cur.execute(
                            "DELETE FROM student_node_states WHERE student_id = %s",
                            (student_id,),
                        )

                active_question_row_ids: list[int] = []
                for raw_question_state in question_states:
                    question_state = raw_question_state if isinstance(raw_question_state, dict) else {}
                    question_uid = normalize_text(question_state.get("question_id"))
                    if question_uid is None:
                        continue
                    question_payload = coerce_json_object(question_state.get("question_payload"))
                    source_type = normalize_text(question_state.get("source_type")) or normalize_text(
                        question_payload.get("source_type")
                    ) or "manual_entry"
                    question_row = self._ensure_student_question(
                        cur,
                        student_id=student_id,
                        question_uid=question_uid,
                        question_kind=infer_question_kind(
                            question_uid=question_uid,
                            source_type=source_type,
                            question_state=question_state,
                        ),
                        source_type=source_type,
                        source_batch_id=normalize_text(question_state.get("source_batch_id")),
                        source_name=normalize_text(question_payload.get("source_name")),
                        source_section=normalize_text(question_payload.get("source_section")),
                        source_chapter=normalize_text(question_payload.get("source_chapter")),
                        question_type=normalize_text(question_payload.get("question_type")),
                        stem=str(question_payload.get("stem") or ""),
                        student_answer=normalize_text(question_payload.get("student_answer")),
                        correct_answer=normalize_text(question_payload.get("correct_answer")),
                        solution_text=normalize_text(question_payload.get("solution_text")),
                        priority_note=normalize_text(question_state.get("priority_note")),
                        note=normalize_text(question_state.get("note")),
                        payload=question_payload,
                    )
                    question_row_id = int(question_row["id"])
                    active_question_row_ids.append(question_row_id)
                    cur.execute(
                        """
                        INSERT INTO student_question_states (
                          student_id,
                          question_id,
                          state,
                          source_batch_id,
                          last_result,
                          review_count,
                          first_seen_at,
                          last_reviewed_at,
                          next_review_at,
                          difficulty_estimate,
                          priority_note,
                          mastery,
                          stability,
                          manual_priority_bias,
                          manual_skip_until,
                          session_priority_boost,
                          session_priority_until,
                          session_priority_reason
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (student_id, question_id) DO UPDATE
                        SET state = EXCLUDED.state,
                            source_batch_id = EXCLUDED.source_batch_id,
                            last_result = EXCLUDED.last_result,
                            review_count = EXCLUDED.review_count,
                            first_seen_at = EXCLUDED.first_seen_at,
                            last_reviewed_at = EXCLUDED.last_reviewed_at,
                            next_review_at = EXCLUDED.next_review_at,
                            difficulty_estimate = EXCLUDED.difficulty_estimate,
                            priority_note = EXCLUDED.priority_note,
                            mastery = EXCLUDED.mastery,
                            stability = EXCLUDED.stability,
                            manual_priority_bias = EXCLUDED.manual_priority_bias,
                            manual_skip_until = EXCLUDED.manual_skip_until,
                            session_priority_boost = EXCLUDED.session_priority_boost,
                            session_priority_until = EXCLUDED.session_priority_until,
                            session_priority_reason = EXCLUDED.session_priority_reason
                        """,
                        (
                            student_id,
                            question_row_id,
                            self._normalized_review_state_value(question_state.get("state")),
                            normalize_text(question_state.get("source_batch_id")),
                            self._normalized_question_result_value(question_state.get("last_result")),
                            int(question_state.get("review_count", 0) or 0),
                            normalize_text(question_state.get("first_seen_at")),
                            normalize_text(question_state.get("last_reviewed_at")),
                            normalize_text(question_state.get("next_review_at")),
                            (
                                float(question_state.get("difficulty_estimate"))
                                if question_state.get("difficulty_estimate") not in (None, "")
                                else None
                            ),
                            normalize_text(question_state.get("priority_note")),
                            (
                                float(question_state.get("mastery"))
                                if question_state.get("mastery") not in (None, "")
                                else None
                            ),
                            (
                                float(question_state.get("stability"))
                                if question_state.get("stability") not in (None, "")
                                else None
                            ),
                            float(question_state.get("manual_priority_bias", 0.0) or 0.0),
                            normalize_text(question_state.get("manual_skip_until")),
                            float(question_state.get("session_priority_boost", 0.0) or 0.0),
                            normalize_text(question_state.get("session_priority_until")),
                            normalize_text(question_state.get("session_priority_reason")),
                        ),
                    )
                    self._replace_question_links(cur, question_row_id, question_state)

                if replace_existing:
                    if active_question_row_ids:
                        cur.execute(
                            """
                            DELETE FROM student_question_states
                            WHERE student_id = %s
                              AND question_id <> ALL(%s)
                            """,
                            (student_id, active_question_row_ids),
                        )
                    else:
                        cur.execute(
                            "DELETE FROM student_question_states WHERE student_id = %s",
                            (student_id,),
                        )
        return {
            "student_id": student_uid,
            "knowledge_point_count": len(active_node_ids),
            "question_count": len(active_question_row_ids),
        }

    def load_review_state(self, student_uid: str) -> dict[str, Any] | None:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._get_student_by_uid(cur, student_uid)
                if student is None:
                    return None
                student_id = int(student["id"])
                cur.execute(
                    """
                    SELECT record_uid, generated_at, review_plan, notes
                    FROM student_review_states
                    WHERE student_id = %s
                    """,
                    (student_id,),
                )
                review_row = cur.fetchone()
                if review_row is None:
                    return None

                cur.execute(
                    """
                    SELECT node_id, state, mastery, stability, first_seen_at, last_reviewed_at,
                           next_review_at, correct_count, wrong_count, source_batch_ids,
                           priority_note, manual_priority_bias, manual_skip_until,
                           session_priority_boost, session_priority_until, session_priority_reason
                    FROM student_node_states
                    WHERE student_id = %s
                    ORDER BY node_id
                    """,
                    (student_id,),
                )
                node_rows = cur.fetchall()

                cur.execute(
                    """
                    SELECT qs.question_id AS question_row_id,
                           qs.state,
                           qs.source_batch_id,
                           qs.last_result,
                           qs.review_count,
                           qs.first_seen_at,
                           qs.last_reviewed_at,
                           qs.next_review_at,
                           qs.difficulty_estimate,
                           qs.priority_note,
                           qs.mastery,
                           qs.stability,
                           qs.manual_priority_bias,
                           qs.manual_skip_until,
                           qs.session_priority_boost,
                           qs.session_priority_until,
                           qs.session_priority_reason,
                           q.question_uid,
                           q.source_type,
                           q.source_name,
                           q.source_section,
                           q.source_chapter,
                           q.question_type,
                           q.stem,
                           q.student_answer,
                           q.correct_answer,
                           q.solution_text,
                           q.note,
                           q.payload
                    FROM student_question_states qs
                    JOIN student_questions q ON q.id = qs.question_id
                    WHERE qs.student_id = %s
                    ORDER BY qs.id
                    """,
                    (student_id,),
                )
                question_rows = cur.fetchall()
                question_row_ids = [int(row["question_row_id"]) for row in question_rows]
                link_map: dict[int, list[dict[str, Any]]] = {}
                if question_row_ids:
                    cur.execute(
                        """
                        SELECT question_id, node_id, link_role
                        FROM student_question_node_links
                        WHERE question_id = ANY(%s)
                        ORDER BY question_id, CASE WHEN link_role = 'primary' THEN 0 ELSE 1 END, node_id
                        """,
                        (question_row_ids,),
                    )
                    for link_row in cur.fetchall():
                        link_map.setdefault(int(link_row["question_id"]), []).append(link_row)

        linked_question_ids_by_node: dict[str, list[str]] = {}
        example_question_states: list[dict[str, Any]] = []
        for row in question_rows:
            question_row_id = int(row["question_row_id"])
            links = link_map.get(question_row_id, [])
            primary_node_ids = [
                str(link["node_id"])
                for link in links
                if str(link["link_role"]) == "primary"
            ]
            secondary_node_ids = [
                str(link["node_id"])
                for link in links
                if str(link["link_role"]) != "primary"
            ]
            linked_node_ids = primary_node_ids + [node_id for node_id in secondary_node_ids if node_id not in primary_node_ids]
            for node_id in linked_node_ids:
                linked_question_ids_by_node.setdefault(node_id, []).append(str(row["question_uid"]))
            payload = coerce_json_object(row["payload"])
            question_payload = {
                **payload,
                "stem": row["stem"] or "",
                "question_type": row["question_type"],
                "student_answer": row["student_answer"],
                "correct_answer": row["correct_answer"],
                "solution_text": row["solution_text"],
                "source_name": row["source_name"],
                "source_type": row["source_type"],
                "source_section": row["source_section"],
                "source_chapter": row["source_chapter"],
            }
            state_payload = {
                "question_id": str(row["question_uid"]),
                "state": row["state"],
                "linked_node_ids": linked_node_ids,
                "primary_node_ids": primary_node_ids,
                "secondary_node_ids": secondary_node_ids,
                "source_batch_id": row["source_batch_id"],
                "source_type": row["source_type"],
                "last_result": row["last_result"],
                "review_count": int(row["review_count"] or 0),
                "first_seen_at": isoformat_or_none(row["first_seen_at"]),
                "last_reviewed_at": isoformat_or_none(row["last_reviewed_at"]),
                "next_review_at": isoformat_or_none(row["next_review_at"]),
                "difficulty_estimate": row["difficulty_estimate"],
                "priority_note": row["priority_note"],
                "question_payload": question_payload,
                "manual_priority_bias": float(row["manual_priority_bias"] or 0.0),
                "manual_skip_until": isoformat_or_none(row["manual_skip_until"]),
                "session_priority_boost": float(row["session_priority_boost"] or 0.0),
                "session_priority_until": isoformat_or_none(row["session_priority_until"]),
                "session_priority_reason": row["session_priority_reason"],
            }
            if row["mastery"] is not None:
                state_payload["mastery"] = float(row["mastery"])
            if row["stability"] is not None:
                state_payload["stability"] = float(row["stability"])
            if normalize_text(row["note"]):
                state_payload["note"] = str(row["note"])
            example_question_states.append(state_payload)

        knowledge_point_states: list[dict[str, Any]] = []
        for row in node_rows:
            node_id = str(row["node_id"])
            knowledge_point_states.append(
                {
                    "node_id": node_id,
                    "state": row["state"],
                    "mastery": float(row["mastery"] or 0.0),
                    "stability": float(row["stability"] or 0.0),
                    "linked_question_ids": unique_str_list(linked_question_ids_by_node.get(node_id, [])),
                    "source_batch_ids": normalize_str_list(row["source_batch_ids"]),
                    "first_seen_at": isoformat_or_none(row["first_seen_at"]),
                    "last_reviewed_at": isoformat_or_none(row["last_reviewed_at"]),
                    "next_review_at": isoformat_or_none(row["next_review_at"]),
                    "correct_count": int(row["correct_count"] or 0),
                    "wrong_count": int(row["wrong_count"] or 0),
                    "priority_note": row["priority_note"],
                    "manual_priority_bias": float(row["manual_priority_bias"] or 0.0),
                    "manual_skip_until": isoformat_or_none(row["manual_skip_until"]),
                    "session_priority_boost": float(row["session_priority_boost"] or 0.0),
                    "session_priority_until": isoformat_or_none(row["session_priority_until"]),
                    "session_priority_reason": row["session_priority_reason"],
                }
            )

        return {
            "record_id": review_row["record_uid"],
            "student_id": student_uid,
            "generated_at": isoformat_or_none(review_row["generated_at"]),
            "knowledge_point_states": knowledge_point_states,
            "example_question_states": example_question_states,
            "review_plan": coerce_json_object(review_row["review_plan"]),
            "notes": coerce_json_object(review_row["notes"]),
        }

    def save_memory_profile(
        self,
        profile: dict[str, Any],
        *,
        replace_existing: bool = True,
    ) -> dict[str, Any]:
        student_uid = normalize_text(profile.get("student_id"))
        if student_uid is None:
            raise ValueError("profile.student_id is required")
        summary = coerce_json_object(profile.get("personalization_summary"))
        teaching_preferences = coerce_json_object(profile.get("teaching_preferences"))
        practice_preferences = coerce_json_object(profile.get("practice_preferences"))
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._ensure_student(cur, student_uid=student_uid)
                student_id = int(student["id"])
                cur.execute(
                    """
                    INSERT INTO student_memory_profiles (
                      student_id,
                      record_uid,
                      profile_version,
                      generated_at,
                      updated_at,
                      dominant_error_type,
                      dominant_error_signal_strength,
                      dominant_error_share,
                      memory_stage,
                      recommended_teaching_mode,
                      recommended_review_mode,
                      error_type_counts,
                      teaching_preferences,
                      practice_preferences,
                      personalization_summary,
                      memory_graph,
                      agent_memory_text,
                      notes,
                      raw_profile
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (student_id) DO UPDATE
                    SET record_uid = EXCLUDED.record_uid,
                        profile_version = EXCLUDED.profile_version,
                        generated_at = EXCLUDED.generated_at,
                        updated_at = EXCLUDED.updated_at,
                        dominant_error_type = EXCLUDED.dominant_error_type,
                        dominant_error_signal_strength = EXCLUDED.dominant_error_signal_strength,
                        dominant_error_share = EXCLUDED.dominant_error_share,
                        memory_stage = EXCLUDED.memory_stage,
                        recommended_teaching_mode = EXCLUDED.recommended_teaching_mode,
                        recommended_review_mode = EXCLUDED.recommended_review_mode,
                        error_type_counts = EXCLUDED.error_type_counts,
                        teaching_preferences = EXCLUDED.teaching_preferences,
                        practice_preferences = EXCLUDED.practice_preferences,
                        personalization_summary = EXCLUDED.personalization_summary,
                        memory_graph = EXCLUDED.memory_graph,
                        agent_memory_text = EXCLUDED.agent_memory_text,
                        notes = EXCLUDED.notes,
                        raw_profile = EXCLUDED.raw_profile
                    """,
                    (
                        student_id,
                        normalize_text(profile.get("record_id")) or f"student_memory.{student_uid}",
                        normalize_text(profile.get("profile_version")) or "student_memory_profile_v1",
                        normalize_text(profile.get("generated_at")) or datetime.now().isoformat(),
                        normalize_text(profile.get("updated_at")) or datetime.now().isoformat(),
                        normalize_text(summary.get("dominant_error_type")) or normalize_text(teaching_preferences.get("dominant_error_type")),
                        normalize_text(summary.get("dominant_error_signal_strength")),
                        (
                            float(summary.get("dominant_error_share"))
                            if summary.get("dominant_error_share") not in (None, "")
                            else None
                        ),
                        normalize_text(summary.get("memory_stage")),
                        normalize_text(summary.get("recommended_teaching_mode")) or normalize_text(teaching_preferences.get("recommended_mode")),
                        normalize_text(summary.get("recommended_review_mode")) or normalize_text(practice_preferences.get("recommended_review_mode")),
                        jsonb(coerce_json_object(profile.get("error_type_counts"))),
                        jsonb(teaching_preferences),
                        jsonb(practice_preferences),
                        jsonb(summary),
                        jsonb(coerce_json_object(profile.get("memory_graph"))),
                        normalize_text(profile.get("agent_memory_text")),
                        jsonb(coerce_json_object(profile.get("notes"))),
                        jsonb(profile),
                    ),
                )

                active_node_ids: list[str] = []
                for raw_node_memory in coerce_json_list(profile.get("node_memories")):
                    node_memory = raw_node_memory if isinstance(raw_node_memory, dict) else {}
                    node_id = normalize_text(node_memory.get("node_id"))
                    if node_id is None:
                        continue
                    active_node_ids.append(node_id)
                    cur.execute(
                        """
                        INSERT INTO student_node_memories (
                          student_id,
                          node_id,
                          error_type_counts,
                          observed_wrong_count,
                          review_wrong_count,
                          mastery_hint,
                          stability_hint,
                          linked_question_uids,
                          diagnosis_count,
                          review_correct_count,
                          review_partial_count,
                          practice_request_count,
                          consecutive_wrong_count,
                          last_seen_at,
                          last_wrong_at,
                          last_event_at,
                          dominant_error_type,
                          recommended_intervention,
                          signal_strength,
                          observation_stage,
                          metadata
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (student_id, node_id) DO UPDATE
                        SET error_type_counts = EXCLUDED.error_type_counts,
                            observed_wrong_count = EXCLUDED.observed_wrong_count,
                            review_wrong_count = EXCLUDED.review_wrong_count,
                            mastery_hint = EXCLUDED.mastery_hint,
                            stability_hint = EXCLUDED.stability_hint,
                            linked_question_uids = EXCLUDED.linked_question_uids,
                            diagnosis_count = EXCLUDED.diagnosis_count,
                            review_correct_count = EXCLUDED.review_correct_count,
                            review_partial_count = EXCLUDED.review_partial_count,
                            practice_request_count = EXCLUDED.practice_request_count,
                            consecutive_wrong_count = EXCLUDED.consecutive_wrong_count,
                            last_seen_at = EXCLUDED.last_seen_at,
                            last_wrong_at = EXCLUDED.last_wrong_at,
                            last_event_at = EXCLUDED.last_event_at,
                            dominant_error_type = EXCLUDED.dominant_error_type,
                            recommended_intervention = EXCLUDED.recommended_intervention,
                            signal_strength = EXCLUDED.signal_strength,
                            observation_stage = EXCLUDED.observation_stage,
                            metadata = EXCLUDED.metadata
                        """,
                        (
                            student_id,
                            node_id,
                            jsonb(coerce_json_object(node_memory.get("error_type_counts"))),
                            int(node_memory.get("observed_wrong_count", 0) or 0),
                            int(node_memory.get("review_wrong_count", 0) or 0),
                            normalize_text(node_memory.get("mastery_hint")) or "unknown",
                            normalize_text(node_memory.get("stability_hint")) or "unknown",
                            normalize_str_list(node_memory.get("linked_question_ids")),
                            int(node_memory.get("diagnosis_count", 0) or 0),
                            int(node_memory.get("review_correct_count", 0) or 0),
                            int(node_memory.get("review_partial_count", 0) or 0),
                            int(node_memory.get("practice_request_count", 0) or 0),
                            int(node_memory.get("consecutive_wrong_count", 0) or 0),
                            normalize_text(node_memory.get("last_seen_at")),
                            normalize_text(node_memory.get("last_wrong_at")),
                            normalize_text(node_memory.get("last_event_at")),
                            normalize_text(node_memory.get("dominant_error_type")),
                            normalize_text(node_memory.get("recommended_intervention")),
                            normalize_text(node_memory.get("signal_strength")),
                            normalize_text(node_memory.get("observation_stage")),
                            jsonb(
                                extract_extra_fields(
                                    node_memory,
                                    {
                                        "node_id",
                                        "error_type_counts",
                                        "observed_wrong_count",
                                        "review_wrong_count",
                                        "mastery_hint",
                                        "stability_hint",
                                        "linked_question_ids",
                                        "diagnosis_count",
                                        "review_correct_count",
                                        "review_partial_count",
                                        "practice_request_count",
                                        "consecutive_wrong_count",
                                        "last_seen_at",
                                        "last_wrong_at",
                                        "last_event_at",
                                        "dominant_error_type",
                                        "recommended_intervention",
                                        "signal_strength",
                                        "observation_stage",
                                    },
                                )
                            ),
                        ),
                    )

                if replace_existing:
                    if active_node_ids:
                        cur.execute(
                            """
                            DELETE FROM student_node_memories
                            WHERE student_id = %s
                              AND node_id <> ALL(%s)
                            """,
                            (student_id, active_node_ids),
                        )
                    else:
                        cur.execute(
                            "DELETE FROM student_node_memories WHERE student_id = %s",
                            (student_id,),
                        )

                active_question_row_ids: list[int] = []
                for raw_question_memory in coerce_json_list(profile.get("question_memories")):
                    question_memory = raw_question_memory if isinstance(raw_question_memory, dict) else {}
                    question_uid = normalize_text(question_memory.get("question_id"))
                    if question_uid is None:
                        continue
                    question_row = self._ensure_student_question(
                        cur,
                        student_id=student_id,
                        question_uid=question_uid,
                        question_kind=infer_question_kind(
                            question_uid=question_uid,
                            source_type=normalize_text(question_memory.get("source_type")),
                            question_state=question_memory,
                        ),
                        source_type=normalize_text(question_memory.get("source_type")) or "manual_entry",
                        source_name=normalize_text(question_memory.get("source_name")),
                        source_section=normalize_text(question_memory.get("source_section")),
                        stem="",
                        payload={},
                    )
                    question_row_id = int(question_row["id"])
                    active_question_row_ids.append(question_row_id)
                    cur.execute(
                        """
                        INSERT INTO student_question_memories (
                          student_id,
                          question_id,
                          linked_node_ids,
                          wrong_count,
                          review_count,
                          last_result,
                          error_type_counts,
                          diagnosis_count,
                          correct_count,
                          partial_count,
                          last_error_type,
                          source_name,
                          source_section,
                          last_seen_at,
                          last_wrong_at,
                          last_event_at,
                          signal_strength,
                          observation_stage,
                          metadata
                        )
                        VALUES (
                          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT (student_id, question_id) DO UPDATE
                        SET linked_node_ids = EXCLUDED.linked_node_ids,
                            wrong_count = EXCLUDED.wrong_count,
                            review_count = EXCLUDED.review_count,
                            last_result = EXCLUDED.last_result,
                            error_type_counts = EXCLUDED.error_type_counts,
                            diagnosis_count = EXCLUDED.diagnosis_count,
                            correct_count = EXCLUDED.correct_count,
                            partial_count = EXCLUDED.partial_count,
                            last_error_type = EXCLUDED.last_error_type,
                            source_name = EXCLUDED.source_name,
                            source_section = EXCLUDED.source_section,
                            last_seen_at = EXCLUDED.last_seen_at,
                            last_wrong_at = EXCLUDED.last_wrong_at,
                            last_event_at = EXCLUDED.last_event_at,
                            signal_strength = EXCLUDED.signal_strength,
                            observation_stage = EXCLUDED.observation_stage,
                            metadata = EXCLUDED.metadata
                        """,
                        (
                            student_id,
                            question_row_id,
                            normalize_str_list(question_memory.get("linked_node_ids")),
                            int(question_memory.get("wrong_count", 0) or 0),
                            int(question_memory.get("review_count", 0) or 0),
                            self._normalized_question_result_value(question_memory.get("last_result")),
                            jsonb(coerce_json_object(question_memory.get("error_type_counts"))),
                            int(question_memory.get("diagnosis_count", 0) or 0),
                            int(question_memory.get("correct_count", 0) or 0),
                            int(question_memory.get("partial_count", 0) or 0),
                            normalize_text(question_memory.get("last_error_type")),
                            normalize_text(question_memory.get("source_name")),
                            normalize_text(question_memory.get("source_section")),
                            normalize_text(question_memory.get("last_seen_at")),
                            normalize_text(question_memory.get("last_wrong_at")),
                            normalize_text(question_memory.get("last_event_at")),
                            normalize_text(question_memory.get("signal_strength")),
                            normalize_text(question_memory.get("observation_stage")),
                            jsonb(
                                extract_extra_fields(
                                    question_memory,
                                    {
                                        "question_id",
                                        "linked_node_ids",
                                        "wrong_count",
                                        "review_count",
                                        "last_result",
                                        "error_type_counts",
                                        "diagnosis_count",
                                        "correct_count",
                                        "partial_count",
                                        "last_error_type",
                                        "source_name",
                                        "source_section",
                                        "last_seen_at",
                                        "last_wrong_at",
                                        "last_event_at",
                                        "signal_strength",
                                        "observation_stage",
                                        "source_type",
                                    },
                                )
                            ),
                        ),
                    )

                if replace_existing:
                    if active_question_row_ids:
                        cur.execute(
                            """
                            DELETE FROM student_question_memories
                            WHERE student_id = %s
                              AND question_id <> ALL(%s)
                            """,
                            (student_id, active_question_row_ids),
                        )
                    else:
                        cur.execute(
                            "DELETE FROM student_question_memories WHERE student_id = %s",
                            (student_id,),
                        )
        return {
            "student_id": student_uid,
            "node_memory_count": len(active_node_ids),
            "question_memory_count": len(active_question_row_ids),
        }

    def load_memory_profile(self, student_uid: str) -> dict[str, Any] | None:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._get_student_by_uid(cur, student_uid)
                if student is None:
                    return None
                student_id = int(student["id"])
                cur.execute(
                    """
                    SELECT *
                    FROM student_memory_profiles
                    WHERE student_id = %s
                    """,
                    (student_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                raw_profile = coerce_json_object(row["raw_profile"])
                if raw_profile:
                    return raw_profile

                cur.execute(
                    """
                    SELECT *
                    FROM student_node_memories
                    WHERE student_id = %s
                    ORDER BY node_id
                    """,
                    (student_id,),
                )
                node_rows = cur.fetchall()
                cur.execute(
                    """
                    SELECT sqm.*, sq.question_uid
                    FROM student_question_memories sqm
                    JOIN student_questions sq ON sq.id = sqm.question_id
                    WHERE sqm.student_id = %s
                    ORDER BY sq.question_uid
                    """,
                    (student_id,),
                )
                question_rows = cur.fetchall()

        node_memories = [
            {
                "node_id": row["node_id"],
                "error_type_counts": coerce_json_object(row["error_type_counts"]),
                "observed_wrong_count": int(row["observed_wrong_count"] or 0),
                "review_wrong_count": int(row["review_wrong_count"] or 0),
                "mastery_hint": row["mastery_hint"],
                "stability_hint": row["stability_hint"],
                "linked_question_ids": normalize_str_list(row["linked_question_uids"]),
                "diagnosis_count": int(row["diagnosis_count"] or 0),
                "review_correct_count": int(row["review_correct_count"] or 0),
                "review_partial_count": int(row["review_partial_count"] or 0),
                "practice_request_count": int(row["practice_request_count"] or 0),
                "consecutive_wrong_count": int(row["consecutive_wrong_count"] or 0),
                "last_seen_at": isoformat_or_none(row["last_seen_at"]),
                "last_wrong_at": isoformat_or_none(row["last_wrong_at"]),
                "last_event_at": isoformat_or_none(row["last_event_at"]),
                "dominant_error_type": row["dominant_error_type"],
                "recommended_intervention": row["recommended_intervention"],
                "signal_strength": row["signal_strength"],
                "observation_stage": row["observation_stage"],
                **coerce_json_object(row["metadata"]),
            }
            for row in node_rows
        ]
        question_memories = [
            {
                "question_id": row["question_uid"],
                "linked_node_ids": normalize_str_list(row["linked_node_ids"]),
                "wrong_count": int(row["wrong_count"] or 0),
                "review_count": int(row["review_count"] or 0),
                "last_result": row["last_result"],
                "error_type_counts": coerce_json_object(row["error_type_counts"]),
                "diagnosis_count": int(row["diagnosis_count"] or 0),
                "correct_count": int(row["correct_count"] or 0),
                "partial_count": int(row["partial_count"] or 0),
                "last_error_type": row["last_error_type"],
                "source_name": row["source_name"],
                "source_section": row["source_section"],
                "last_seen_at": isoformat_or_none(row["last_seen_at"]),
                "last_wrong_at": isoformat_or_none(row["last_wrong_at"]),
                "last_event_at": isoformat_or_none(row["last_event_at"]),
                "signal_strength": row["signal_strength"],
                "observation_stage": row["observation_stage"],
                **coerce_json_object(row["metadata"]),
            }
            for row in question_rows
        ]
        return {
            "record_id": row["record_uid"],
            "student_id": student_uid,
            "profile_version": row["profile_version"],
            "generated_at": isoformat_or_none(row["generated_at"]),
            "updated_at": isoformat_or_none(row["updated_at"]),
            "error_type_counts": coerce_json_object(row["error_type_counts"]),
            "node_memories": node_memories,
            "question_memories": question_memories,
            "teaching_preferences": coerce_json_object(row["teaching_preferences"]),
            "practice_preferences": coerce_json_object(row["practice_preferences"]),
            "personalization_summary": coerce_json_object(row["personalization_summary"]),
            "memory_graph": coerce_json_object(row["memory_graph"]),
            "agent_memory_text": row["agent_memory_text"] or "",
            "notes": coerce_json_object(row["notes"]),
        }

    def append_memory_event(self, event: dict[str, Any]) -> dict[str, Any]:
        student_uid = normalize_text(event.get("student_id"))
        if student_uid is None:
            raise ValueError("event.student_id is required")
        event_type = normalize_text(event.get("event_type"))
        if event_type not in EVENT_TYPE_VALUES:
            raise ValueError(f"Unsupported event_type: {event_type}")
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._ensure_student(cur, student_uid=student_uid)
                student_id = int(student["id"])
                question_uid = normalize_text(event.get("question_id"))
                question_row_id: int | None = None
                if question_uid is not None:
                    question_row = self._find_question_by_uid(cur, student_id=student_id, question_uid=question_uid)
                    question_row_id = int(question_row["id"]) if question_row is not None else None
                session_uid = normalize_text(event.get("session_id"))
                learning_session_id: int | None = None
                if session_uid is not None:
                    learning_session_row = self._ensure_learning_session(
                        cur,
                        student_id=student_id,
                        session_uid=session_uid,
                        session_type="mixed",
                    )
                    learning_session_id = int(learning_session_row["id"])
                cur.execute(
                    """
                    INSERT INTO student_memory_events (
                      student_id,
                      learning_session_id,
                      event_uid,
                      event_type,
                      occurred_at,
                      student_question_id,
                      question_uid,
                      primary_node_id,
                      secondary_node_ids,
                      source_name,
                      source_section,
                      error_type,
                      result_label,
                      action_type,
                      confidence,
                      payload
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (student_id, event_uid) DO UPDATE
                    SET learning_session_id = EXCLUDED.learning_session_id,
                        event_type = EXCLUDED.event_type,
                        occurred_at = EXCLUDED.occurred_at,
                        student_question_id = EXCLUDED.student_question_id,
                        question_uid = EXCLUDED.question_uid,
                        primary_node_id = EXCLUDED.primary_node_id,
                        secondary_node_ids = EXCLUDED.secondary_node_ids,
                        source_name = EXCLUDED.source_name,
                        source_section = EXCLUDED.source_section,
                        error_type = EXCLUDED.error_type,
                        result_label = EXCLUDED.result_label,
                        action_type = EXCLUDED.action_type,
                        confidence = EXCLUDED.confidence,
                        payload = EXCLUDED.payload
                    RETURNING id
                    """,
                    (
                        student_id,
                        learning_session_id,
                        normalize_text(event.get("event_id")),
                        event_type,
                        normalize_text(event.get("occurred_at")) or datetime.now().isoformat(),
                        question_row_id,
                        question_uid,
                        normalize_text(event.get("primary_node_id")),
                        normalize_str_list(event.get("secondary_node_ids")),
                        normalize_text(event.get("source_name")),
                        normalize_text(event.get("source_section")),
                        self._normalized_error_type(event.get("error_type")),
                        normalize_text(event.get("result")),
                        normalize_text(event.get("action_type")),
                        (
                            float(event.get("confidence"))
                            if event.get("confidence") not in (None, "")
                            else None
                        ),
                        jsonb(event),
                    ),
                )
                cur.fetchone()
        return event

    def load_memory_events(
        self,
        *,
        student_uid: str,
        event_type: str | None = None,
        question_uid: str | None = None,
        node_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        params: list[Any] = [student_uid]
        where_clauses = ["s.student_uid = %s"]
        normalized_event_type = normalize_text(event_type)
        if normalized_event_type is not None:
            where_clauses.append("e.event_type = %s")
            params.append(normalized_event_type)
        normalized_question_uid = normalize_text(question_uid)
        if normalized_question_uid is not None:
            where_clauses.append("e.question_uid = %s")
            params.append(normalized_question_uid)
        normalized_node_id = normalize_text(node_id)
        if normalized_node_id is not None:
            where_clauses.append("(e.primary_node_id = %s OR %s = ANY(e.secondary_node_ids))")
            params.extend([normalized_node_id, normalized_node_id])

        order_sql = "ORDER BY e.occurred_at DESC, e.id DESC"
        limit_sql = ""
        if limit is not None and limit >= 0:
            limit_sql = "LIMIT %s"
            params.append(limit)

        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT e.event_uid, e.event_type, e.occurred_at, e.question_uid, e.primary_node_id,
                           e.secondary_node_ids, e.source_name, e.source_section, e.error_type,
                           e.result_label, e.action_type, e.confidence, e.payload
                    FROM student_memory_events e
                    JOIN students s ON s.id = e.student_id
                    WHERE {' AND '.join(where_clauses)}
                    {order_sql}
                    {limit_sql}
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        rows = list(reversed(rows))
        return [self._memory_event_row_to_payload(row, student_uid=student_uid) for row in rows]

    def save_diagnosis_flow(
        self,
        *,
        student_uid: str,
        diagnosis_uid: str,
        flow_payload: dict[str, Any],
        request_payload: dict[str, Any] | None = None,
        question_uid: str | None = None,
    ) -> dict[str, Any]:
        student_uid = normalize_text(student_uid)
        diagnosis_uid = normalize_text(diagnosis_uid)
        if student_uid is None or diagnosis_uid is None:
            raise ValueError("student_uid and diagnosis_uid are required")
        request_payload = request_payload or {}
        pending = coerce_json_object(flow_payload.get("pending_diagnosis"))
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._ensure_student(cur, student_uid=student_uid)
                student_id = int(student["id"])
                question_row_id = None
                normalized_question_uid = normalize_text(question_uid)
                if normalized_question_uid is not None:
                    question_row = self._ensure_student_question(
                        cur,
                        student_id=student_id,
                        question_uid=normalized_question_uid,
                        question_kind="wrong_question",
                        source_type="manual_entry",
                        stem=normalize_text(request_payload.get("problem_text")) or "",
                        payload={},
                    )
                    question_row_id = int(question_row["id"])
                cur.execute(
                    """
                    INSERT INTO diagnosis_sessions (
                      student_id,
                      question_id,
                      diagnosis_uid,
                      problem_text,
                      reference_answer,
                      student_answer,
                      student_profile_input,
                      max_coach_turns,
                      error_type,
                      reason,
                      evidence,
                      confidence,
                      can_continue,
                      can_enter_coach,
                      result_payload
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (student_id, diagnosis_uid) DO UPDATE
                    SET question_id = EXCLUDED.question_id,
                        problem_text = EXCLUDED.problem_text,
                        reference_answer = EXCLUDED.reference_answer,
                        student_answer = EXCLUDED.student_answer,
                        student_profile_input = EXCLUDED.student_profile_input,
                        max_coach_turns = EXCLUDED.max_coach_turns,
                        error_type = EXCLUDED.error_type,
                        reason = EXCLUDED.reason,
                        evidence = EXCLUDED.evidence,
                        confidence = EXCLUDED.confidence,
                        can_continue = EXCLUDED.can_continue,
                        can_enter_coach = EXCLUDED.can_enter_coach,
                        result_payload = EXCLUDED.result_payload
                    RETURNING id
                    """,
                    (
                        student_id,
                        question_row_id,
                        diagnosis_uid,
                        normalize_text(request_payload.get("problem_text")) or "",
                        normalize_text(request_payload.get("reference_answer")),
                        normalize_text(request_payload.get("student_answer")),
                        normalize_text(request_payload.get("student_profile")),
                        (
                            int(request_payload.get("max_turns"))
                            if request_payload.get("max_turns") not in (None, "")
                            else None
                        ),
                        self._normalized_error_type(pending.get("error_type")),
                        normalize_text(pending.get("reason")),
                        normalize_text(pending.get("evidence")),
                        (
                            float(pending.get("confidence"))
                            if pending.get("confidence") not in (None, "")
                            else None
                        ),
                        bool(flow_payload.get("can_continue")),
                        bool(flow_payload.get("can_enter_coach")),
                        jsonb({"request": request_payload, "flow": flow_payload}),
                    ),
                )
                session_row = cur.fetchone()
                session_id = int(session_row["id"])
                cur.execute(
                    "DELETE FROM diagnosis_messages WHERE diagnosis_session_id = %s",
                    (session_id,),
                )
                for index, message in enumerate(coerce_json_list(flow_payload.get("chat_history"))):
                    message_payload = message if isinstance(message, dict) else {}
                    cur.execute(
                        """
                        INSERT INTO diagnosis_messages (
                          diagnosis_session_id,
                          message_index,
                          speaker,
                          content,
                          payload
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            session_id,
                            index,
                            speaker_from_message(message_payload.get("role")),
                            str(message_payload.get("content") or ""),
                            jsonb(message_payload),
                        ),
                    )
        return {
            "student_id": student_uid,
            "diagnosis_uid": diagnosis_uid,
        }

    def load_diagnosis_flow(self, *, student_uid: str, diagnosis_uid: str) -> dict[str, Any] | None:
        student_uid = normalize_text(student_uid)
        diagnosis_uid = normalize_text(diagnosis_uid)
        if student_uid is None or diagnosis_uid is None:
            raise ValueError("student_uid and diagnosis_uid are required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT ds.id, ds.result_payload
                    FROM diagnosis_sessions ds
                    JOIN students s ON s.id = ds.student_id
                    WHERE s.student_uid = %s AND ds.diagnosis_uid = %s
                    """,
                    (student_uid, diagnosis_uid),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                payload = coerce_json_object(row["result_payload"])
                cur.execute(
                    """
                    SELECT payload
                    FROM diagnosis_messages
                    WHERE diagnosis_session_id = %s
                    ORDER BY message_index
                    """,
                    (row["id"],),
                )
                messages = [coerce_json_object(message_row["payload"]) for message_row in cur.fetchall()]
        flow = coerce_json_object(payload.get("flow"))
        flow["chat_history"] = messages
        return {
            "request": coerce_json_object(payload.get("request")),
            "flow": flow,
        }

    def save_coach_chat(
        self,
        *,
        student_uid: str,
        coach_uid: str,
        chat_payload: dict[str, Any],
        request_payload: dict[str, Any] | None = None,
        question_uid: str | None = None,
    ) -> dict[str, Any]:
        student_uid = normalize_text(student_uid)
        coach_uid = normalize_text(coach_uid)
        if student_uid is None or coach_uid is None:
            raise ValueError("student_uid and coach_uid are required")
        request_payload = request_payload or {}
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._ensure_student(cur, student_uid=student_uid)
                student_id = int(student["id"])
                question_row_id = None
                normalized_question_uid = normalize_text(question_uid)
                if normalized_question_uid is not None:
                    question_row = self._ensure_student_question(
                        cur,
                        student_id=student_id,
                        question_uid=normalized_question_uid,
                        question_kind="wrong_question",
                        source_type="manual_entry",
                        stem=normalize_text(request_payload.get("problem_text")) or "",
                        payload={},
                    )
                    question_row_id = int(question_row["id"])
                cur.execute(
                    """
                    INSERT INTO coach_sessions (
                      student_id,
                      question_id,
                      coach_uid,
                      error_type,
                      coach_mode,
                      max_turns,
                      turn_index,
                      done,
                      stop_reason,
                      student_profile_input,
                      result_payload
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (student_id, coach_uid) DO UPDATE
                    SET question_id = EXCLUDED.question_id,
                        error_type = EXCLUDED.error_type,
                        coach_mode = EXCLUDED.coach_mode,
                        max_turns = EXCLUDED.max_turns,
                        turn_index = EXCLUDED.turn_index,
                        done = EXCLUDED.done,
                        stop_reason = EXCLUDED.stop_reason,
                        student_profile_input = EXCLUDED.student_profile_input,
                        result_payload = EXCLUDED.result_payload
                    RETURNING id
                    """,
                    (
                        student_id,
                        question_row_id,
                        coach_uid,
                        self._normalized_error_type(request_payload.get("error_type") or chat_payload.get("error_type")),
                        normalize_text(chat_payload.get("coach_mode")),
                        int(chat_payload.get("max_turns", 0) or 0),
                        int(chat_payload.get("turn_index", 0) or 0),
                        bool(chat_payload.get("done")),
                        normalize_text(chat_payload.get("stop_reason")),
                        normalize_text(request_payload.get("student_profile")),
                        jsonb({"request": request_payload, "chat": chat_payload}),
                    ),
                )
                session_row = cur.fetchone()
                session_id = int(session_row["id"])
                cur.execute(
                    "DELETE FROM coach_messages WHERE coach_session_id = %s",
                    (session_id,),
                )
                for index, message in enumerate(coerce_json_list(chat_payload.get("chat_history"))):
                    message_payload = message if isinstance(message, dict) else {}
                    cur.execute(
                        """
                        INSERT INTO coach_messages (
                          coach_session_id,
                          message_index,
                          speaker,
                          content,
                          payload
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            session_id,
                            index,
                            speaker_from_message(message_payload.get("role")),
                            str(message_payload.get("content") or ""),
                            jsonb(message_payload),
                        ),
                    )
        return {
            "student_id": student_uid,
            "coach_uid": coach_uid,
        }

    def load_coach_chat(self, *, student_uid: str, coach_uid: str) -> dict[str, Any] | None:
        student_uid = normalize_text(student_uid)
        coach_uid = normalize_text(coach_uid)
        if student_uid is None or coach_uid is None:
            raise ValueError("student_uid and coach_uid are required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cs.id, cs.result_payload
                    FROM coach_sessions cs
                    JOIN students s ON s.id = cs.student_id
                    WHERE s.student_uid = %s AND cs.coach_uid = %s
                    """,
                    (student_uid, coach_uid),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                payload = coerce_json_object(row["result_payload"])
                cur.execute(
                    """
                    SELECT payload
                    FROM coach_messages
                    WHERE coach_session_id = %s
                    ORDER BY message_index
                    """,
                    (row["id"],),
                )
                messages = [coerce_json_object(message_row["payload"]) for message_row in cur.fetchall()]
        chat = coerce_json_object(payload.get("chat"))
        chat["chat_history"] = messages
        return {
            "request": coerce_json_object(payload.get("request")),
            "chat": chat,
        }

    def reset_student_runtime(self, student_uid: str) -> dict[str, Any]:
        student_uid = normalize_text(student_uid)
        if student_uid is None:
            raise ValueError("student_uid is required")
        with self.connection() as conn:
            with conn.cursor() as cur:
                student = self._get_student_by_uid(cur, student_uid)
                if student is None:
                    return {"student_id": student_uid, "cleared": False}
                student_id = int(student["id"])
                cur.execute("DELETE FROM diagnosis_sessions WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM coach_sessions WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM student_memory_events WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM student_node_memories WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM student_question_memories WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM student_memory_profiles WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM student_question_states WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM student_node_states WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM student_review_states WHERE student_id = %s", (student_id,))
                cur.execute("DELETE FROM student_questions WHERE student_id = %s", (student_id,))
                cur.execute(
                    """
                    DELETE FROM knowledge_nodes
                    WHERE owner_student_id = %s
                      AND source_scope = 'student_custom'
                    """,
                    (student_id,),
                )
        return {"student_id": student_uid, "cleared": True}

    def _get_student_by_uid(self, cur: Any, student_uid: str) -> dict[str, Any] | None:
        cur.execute(
            """
            SELECT id, student_uid, display_name, grade_level, status, metadata, created_at, updated_at
            FROM students
            WHERE student_uid = %s
            """,
            (student_uid,),
        )
        return cur.fetchone()

    def _ensure_student(
        self,
        cur: Any,
        *,
        student_uid: str,
        display_name: str | None = None,
        grade_level: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        cur.execute(
            """
            INSERT INTO students (
              student_uid,
              display_name,
              grade_level,
              metadata
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (student_uid) DO UPDATE
            SET display_name = COALESCE(EXCLUDED.display_name, students.display_name),
                grade_level = COALESCE(EXCLUDED.grade_level, students.grade_level),
                metadata = students.metadata || EXCLUDED.metadata
            RETURNING id, student_uid, display_name, grade_level, status, metadata, created_at, updated_at
            """,
            (
                student_uid,
                normalize_text(display_name),
                normalize_text(grade_level),
                jsonb(coerce_json_object(metadata)),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to create or load student")
        return row

    def _ensure_learning_session(
        self,
        cur: Any,
        *,
        student_id: int,
        session_uid: str,
        session_type: str,
    ) -> dict[str, Any]:
        cur.execute(
            """
            INSERT INTO learning_sessions (
              student_id,
              session_uid,
              session_type
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (student_id, session_uid) DO UPDATE
            SET session_type = EXCLUDED.session_type
            RETURNING id, student_id, session_uid, session_type, started_at, ended_at
            """,
            (student_id, session_uid, session_type),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to create or load learning session")
        return row

    def _upsert_knowledge_node(
        self,
        cur: Any,
        node_payload: dict[str, Any],
        *,
        owner_student_id: int | None,
        source_scope: str,
    ) -> dict[str, Any]:
        node_id = normalize_text(node_payload.get("node_id"))
        parent_node_id = normalize_text(node_payload.get("parent_id") or node_payload.get("parent_node_id"))
        name = normalize_text(node_payload.get("name") or node_payload.get("title"))
        if node_id is None:
            if parent_node_id is None or name is None:
                raise ValueError("custom node requires node_id or parent_id + name")
            slug = name.replace(" ", "_").replace("/", "_")
            node_id = f"{parent_node_id}.{slug}"
        if name is None:
            raise ValueError("knowledge node name is required")
        path = normalize_str_list(node_payload.get("path"))
        if not path and parent_node_id is not None:
            cur.execute(
                "SELECT path, name FROM knowledge_nodes WHERE node_id = %s",
                (parent_node_id,),
            )
            parent = cur.fetchone()
            if parent is not None:
                parent_path = normalize_str_list(parent.get("path"))
                parent_name = normalize_text(parent.get("name"))
                path = parent_path or ([parent_name] if parent_name else [])
                path.append(name)
        elif not path:
            path = [name]
        path_text = normalize_text(node_payload.get("path_text")) or " > ".join(path)
        cur.execute(
            """
            INSERT INTO knowledge_nodes (
              node_id,
              owner_student_id,
              parent_node_id,
              name,
              level,
              is_leaf,
              node_kind,
              review_role,
              binding_role,
              path,
              path_text,
              aliases,
              common_errors,
              typing_source,
              source_scope
            )
            VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (node_id) DO UPDATE
            SET owner_student_id = EXCLUDED.owner_student_id,
                parent_node_id = EXCLUDED.parent_node_id,
                name = EXCLUDED.name,
                level = EXCLUDED.level,
                is_leaf = EXCLUDED.is_leaf,
                node_kind = EXCLUDED.node_kind,
                review_role = EXCLUDED.review_role,
                binding_role = EXCLUDED.binding_role,
                path = EXCLUDED.path,
                path_text = EXCLUDED.path_text,
                aliases = EXCLUDED.aliases,
                common_errors = EXCLUDED.common_errors,
                typing_source = EXCLUDED.typing_source,
                source_scope = EXCLUDED.source_scope
            RETURNING node_id, parent_node_id, name, level, is_leaf, node_kind, review_role,
                      binding_role, path, path_text, aliases, common_errors, typing_source,
                      source_scope, created_at, updated_at
            """,
            (
                node_id,
                owner_student_id,
                parent_node_id,
                name,
                int(node_payload.get("level", len(path) - 1) or 0),
                bool(node_payload.get("is_leaf", True)),
                normalize_text(node_payload.get("node_kind")) or ("custom" if source_scope == "student_custom" else "leaf"),
                normalize_text(node_payload.get("review_role")),
                normalize_text(node_payload.get("binding_role")),
                path,
                path_text,
                normalize_str_list(node_payload.get("aliases")),
                normalize_str_list(node_payload.get("common_errors")),
                normalize_text(node_payload.get("typing_source")) or ("custom_ui" if source_scope == "student_custom" else "inventory_seed"),
                source_scope,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to save knowledge node")
        return row

    def _ensure_student_question(
        self,
        cur: Any,
        *,
        student_id: int,
        question_uid: str,
        question_kind: str,
        source_type: str,
        stem: str,
        payload: dict[str, Any],
        source_batch_id: str | None = None,
        source_name: str | None = None,
        source_section: str | None = None,
        source_chapter: str | None = None,
        question_type: str | None = None,
        student_answer: str | None = None,
        correct_answer: str | None = None,
        solution_text: str | None = None,
        priority_note: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        normalized_kind = question_kind if question_kind in QUESTION_KIND_VALUES else "wrong_question"
        cur.execute(
            """
            INSERT INTO student_questions (
              student_id,
              question_uid,
              question_kind,
              source_type,
              source_batch_id,
              source_name,
              source_section,
              source_chapter,
              question_type,
              stem,
              student_answer,
              correct_answer,
              solution_text,
              priority_note,
              note,
              payload
            )
            VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (student_id, question_uid) DO UPDATE
            SET question_kind = EXCLUDED.question_kind,
                source_type = COALESCE(NULLIF(EXCLUDED.source_type, ''), student_questions.source_type),
                source_batch_id = COALESCE(EXCLUDED.source_batch_id, student_questions.source_batch_id),
                source_name = COALESCE(EXCLUDED.source_name, student_questions.source_name),
                source_section = COALESCE(EXCLUDED.source_section, student_questions.source_section),
                source_chapter = COALESCE(EXCLUDED.source_chapter, student_questions.source_chapter),
                question_type = COALESCE(EXCLUDED.question_type, student_questions.question_type),
                stem = COALESCE(NULLIF(EXCLUDED.stem, ''), student_questions.stem),
                student_answer = COALESCE(EXCLUDED.student_answer, student_questions.student_answer),
                correct_answer = COALESCE(EXCLUDED.correct_answer, student_questions.correct_answer),
                solution_text = COALESCE(EXCLUDED.solution_text, student_questions.solution_text),
                priority_note = COALESCE(EXCLUDED.priority_note, student_questions.priority_note),
                note = COALESCE(EXCLUDED.note, student_questions.note),
                payload = CASE
                  WHEN EXCLUDED.payload = '{}'::jsonb THEN student_questions.payload
                  ELSE EXCLUDED.payload
                END
            RETURNING id, question_uid
            """,
            (
                student_id,
                question_uid,
                normalized_kind,
                source_type,
                source_batch_id,
                source_name,
                source_section,
                source_chapter,
                question_type,
                stem,
                student_answer,
                correct_answer,
                solution_text,
                priority_note,
                note,
                jsonb(coerce_json_object(payload)),
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to save student question")
        return row

    def _find_question_by_uid(self, cur: Any, *, student_id: int, question_uid: str) -> dict[str, Any] | None:
        cur.execute(
            """
            SELECT id, question_uid
            FROM student_questions
            WHERE student_id = %s AND question_uid = %s
            """,
            (student_id, question_uid),
        )
        return cur.fetchone()

    def _replace_question_links(self, cur: Any, question_row_id: int, question_state: dict[str, Any]) -> None:
        primary_node_ids = normalize_str_list(question_state.get("primary_node_ids"))
        secondary_node_ids = normalize_str_list(question_state.get("secondary_node_ids"))
        linked_node_ids = unique_str_list(
            primary_node_ids
            + secondary_node_ids
            + normalize_str_list(question_state.get("linked_node_ids"))
        )
        cur.execute(
            "DELETE FROM student_question_node_links WHERE question_id = %s",
            (question_row_id,),
        )
        primary_set = set(primary_node_ids)
        for node_id in linked_node_ids:
            cur.execute(
                """
                INSERT INTO student_question_node_links (
                  question_id,
                  node_id,
                  link_role
                )
                VALUES (%s, %s, %s)
                """,
                (
                    question_row_id,
                    node_id,
                    "primary" if node_id in primary_set else "secondary",
                ),
            )

    def _normalized_review_state_value(self, value: Any) -> str:
        text = normalize_text(value) or "new"
        return text if text in REVIEW_STATE_VALUES else "new"

    def _normalized_question_result_value(self, value: Any) -> str:
        text = normalize_text(value) or "unseen"
        return text if text in QUESTION_RESULT_VALUES else "unseen"

    def _normalized_error_type(self, value: Any) -> str | None:
        text = normalize_text(value)
        if text is None:
            return None
        return text if text in ERROR_TYPE_VALUES else None

    def _student_row_to_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "student_uid": row["student_uid"],
            "display_name": row["display_name"],
            "grade_level": row["grade_level"],
            "status": row["status"],
            "metadata": coerce_json_object(row["metadata"]),
            "created_at": isoformat_or_none(row["created_at"]),
            "updated_at": isoformat_or_none(row["updated_at"]),
        }

    def _knowledge_node_row_to_dict(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "node_id": row["node_id"],
            "parent_id": row["parent_node_id"],
            "name": row["name"],
            "level": int(row["level"] or 0),
            "is_leaf": bool(row["is_leaf"]),
            "node_kind": row["node_kind"],
            "review_role": row.get("review_role"),
            "binding_role": row.get("binding_role"),
            "path": normalize_str_list(row.get("path")),
            "path_text": row.get("path_text"),
            "aliases": normalize_str_list(row.get("aliases")),
            "common_errors": normalize_str_list(row.get("common_errors")),
            "typing_source": row.get("typing_source"),
            "source_scope": row.get("source_scope"),
            "created_at": isoformat_or_none(row.get("created_at")),
            "updated_at": isoformat_or_none(row.get("updated_at")),
        }

    def _memory_event_row_to_payload(self, row: dict[str, Any], *, student_uid: str) -> dict[str, Any]:
        payload = coerce_json_object(row["payload"]).copy()
        payload.setdefault("event_id", row["event_uid"])
        payload.setdefault("event_type", row["event_type"])
        payload.setdefault("student_id", student_uid)
        payload.setdefault("occurred_at", isoformat_or_none(row["occurred_at"]))
        payload.setdefault("question_id", row["question_uid"])
        payload.setdefault("primary_node_id", row["primary_node_id"])
        payload.setdefault("secondary_node_ids", normalize_str_list(row["secondary_node_ids"]))
        payload.setdefault("source_name", row["source_name"])
        payload.setdefault("source_section", row["source_section"])
        payload.setdefault("error_type", row["error_type"])
        if row["result_label"] is not None:
            payload.setdefault("result", row["result_label"])
        if row["action_type"] is not None:
            payload.setdefault("action_type", row["action_type"])
        if row["confidence"] is not None:
            payload.setdefault("confidence", row["confidence"])
        return payload


__all__ = [
    "DEFAULT_SCHEMA_PATH",
    "PostgresStoreConfig",
    "TeachAgentPostgresStore",
    "database_url_from_env",
    "load_teachagent_env",
]

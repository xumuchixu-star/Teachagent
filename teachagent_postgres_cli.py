from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from teachagent_postgres_store import TeachAgentPostgresStore


ROOT = Path(__file__).resolve().parent
APP_ROOT = ROOT / "app"
STUDENT_DATA_ROOT = APP_ROOT / "data" / "students"
TREE_DATA_PATH = ROOT / "docs" / "rag_inventory" / "knowledge_tree_typed_full.json"


def read_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def empty_review_state(student_id: str) -> dict[str, Any]:
    return {
        "record_id": f"review_state.blank.{student_id}",
        "student_id": student_id,
        "generated_at": datetime.now().astimezone().isoformat(),
        "knowledge_point_states": [],
        "example_question_states": [],
        "review_plan": {},
        "notes": {},
    }


def load_system_tree_nodes() -> list[dict[str, Any]]:
    payload = read_json(TREE_DATA_PATH, default={"nodes": []})
    return [
        node
        for node in payload.get("nodes", [])
        if isinstance(node, dict)
    ]


def discover_student_ids(*, students_root: Path, include_temp: bool) -> list[str]:
    if not students_root.exists():
        return []
    result: list[str] = []
    for path in sorted(students_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir():
            continue
        name = path.name.strip()
        if not name or name.startswith("."):
            continue
        if not include_temp and name.startswith("tmp_"):
            continue
        result.append(name)
    return result


def compose_local_review_state(student_id: str, student_dir: Path) -> dict[str, Any]:
    review_state = read_json(
        student_dir / "review_state.session.json",
        default=empty_review_state(student_id),
    )
    if not isinstance(review_state, dict):
        review_state = empty_review_state(student_id)
    review_state["student_id"] = student_id
    review_state.setdefault("record_id", f"review_state.blank.{student_id}")
    review_state.setdefault("generated_at", datetime.now().astimezone().isoformat())
    review_state.setdefault("knowledge_point_states", [])
    review_state.setdefault("example_question_states", [])
    review_state.setdefault("review_plan", {})
    review_state.setdefault("notes", {})

    wrongbook_payload = read_json(
        student_dir / "wrongbook_custom_questions.session.json",
        default={"questions": []},
    )
    merged_questions = list(review_state.get("example_question_states") or [])
    existing_ids = {
        str(item.get("question_id") or "").strip()
        for item in merged_questions
        if isinstance(item, dict)
    }
    for item in wrongbook_payload.get("questions", []):
        if not isinstance(item, dict):
            continue
        question_id = str(item.get("question_id") or "").strip()
        if not question_id or question_id in existing_ids:
            continue
        merged_questions.append(item)
        existing_ids.add(question_id)
    review_state["example_question_states"] = merged_questions
    return review_state


def import_student_from_local(
    store: TeachAgentPostgresStore,
    *,
    student_id: str,
    students_root: Path,
) -> dict[str, Any]:
    student_dir = students_root / student_id
    if not student_dir.exists():
        raise FileNotFoundError(f"Student directory not found: {student_dir}")

    store.get_or_create_student(student_id)

    custom_nodes_payload = read_json(
        student_dir / "tree_custom_nodes.session.json",
        default={"nodes": []},
    )
    custom_nodes = [
        node
        for node in custom_nodes_payload.get("nodes", [])
        if isinstance(node, dict)
    ]
    if custom_nodes:
        store.upsert_knowledge_nodes(custom_nodes, owner_student_uid=student_id)

    review_state = compose_local_review_state(student_id, student_dir)
    review_summary = store.save_review_state(review_state)

    note_count = 0
    tree_notes = read_json(student_dir / "tree_notes.session.json", default={})
    if isinstance(tree_notes, dict):
        for question_id, note in tree_notes.items():
            question_uid = str(question_id or "").strip()
            text = str(note or "").strip()
            if not question_uid or not text:
                continue
            store.save_question_note(student_id, question_uid, text)
            note_count += 1

    profile_summary: dict[str, Any] | None = None
    profile_path = student_dir / "student_memory_profile.session.json"
    if profile_path.exists():
        profile = read_json(profile_path, default={})
        if isinstance(profile, dict):
            profile["student_id"] = student_id
            profile_summary = store.save_memory_profile(profile)

    event_count = 0
    for event in read_jsonl(student_dir / "student_memory_events.jsonl"):
        event_payload = dict(event)
        event_payload["student_id"] = student_id
        if not str(event_payload.get("event_type") or "").strip():
            continue
        store.append_memory_event(event_payload)
        event_count += 1

    return {
        "student_id": student_id,
        "student_dir": str(student_dir),
        "custom_node_count": len(custom_nodes),
        "note_count": note_count,
        "event_count": event_count,
        "review_state": review_summary,
        "memory_profile": profile_summary,
    }


def print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def handle_ping(_: argparse.Namespace) -> int:
    store = TeachAgentPostgresStore()
    print_json(
        {
            "ok": True,
            "command": "ping",
            "database": store.ping(),
        }
    )
    return 0


def handle_init_schema(args: argparse.Namespace) -> int:
    store = TeachAgentPostgresStore()
    schema_path = Path(args.schema_path).expanduser().resolve() if args.schema_path else store.schema_path
    result = store.apply_schema(schema_path=schema_path)
    print_json(
        {
            "ok": True,
            "command": "init-schema",
            **result,
        }
    )
    return 0


def handle_seed_tree(_: argparse.Namespace) -> int:
    store = TeachAgentPostgresStore()
    nodes = load_system_tree_nodes()
    count = store.upsert_knowledge_nodes(nodes)
    print_json(
        {
            "ok": True,
            "command": "seed-tree",
            "node_count": count,
            "tree_path": str(TREE_DATA_PATH),
        }
    )
    return 0


def resolve_target_student_ids(args: argparse.Namespace) -> list[str]:
    explicit_ids = [str(item).strip() for item in (args.student_id or []) if str(item).strip()]
    if explicit_ids:
        return explicit_ids
    if getattr(args, "all_students", False):
        return discover_student_ids(
            students_root=Path(args.students_root).expanduser().resolve(),
            include_temp=bool(getattr(args, "include_temp", False)),
        )
    raise ValueError("Provide --student-id or --all-students")


def handle_import_local(args: argparse.Namespace) -> int:
    students_root = Path(args.students_root).expanduser().resolve()
    student_ids = resolve_target_student_ids(args)
    store = TeachAgentPostgresStore()
    results = [
        import_student_from_local(store, student_id=student_id, students_root=students_root)
        for student_id in student_ids
    ]
    print_json(
        {
            "ok": True,
            "command": "import-local",
            "students_root": str(students_root),
            "student_count": len(results),
            "students": results,
        }
    )
    return 0


def handle_bootstrap(args: argparse.Namespace) -> int:
    store = TeachAgentPostgresStore()
    schema_path = Path(args.schema_path).expanduser().resolve() if args.schema_path else store.schema_path
    schema_result = store.apply_schema(schema_path=schema_path)
    tree_nodes = load_system_tree_nodes()
    seeded_count = store.upsert_knowledge_nodes(tree_nodes)

    students_root = Path(args.students_root).expanduser().resolve()
    imported_students: list[dict[str, Any]] = []
    if args.student_id or args.all_students:
        student_ids = resolve_target_student_ids(args)
        imported_students = [
            import_student_from_local(store, student_id=student_id, students_root=students_root)
            for student_id in student_ids
        ]

    print_json(
        {
            "ok": True,
            "command": "bootstrap",
            "schema": schema_result,
            "seeded_tree_node_count": seeded_count,
            "imported_student_count": len(imported_students),
            "students": imported_students,
            "database": store.ping(),
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TeachAgent PostgreSQL bootstrap and migration helper."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ping_parser = subparsers.add_parser("ping", help="Check PostgreSQL connectivity.")
    ping_parser.set_defaults(handler=handle_ping)

    init_parser = subparsers.add_parser("init-schema", help="Apply the PostgreSQL schema.")
    init_parser.add_argument(
        "--schema-path",
        default=None,
        help="Optional custom schema path. Defaults to docs/db/teachagent_postgres_mvp.sql",
    )
    init_parser.set_defaults(handler=handle_init_schema)

    seed_parser = subparsers.add_parser("seed-tree", help="Seed system knowledge nodes into PostgreSQL.")
    seed_parser.set_defaults(handler=handle_seed_tree)

    for name, help_text, handler in [
        ("import-local", "Import one or more local students into PostgreSQL.", handle_import_local),
        ("bootstrap", "Apply schema, seed tree, and optionally import local students.", handle_bootstrap),
    ]:
        subparser = subparsers.add_parser(name, help=help_text)
        if name == "bootstrap":
            subparser.add_argument(
                "--schema-path",
                default=None,
                help="Optional custom schema path. Defaults to docs/db/teachagent_postgres_mvp.sql",
            )
        subparser.add_argument(
            "--students-root",
            default=str(STUDENT_DATA_ROOT),
            help="Directory containing per-student local JSON folders.",
        )
        subparser.add_argument(
            "--student-id",
            action="append",
            default=[],
            help="Import a specific student_id. Repeatable.",
        )
        subparser.add_argument(
            "--all-students",
            action="store_true",
            help="Import every student folder under --students-root.",
        )
        subparser.add_argument(
            "--include-temp",
            action="store_true",
            help="Include folders starting with tmp_.",
        )
        subparser.set_defaults(handler=handler)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())

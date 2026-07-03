from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from student_memory_manager import build_profile


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
DEFAULT_EVENTS_DIR = ROOT / "data" / "student_memory"
DEFAULT_EVENTS_PATH = DEFAULT_EVENTS_DIR / "student_memory_events.jsonl"

SUPPORTED_EVENT_TYPES = {
    "diagnosis",
    "coach",
    "review",
    "binding",
    "student_choice",
}


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent_dir(path)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSONL at {path}:{line_number}: {exc.msg}"
                ) from exc
            if isinstance(payload, dict):
                yield payload


def append_event(
    event: dict[str, Any],
    *,
    path: Path = DEFAULT_EVENTS_PATH,
) -> dict[str, Any]:
    event_type = normalize_text(event.get("event_type"))
    if event_type is None:
        raise ValueError("event_type is required")
    if event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(f"Unsupported event_type: {event_type}")
    occurred_at = normalize_text(event.get("occurred_at"))
    if occurred_at is None:
        raise ValueError("occurred_at is required")

    ensure_parent_dir(path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def load_events(
    *,
    path: Path = DEFAULT_EVENTS_PATH,
    student_id: str | None = None,
    event_type: str | None = None,
    question_id: str | None = None,
    node_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    normalized_student_id = normalize_text(student_id)
    normalized_event_type = normalize_text(event_type)
    normalized_question_id = normalize_text(question_id)
    normalized_node_id = normalize_text(node_id)

    for event in iter_jsonl(path) or []:
        if normalized_student_id is not None and normalize_text(event.get("student_id")) != normalized_student_id:
            continue
        if normalized_event_type is not None and normalize_text(event.get("event_type")) != normalized_event_type:
            continue
        if normalized_question_id is not None and normalize_text(event.get("question_id")) != normalized_question_id:
            continue
        if normalized_node_id is not None:
            primary_node_id = normalize_text(event.get("primary_node_id"))
            secondary_node_ids = event.get("secondary_node_ids")
            linked_node_ids = event.get("linked_node_ids")
            node_candidates = {
                primary_node_id,
                *(str(item).strip() for item in secondary_node_ids or [] if str(item).strip()),
                *(str(item).strip() for item in linked_node_ids or [] if str(item).strip()),
            }
            if normalized_node_id not in node_candidates:
                continue
        filtered.append(event)

    filtered.sort(
        key=lambda item: (
            normalize_text(item.get("occurred_at")) or "",
            normalize_text(item.get("event_id")) or "",
        )
    )
    if limit is not None and limit >= 0:
        return filtered[-limit:]
    return filtered


def bucket_events_by_type(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        event_type = normalize_text(event.get("event_type"))
        if event_type is None:
            continue
        buckets[event_type].append(event)
    return dict(buckets)


def build_profile_from_store(
    *,
    student_id: str,
    path: Path = DEFAULT_EVENTS_PATH,
    review_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = load_events(path=path, student_id=student_id)
    return build_profile(
        student_id=student_id,
        review_state=review_state,
        events=events,
    )


@dataclass(frozen=True)
class StoreStats:
    path: str
    total_events: int
    event_type_counts: dict[str, int]
    distinct_students: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "total_events": self.total_events,
            "event_type_counts": self.event_type_counts,
            "distinct_students": self.distinct_students,
        }


def summarize_store(path: Path = DEFAULT_EVENTS_PATH) -> StoreStats:
    counts: dict[str, int] = defaultdict(int)
    students: set[str] = set()
    total = 0
    for event in iter_jsonl(path) or []:
        total += 1
        event_type = normalize_text(event.get("event_type")) or "unknown"
        counts[event_type] += 1
        student_id = normalize_text(event.get("student_id"))
        if student_id:
            students.add(student_id)
    return StoreStats(
        path=str(path),
        total_events=total,
        event_type_counts=dict(sorted(counts.items())),
        distinct_students=len(students),
    )


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append")
    append_parser.add_argument("--event-json", required=True, help="Path to one JSON event object")
    append_parser.add_argument("--events-path", default=str(DEFAULT_EVENTS_PATH))

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--events-path", default=str(DEFAULT_EVENTS_PATH))
    list_parser.add_argument("--student-id")
    list_parser.add_argument("--event-type")
    list_parser.add_argument("--question-id")
    list_parser.add_argument("--node-id")
    list_parser.add_argument("--limit", type=int)

    profile_parser = subparsers.add_parser("build-profile")
    profile_parser.add_argument("--student-id", required=True)
    profile_parser.add_argument("--events-path", default=str(DEFAULT_EVENTS_PATH))
    profile_parser.add_argument("--review-state")
    profile_parser.add_argument("--out-json")

    stats_parser = subparsers.add_parser("stats")
    stats_parser.add_argument("--events-path", default=str(DEFAULT_EVENTS_PATH))

    args = parser.parse_args()
    events_path = Path(args.events_path)

    if args.command == "append":
        payload = load_json(Path(args.event_json))
        if not isinstance(payload, dict):
            raise ValueError("event-json must be a JSON object")
        event = append_event(payload, path=events_path)
        print(json.dumps(event, ensure_ascii=False, indent=2))
        return

    if args.command == "list":
        events = load_events(
            path=events_path,
            student_id=args.student_id,
            event_type=args.event_type,
            question_id=args.question_id,
            node_id=args.node_id,
            limit=args.limit,
        )
        print(json.dumps(events, ensure_ascii=False, indent=2))
        return

    if args.command == "build-profile":
        review_state = load_json(Path(args.review_state)) if args.review_state else None
        profile = build_profile_from_store(
            student_id=args.student_id,
            path=events_path,
            review_state=review_state,
        )
        if args.out_json:
            write_json(Path(args.out_json), profile)
        else:
            print(json.dumps(profile, ensure_ascii=False, indent=2))
        return

    if args.command == "stats":
        stats = summarize_store(events_path)
        print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

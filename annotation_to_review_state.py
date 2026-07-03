from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")

DEFAULT_SOURCE_BATCH_ID = "student_annotation_batch"
DEFAULT_PRIORITY_NOTE = "学生确认知识点后导入复习系统"


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            text = normalize_text(item)
            if text:
                values.append(text)
        return values
    text = normalize_text(value)
    return [text] if text else []


def unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        items.append(value)
    return items


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_annotation_records(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        records = payload.get("records")
        if isinstance(records, list):
            return [item for item in records if isinstance(item, dict)]
        return [payload]
    raise ValueError(f"Unsupported annotation payload shape: {path}")


def load_review_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    payload = load_json(path)
    if isinstance(payload, dict) and isinstance(payload.get("updated_payload"), dict):
        return payload["updated_payload"]
    return payload


def build_empty_review_state(
    *,
    record_id: str,
    student_id: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "record_id": record_id,
        "student_id": student_id,
        "generated_at": generated_at,
        "knowledge_point_states": [],
        "example_question_states": [],
        "notes": {},
    }


def normalize_notes_container(notes: Any) -> dict[str, Any]:
    if isinstance(notes, dict):
        return notes
    if isinstance(notes, list):
        return {
            "legacy_notes": notes,
        }
    return {}


def extract_selected_nodes(record: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    student_selection = record.get("student_selection") or {}
    primary_node_ids = normalize_str_list(student_selection.get("primary_node_ids"))
    secondary_node_ids = normalize_str_list(student_selection.get("secondary_node_ids"))
    selected_node_ids = normalize_str_list(student_selection.get("selected_node_ids"))

    if not selected_node_ids:
        selected_node_ids = unique_list(primary_node_ids + secondary_node_ids)

    if not selected_node_ids:
        review_linkage = record.get("review_linkage") or {}
        selected_node_ids = normalize_str_list(review_linkage.get("review_node_ids"))

    if not primary_node_ids and selected_node_ids:
        primary_node_ids = selected_node_ids[:1]

    if not secondary_node_ids and len(selected_node_ids) > 1:
        primary_set = set(primary_node_ids)
        secondary_node_ids = [node_id for node_id in selected_node_ids if node_id not in primary_set]

    return (
        unique_list(selected_node_ids),
        unique_list(primary_node_ids),
        unique_list(secondary_node_ids),
    )


def question_priority_note(record: dict[str, Any]) -> str:
    student_selection = record.get("student_selection") or {}
    selection_notes = normalize_text(student_selection.get("selection_notes"))
    if selection_notes:
        return selection_notes
    review_linkage = record.get("review_linkage") or {}
    review_notes = normalize_text(review_linkage.get("review_notes"))
    if review_notes:
        return review_notes
    return DEFAULT_PRIORITY_NOTE


def build_question_state(
    record: dict[str, Any],
    *,
    source_batch_id: str,
    created_at: str,
) -> dict[str, Any] | None:
    question_id = normalize_text(record.get("question_id"))
    if not question_id:
        return None

    linked_node_ids, primary_node_ids, secondary_node_ids = extract_selected_nodes(record)
    if not linked_node_ids:
        return None

    return {
        "question_id": question_id,
        "state": "new",
        "linked_node_ids": linked_node_ids,
        "primary_node_ids": primary_node_ids,
        "secondary_node_ids": secondary_node_ids,
        "question_payload": record.get("question_payload") or {},
        "source_batch_id": source_batch_id,
        "first_seen_at": created_at,
        "next_review_at": created_at,
        "last_result": "unseen",
        "review_count": 0,
        "priority_note": question_priority_note(record),
    }


def merge_question_state(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing["linked_node_ids"] = unique_list(
        normalize_str_list(existing.get("linked_node_ids"))
        + normalize_str_list(incoming.get("linked_node_ids"))
    )
    existing["primary_node_ids"] = unique_list(
        normalize_str_list(existing.get("primary_node_ids"))
        + normalize_str_list(incoming.get("primary_node_ids"))
    )
    existing["secondary_node_ids"] = unique_list(
        normalize_str_list(existing.get("secondary_node_ids"))
        + normalize_str_list(incoming.get("secondary_node_ids"))
    )
    existing.setdefault("state", incoming.get("state", "new"))
    existing.setdefault("last_result", incoming.get("last_result", "unseen"))
    existing.setdefault("review_count", incoming.get("review_count", 0))
    if incoming.get("question_payload"):
        existing["question_payload"] = incoming["question_payload"]
    existing["source_batch_id"] = incoming.get("source_batch_id") or existing.get("source_batch_id")
    if normalize_text(incoming.get("priority_note")):
        existing["priority_note"] = incoming["priority_note"]
    return existing


def build_node_state(
    *,
    node_id: str,
    question_ids: list[str],
    source_batch_ids: list[str],
    priority_note: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "state": "new",
        "mastery": 0.0,
        "stability": 0.0,
        "linked_question_ids": unique_list(question_ids),
        "source_batch_ids": unique_list(source_batch_ids),
        "first_seen_at": created_at,
        "next_review_at": created_at,
        "priority_note": priority_note,
    }


def merge_node_state(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    existing["linked_question_ids"] = unique_list(
        normalize_str_list(existing.get("linked_question_ids"))
        + normalize_str_list(incoming.get("linked_question_ids"))
    )
    existing["source_batch_ids"] = unique_list(
        normalize_str_list(existing.get("source_batch_ids"))
        + normalize_str_list(incoming.get("source_batch_ids"))
    )
    existing.setdefault("state", incoming.get("state", "new"))
    existing.setdefault("mastery", incoming.get("mastery", 0.0))
    existing.setdefault("stability", incoming.get("stability", 0.0))
    if normalize_text(incoming.get("priority_note")):
        existing["priority_note"] = incoming["priority_note"]
    return existing


def convert_annotations_to_review_state(
    records: list[dict[str, Any]],
    *,
    existing_review_state: dict[str, Any] | None = None,
    record_id: str,
    student_id: str,
    source_batch_id: str,
) -> dict[str, Any]:
    current_time = now_iso()
    review_state = existing_review_state or build_empty_review_state(
        record_id=record_id,
        student_id=student_id,
        generated_at=current_time,
    )

    review_state.setdefault("record_id", record_id)
    review_state.setdefault("student_id", student_id)
    review_state["generated_at"] = current_time
    review_state.setdefault("knowledge_point_states", [])
    review_state.setdefault("example_question_states", [])
    review_state["notes"] = normalize_notes_container(review_state.get("notes"))

    question_lookup = {
        state["question_id"]: state
        for state in review_state["example_question_states"]
        if isinstance(state, dict) and "question_id" in state
    }
    node_lookup = {
        state["node_id"]: state
        for state in review_state["knowledge_point_states"]
        if isinstance(state, dict) and "node_id" in state
    }

    skipped_records: list[dict[str, Any]] = []
    node_to_question_ids: dict[str, list[str]] = {}
    node_to_priority_note: dict[str, str] = {}

    for record in records:
        question_state = build_question_state(
            record,
            source_batch_id=source_batch_id,
            created_at=current_time,
        )
        annotation_id = normalize_text(record.get("annotation_id"))
        question_id = normalize_text(record.get("question_id"))

        if question_state is None:
            skipped_records.append(
                {
                    "annotation_id": annotation_id,
                    "question_id": question_id,
                    "reason": "missing_confirmed_node_selection",
                }
            )
            continue

        existing_question = question_lookup.get(question_state["question_id"])
        if existing_question is None:
            review_state["example_question_states"].append(question_state)
            question_lookup[question_state["question_id"]] = question_state
        else:
            merge_question_state(existing_question, question_state)

        for node_id in question_state["linked_node_ids"]:
            node_to_question_ids.setdefault(node_id, [])
            node_to_question_ids[node_id].append(question_state["question_id"])
            node_to_priority_note[node_id] = question_state["priority_note"]

    for node_id, linked_question_ids in node_to_question_ids.items():
        incoming = build_node_state(
            node_id=node_id,
            question_ids=linked_question_ids,
            source_batch_ids=[source_batch_id],
            priority_note=node_to_priority_note.get(node_id, DEFAULT_PRIORITY_NOTE),
            created_at=current_time,
        )
        existing_node = node_lookup.get(node_id)
        if existing_node is None:
            review_state["knowledge_point_states"].append(incoming)
            node_lookup[node_id] = incoming
        else:
            merge_node_state(existing_node, incoming)

    notes = normalize_notes_container(review_state.get("notes"))
    bridge_notes = {
        "bridge_source": "annotation_to_review_state",
        "source_batch_id": source_batch_id,
        "annotation_record_count": len(records),
        "imported_question_count": len(node_to_question_ids) and len(
            {
                question_id
                for question_ids in node_to_question_ids.values()
                for question_id in question_ids
            }
        ) or 0,
        "skipped_records": skipped_records,
    }
    notes["annotation_bridge"] = bridge_notes
    review_state["notes"] = notes
    return review_state


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--annotation-json",
        required=True,
        help="Path to student-confirmed wrong-question annotation JSON",
    )
    parser.add_argument(
        "--out-json",
        required=True,
        help="Output review_state JSON path",
    )
    parser.add_argument(
        "--existing-review-state",
        help="Optional existing review_state JSON to merge into",
    )
    parser.add_argument(
        "--record-id",
        default="review_state.from_student_annotations.v1",
    )
    parser.add_argument(
        "--student-id",
        default="demo_student",
    )
    parser.add_argument(
        "--source-batch-id",
        default=DEFAULT_SOURCE_BATCH_ID,
    )
    args = parser.parse_args()

    records = load_annotation_records(Path(args.annotation_json))
    existing_review_state = load_review_state(
        Path(args.existing_review_state) if args.existing_review_state else None
    )
    review_state = convert_annotations_to_review_state(
        records,
        existing_review_state=existing_review_state,
        record_id=args.record_id,
        student_id=args.student_id,
        source_batch_id=args.source_batch_id,
    )
    write_json(Path(args.out_json), review_state)


if __name__ == "__main__":
    main()

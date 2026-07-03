from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


ERROR_TYPES = (
    "concept_gap",
    "missing_strategy",
    "misreading",
    "calculation",
    "careless",
)
QUESTION_TARGET = "wrong_question"
NODE_TARGET = "knowledge_point"


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


def normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {
            "true",
            "1",
            "yes",
            "y",
            "是",
            "完成",
            "完成了",
            "懂了",
        }
    return bool(value)


def unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = normalize_text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def now_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.isoformat()


def normalize_error_type(value: Any) -> str:
    text = normalize_text(value) or "concept_gap"
    return text if text in ERROR_TYPES else "concept_gap"


def coerce_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def first_non_empty_text(*values: Any) -> str | None:
    for value in values:
        text = normalize_text(value)
        if text is not None:
            return text
    return None


def first_non_empty_list(*values: Any) -> list[str]:
    for value in values:
        items = normalize_str_list(value)
        if items:
            return items
    return []


def first_list_item_text(value: Any) -> str | None:
    items = normalize_str_list(value)
    return items[0] if items else None


def extract_node_binding_context(payload: dict[str, Any]) -> tuple[str | None, list[str]]:
    binding = coerce_dict(payload.get("binding"))
    annotation = coerce_dict(payload.get("annotation"))
    student_selection = coerce_dict(
        payload.get("student_selection") or annotation.get("student_selection")
    )
    review_linkage = coerce_dict(
        payload.get("review_linkage") or annotation.get("review_linkage")
    )

    primary_node_id = first_non_empty_text(
        payload.get("primary_node_id"),
        first_list_item_text(payload.get("primary_node_ids")),
        binding.get("primary_node_id"),
        first_list_item_text(binding.get("primary_node_ids")),
        first_list_item_text(student_selection.get("primary_node_ids")),
        first_list_item_text(student_selection.get("selected_node_ids")),
        first_list_item_text(review_linkage.get("review_node_ids")),
        first_list_item_text(payload.get("linked_node_ids")),
    )
    if primary_node_id is None:
        primary_candidates = unique_list(
            first_non_empty_list(
                payload.get("primary_node_ids"),
                binding.get("primary_node_ids"),
                student_selection.get("primary_node_ids"),
            )
        )
        if primary_candidates:
            primary_node_id = primary_candidates[0]

    linked_node_ids = unique_list(
        normalize_str_list(payload.get("linked_node_ids"))
        + normalize_str_list(payload.get("secondary_node_ids"))
        + normalize_str_list(payload.get("primary_node_ids"))
        + normalize_str_list(binding.get("linked_node_ids"))
        + normalize_str_list(binding.get("secondary_node_ids"))
        + normalize_str_list(binding.get("primary_node_ids"))
        + normalize_str_list(student_selection.get("selected_node_ids"))
        + normalize_str_list(student_selection.get("secondary_node_ids"))
        + normalize_str_list(student_selection.get("mistake_node_ids"))
        + normalize_str_list(review_linkage.get("review_node_ids"))
    )
    if primary_node_id is not None:
        linked_node_ids = unique_list([primary_node_id] + linked_node_ids)
    secondary_node_ids = [
        node_id for node_id in linked_node_ids if node_id != primary_node_id
    ]
    return primary_node_id, secondary_node_ids


def extract_question_context(
    payload: dict[str, Any],
) -> tuple[str | None, str | None, str | None]:
    binding = coerce_dict(payload.get("binding"))
    annotation = coerce_dict(payload.get("annotation"))
    question_payload = coerce_dict(
        payload.get("question_payload") or annotation.get("question_payload")
    )
    source = coerce_dict(payload.get("source"))
    question_id = first_non_empty_text(
        payload.get("question_id"),
        binding.get("question_id"),
        annotation.get("question_id"),
        payload.get("target_id"),
    )
    source_name = first_non_empty_text(
        payload.get("source_name"),
        question_payload.get("source_name"),
        source.get("source_name"),
    )
    source_section = first_non_empty_text(
        payload.get("source_section"),
        question_payload.get("source_section"),
        source.get("source_section"),
    )
    return question_id, source_name, source_section


def extract_question_type(payload: dict[str, Any]) -> str | None:
    annotation = coerce_dict(payload.get("annotation"))
    question_payload = coerce_dict(
        payload.get("question_payload") or annotation.get("question_payload")
    )
    source = coerce_dict(payload.get("source"))
    return first_non_empty_text(
        payload.get("question_type"),
        question_payload.get("question_type"),
        source.get("question_type"),
    )


def build_event_entry(
    *,
    event_type: str,
    occurred_at: str,
    details: dict[str, Any],
) -> dict[str, Any]:
    payload = {
        "event_type": event_type,
        "occurred_at": occurred_at,
    }
    payload.update(details)
    return payload


def normalize_diagnosis_event_payload(
    diagnosis_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    raw_diagnosis = coerce_dict(diagnosis_event.get("diagnosis"))
    diagnosis_payload = raw_diagnosis or diagnosis_event
    question_id, source_name, source_section = extract_question_context(diagnosis_event)
    question_type = extract_question_type(diagnosis_event)
    primary_node_id, secondary_node_ids = extract_node_binding_context(diagnosis_event)
    occurred_at = first_non_empty_text(
        diagnosis_event.get("occurred_at"),
        diagnosis_payload.get("occurred_at"),
        now_iso(now),
    )
    return {
        "event_type": "diagnosis",
        "event_id": normalize_text(diagnosis_event.get("event_id")),
        "student_id": first_non_empty_text(
            diagnosis_event.get("student_id"),
            diagnosis_payload.get("student_id"),
        ),
        "session_id": first_non_empty_text(
            diagnosis_event.get("session_id"),
            diagnosis_payload.get("session_id"),
        ),
        "occurred_at": occurred_at,
        "question_id": question_id or "unknown_question",
        "question_type": question_type,
        "error_type": normalize_error_type(diagnosis_payload.get("error_type")),
        "primary_node_id": primary_node_id,
        "secondary_node_ids": secondary_node_ids,
        "reason": first_non_empty_text(
            diagnosis_event.get("reason"),
            diagnosis_payload.get("reason"),
        ),
        "evidence": first_non_empty_text(
            diagnosis_event.get("evidence"),
            diagnosis_payload.get("evidence"),
        ),
        "confidence": diagnosis_payload.get("confidence"),
        "source_name": source_name,
        "source_section": source_section,
        "coach_mode": first_non_empty_text(
            diagnosis_event.get("coach_mode"),
            diagnosis_payload.get("coach_mode"),
        ),
        "coach_trap": first_non_empty_text(
            diagnosis_event.get("coach_trap"),
            diagnosis_payload.get("coach_trap"),
        ),
        "coach_prompt": first_non_empty_text(
            diagnosis_event.get("coach_prompt"),
            diagnosis_payload.get("coach_prompt"),
        ),
        "diagnosis_source": first_non_empty_text(
            diagnosis_event.get("source"),
            diagnosis_payload.get("source"),
        ),
        "metadata": coerce_dict(diagnosis_event.get("metadata")) or None,
    }


def diagnosis_result_to_memory_event(
    diagnosis_payload: dict[str, Any],
    *,
    question_id: str,
    question_type: str | None = None,
    binding: dict[str, Any] | None = None,
    annotation: dict[str, Any] | None = None,
    occurred_at: str | None = None,
    source_name: str | None = None,
    source_section: str | None = None,
    student_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question_id": question_id,
        "diagnosis": diagnosis_payload,
    }
    if question_type is not None:
        payload["question_type"] = question_type
    if binding is not None:
        payload["binding"] = binding
    if annotation is not None:
        payload["annotation"] = annotation
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at
    if source_name is not None:
        payload["source_name"] = source_name
    if source_section is not None:
        payload["source_section"] = source_section
    if student_id is not None:
        payload["student_id"] = student_id
    if session_id is not None:
        payload["session_id"] = session_id
    return normalize_diagnosis_event_payload(payload)


def normalize_coach_event_payload(
    coach_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    raw_response = coerce_dict(coach_event.get("coach_response"))
    coach_payload = raw_response or coach_event
    strategy = coerce_dict(coach_payload.get("strategy"))
    reply_analysis = coerce_dict(coach_payload.get("reply_analysis"))
    question_id, source_name, source_section = extract_question_context(coach_event)
    question_type = extract_question_type(coach_event)
    primary_node_id, secondary_node_ids = extract_node_binding_context(coach_event)
    occurred_at = first_non_empty_text(
        coach_event.get("occurred_at"),
        coach_payload.get("occurred_at"),
        now_iso(now),
    )
    turn_index_text = first_non_empty_text(
        coach_event.get("turn_index"),
        coach_payload.get("turn_index"),
    )
    try:
        turn_index = int(turn_index_text) if turn_index_text is not None else 1
    except ValueError:
        turn_index = 1

    return {
        "event_type": "coach",
        "event_id": normalize_text(coach_event.get("event_id")),
        "student_id": first_non_empty_text(
            coach_event.get("student_id"),
            coach_payload.get("student_id"),
        ),
        "session_id": first_non_empty_text(
            coach_event.get("session_id"),
            coach_payload.get("session_id"),
        ),
        "occurred_at": occurred_at,
        "question_id": question_id or "unknown_question",
        "question_type": question_type,
        "primary_node_id": primary_node_id,
        "secondary_node_ids": secondary_node_ids,
        "error_type": normalize_error_type(
            first_non_empty_text(
                coach_event.get("error_type"),
                coach_event.get("diagnosis_error_type"),
                coach_event.get("last_error_type"),
            )
        ),
        "coach_mode": first_non_empty_text(
            coach_event.get("coach_mode"),
            strategy.get("mode"),
            coach_payload.get("strategy_mode"),
        ),
        "coach_trap": first_non_empty_text(
            coach_event.get("coach_trap"),
            strategy.get("trap"),
            coach_payload.get("strategy_trap"),
        ),
        "coach_prompt": first_non_empty_text(
            coach_event.get("coach_prompt"),
            strategy.get("prompt"),
            coach_payload.get("strategy_prompt"),
        ),
        "reply_quality": first_non_empty_text(
            coach_event.get("reply_quality"),
            reply_analysis.get("quality"),
            coach_payload.get("reply_quality"),
        ),
        "understands": normalize_bool(
            reply_analysis.get("understands", coach_event.get("understands"))
        ),
        "completed": normalize_bool(
            reply_analysis.get("completed", coach_event.get("completed"))
        ),
        "reason": first_non_empty_text(
            coach_event.get("reason"),
            reply_analysis.get("reason"),
        ),
        "turn_index": max(turn_index, 1),
        "done": normalize_bool(coach_payload.get("done", coach_event.get("done"))),
        "stop_reason": first_non_empty_text(
            coach_event.get("stop_reason"),
            coach_payload.get("stop_reason"),
        ),
        "source_name": source_name,
        "source_section": source_section,
        "metadata": coerce_dict(coach_event.get("metadata")) or None,
    }


def coach_response_to_memory_event(
    coach_payload: dict[str, Any],
    *,
    question_id: str,
    question_type: str | None = None,
    binding: dict[str, Any] | None = None,
    annotation: dict[str, Any] | None = None,
    occurred_at: str | None = None,
    error_type: str | None = None,
    source_name: str | None = None,
    source_section: str | None = None,
    student_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question_id": question_id,
        "coach_response": coach_payload,
    }
    if question_type is not None:
        payload["question_type"] = question_type
    if binding is not None:
        payload["binding"] = binding
    if annotation is not None:
        payload["annotation"] = annotation
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at
    if error_type is not None:
        payload["error_type"] = error_type
    if source_name is not None:
        payload["source_name"] = source_name
    if source_section is not None:
        payload["source_section"] = source_section
    if student_id is not None:
        payload["student_id"] = student_id
    if session_id is not None:
        payload["session_id"] = session_id
    return normalize_coach_event_payload(payload)


def normalize_review_event_payload(
    review_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    occurred_at = first_non_empty_text(
        review_event.get("occurred_at"),
        review_event.get("executed_at"),
        now_iso(now),
    )
    action = normalize_text(review_event.get("action")) or "unknown"
    target_type = normalize_text(review_event.get("target_type")) or ""
    target_id = normalize_text(review_event.get("target_id")) or "unknown"
    result = normalize_text(review_event.get("result"))
    updated_payload = (
        review_event.get("updated_payload")
        if isinstance(review_event.get("updated_payload"), dict)
        else None
    )

    question_id: str | None = None
    primary_node_id: str | None = None
    secondary_node_ids: list[str] = []
    linked_node_ids: list[str] = []
    linked_question_ids: list[str] = []

    if target_type == QUESTION_TARGET:
        question_id = target_id
        if updated_payload:
            for state in updated_payload.get("example_question_states", []):
                if normalize_text(state.get("question_id")) != target_id:
                    continue
                primary_node_id = first_list_item_text(state.get("primary_node_ids")) or first_list_item_text(
                    state.get("linked_node_ids")
                )
                linked_node_ids = unique_list(normalize_str_list(state.get("linked_node_ids")))
                secondary_node_ids = [
                    node_id for node_id in linked_node_ids if node_id != primary_node_id
                ]
                break
    elif target_type == NODE_TARGET:
        primary_node_id = target_id
        if updated_payload:
            for state in updated_payload.get("knowledge_point_states", []):
                if normalize_text(state.get("node_id")) != target_id:
                    continue
                linked_question_ids = unique_list(
                    normalize_str_list(state.get("linked_question_ids"))
                )
                break

    return {
        "event_type": "review",
        "event_id": normalize_text(review_event.get("event_id")),
        "student_id": normalize_text(review_event.get("student_id")),
        "session_id": normalize_text(review_event.get("session_id")),
        "occurred_at": occurred_at,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "question_id": question_id,
        "primary_node_id": primary_node_id,
        "secondary_node_ids": secondary_node_ids,
        "linked_node_ids": linked_node_ids,
        "linked_question_ids": linked_question_ids,
        "result": result,
        "updated_payload": updated_payload,
        "source_name": normalize_text(review_event.get("source_name")),
        "source_section": normalize_text(review_event.get("source_section")),
        "metadata": coerce_dict(review_event.get("metadata")) or None,
    }


def review_state_update_to_memory_event(
    review_event: dict[str, Any],
    *,
    student_id: str | None = None,
    session_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = dict(review_event)
    if student_id is not None:
        payload["student_id"] = student_id
    if session_id is not None:
        payload["session_id"] = session_id
    return normalize_review_event_payload(payload, now=now)


def normalize_binding_event_payload(
    binding_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    binding = coerce_dict(binding_event.get("binding"))
    annotation = coerce_dict(binding_event.get("annotation"))
    student_selection = coerce_dict(
        binding_event.get("student_selection") or annotation.get("student_selection")
    )
    question_id, source_name, source_section = extract_question_context(binding_event)
    question_type = extract_question_type(binding_event)
    primary_node_id, secondary_node_ids = extract_node_binding_context(binding_event)
    occurred_at = first_non_empty_text(
        binding_event.get("occurred_at"),
        now_iso(now),
    )
    candidate_node_ids = unique_list(
        normalize_str_list(binding_event.get("candidate_node_ids"))
        + normalize_str_list(binding_event.get("top_k_node_ids"))
        + normalize_str_list(binding.get("candidate_node_ids"))
        + normalize_str_list(binding.get("top_k_node_ids"))
    )
    binding_source = first_non_empty_text(
        binding_event.get("binding_source"),
        annotation.get("binding_source"),
    )
    if binding_source is None:
        binding_source = (
            "student_confirmed" if student_selection or annotation else "system_recommendation"
        )

    return {
        "event_type": "binding",
        "event_id": normalize_text(binding_event.get("event_id")),
        "student_id": normalize_text(binding_event.get("student_id")),
        "session_id": normalize_text(binding_event.get("session_id")),
        "occurred_at": occurred_at,
        "question_id": question_id or "unknown_question",
        "question_type": question_type,
        "primary_node_id": primary_node_id,
        "secondary_node_ids": secondary_node_ids,
        "candidate_node_ids": candidate_node_ids,
        "binding_source": binding_source,
        "binding_confidence": first_non_empty_text(
            binding_event.get("binding_confidence"),
            binding.get("binding_confidence"),
        ),
        "annotation_mode": first_non_empty_text(
            binding_event.get("annotation_mode"),
            "tree_selection" if student_selection else None,
        ),
        "source_name": source_name,
        "source_section": source_section,
        "metadata": coerce_dict(binding_event.get("metadata")) or None,
    }


def binding_result_to_memory_event(
    *,
    question_id: str,
    question_type: str | None = None,
    primary_node_id: str | None = None,
    secondary_node_ids: list[str] | None = None,
    candidate_node_ids: list[str] | None = None,
    binding_source: str = "system_recommendation",
    occurred_at: str | None = None,
    source_name: str | None = None,
    source_section: str | None = None,
    student_id: str | None = None,
    session_id: str | None = None,
    binding_confidence: float | str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question_id": question_id,
        "primary_node_id": primary_node_id,
        "secondary_node_ids": secondary_node_ids or [],
        "candidate_node_ids": candidate_node_ids or [],
        "binding_source": binding_source,
    }
    if question_type is not None:
        payload["question_type"] = question_type
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at
    if source_name is not None:
        payload["source_name"] = source_name
    if source_section is not None:
        payload["source_section"] = source_section
    if student_id is not None:
        payload["student_id"] = student_id
    if session_id is not None:
        payload["session_id"] = session_id
    if binding_confidence is not None:
        payload["binding_confidence"] = binding_confidence
    return normalize_binding_event_payload(payload)


def normalize_student_choice_event_payload(
    student_choice_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    annotation = coerce_dict(student_choice_event.get("annotation"))
    student_selection = coerce_dict(
        student_choice_event.get("student_selection") or annotation.get("student_selection")
    )
    question_id, source_name, source_section = extract_question_context(student_choice_event)
    question_type = extract_question_type(student_choice_event)
    primary_node_id, secondary_node_ids = extract_node_binding_context(student_choice_event)
    occurred_at = first_non_empty_text(
        student_choice_event.get("occurred_at"),
        now_iso(now),
    )
    selected_node_ids = unique_list(
        normalize_str_list(student_choice_event.get("selected_node_ids"))
        + normalize_str_list(student_selection.get("selected_node_ids"))
    )

    return {
        "event_type": "student_choice",
        "event_id": normalize_text(student_choice_event.get("event_id")),
        "student_id": normalize_text(student_choice_event.get("student_id")),
        "session_id": normalize_text(student_choice_event.get("session_id")),
        "occurred_at": occurred_at,
        "action_type": first_non_empty_text(
            student_choice_event.get("action_type"),
            student_selection.get("action_type"),
            "select_node",
        ),
        "question_id": question_id,
        "question_type": question_type,
        "target_type": first_non_empty_text(
            student_choice_event.get("target_type"),
            "question" if question_id else "knowledge_point",
        ),
        "target_id": first_non_empty_text(
            student_choice_event.get("target_id"),
            question_id,
            primary_node_id,
        ),
        "selected_node_ids": selected_node_ids,
        "primary_node_id": primary_node_id,
        "secondary_node_ids": secondary_node_ids,
        "note": first_non_empty_text(
            student_choice_event.get("note"),
            student_selection.get("note"),
        ),
        "source_name": source_name,
        "source_section": source_section,
        "metadata": coerce_dict(student_choice_event.get("metadata")) or None,
    }


def student_choice_to_memory_event(
    *,
    action_type: str,
    target_type: str,
    target_id: str,
    occurred_at: str | None = None,
    question_id: str | None = None,
    question_type: str | None = None,
    selected_node_ids: list[str] | None = None,
    note: str | None = None,
    source_name: str | None = None,
    source_section: str | None = None,
    student_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action_type": action_type,
        "target_type": target_type,
        "target_id": target_id,
        "selected_node_ids": selected_node_ids or [],
    }
    if occurred_at is not None:
        payload["occurred_at"] = occurred_at
    if question_id is not None:
        payload["question_id"] = question_id
    if question_type is not None:
        payload["question_type"] = question_type
    if note is not None:
        payload["note"] = note
    if source_name is not None:
        payload["source_name"] = source_name
    if source_section is not None:
        payload["source_section"] = source_section
    if student_id is not None:
        payload["student_id"] = student_id
    if session_id is not None:
        payload["session_id"] = session_id
    return normalize_student_choice_event_payload(payload)


__all__ = [
    "QUESTION_TARGET",
    "NODE_TARGET",
    "build_event_entry",
    "normalize_diagnosis_event_payload",
    "diagnosis_result_to_memory_event",
    "normalize_coach_event_payload",
    "coach_response_to_memory_event",
    "normalize_review_event_payload",
    "review_state_update_to_memory_event",
    "normalize_binding_event_payload",
    "binding_result_to_memory_event",
    "normalize_student_choice_event_payload",
    "student_choice_to_memory_event",
]

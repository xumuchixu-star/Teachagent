from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from student_memory_events import (
    QUESTION_TARGET,
    NODE_TARGET,
    build_event_entry,
    review_state_update_to_memory_event,
    coach_response_to_memory_event,
    diagnosis_result_to_memory_event,
    normalize_binding_event_payload,
    normalize_coach_event_payload,
    normalize_diagnosis_event_payload,
    normalize_review_event_payload,
    normalize_student_choice_event_payload,
)


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
DEFAULT_OUT_PATH = ROOT / "scratch" / "student_memory_profile_demo.json"
PROFILE_VERSION = "student_memory_profile_v1"
ERROR_TYPES = (
    "concept_gap",
    "missing_strategy",
    "misreading",
    "calculation",
    "careless",
)
TENTATIVE_SIGNAL = "tentative"
ESTABLISHED_SIGNAL = "established"
EARLY_OBSERVATION_STAGE = "early_observation"
FORMING_PATTERN_STAGE = "forming_pattern"
ESTABLISHED_ERROR_EVENT_THRESHOLD = 3
ESTABLISHED_NODE_OBSERVATION_THRESHOLD = 2
ESTABLISHED_PROFILE_QUESTION_THRESHOLD = 3
ESTABLISHED_PROFILE_DIAGNOSIS_THRESHOLD = 3
ESTABLISHED_PROFILE_REVIEW_THRESHOLD = 4

TEACHING_DIMENSIONS = (
    "concept_explain_bias",
    "strategy_scaffold_bias",
    "step_by_step_bias",
    "condition_reading_bias",
    "self_check_bias",
    "direct_explain_bias",
)
PRACTICE_DIMENSIONS = (
    "leaf_first_bias",
    "question_first_bias",
    "concept_card_bias",
    "method_card_bias",
    "representative_question_bias",
    "retry_recent_wrong_bias",
)

ERROR_TO_TEACHING = {
    "concept_gap": {
        "concept_explain_bias": 1.0,
        "step_by_step_bias": 0.45,
        "direct_explain_bias": 0.8,
    },
    "missing_strategy": {
        "strategy_scaffold_bias": 1.0,
        "step_by_step_bias": 0.85,
        "direct_explain_bias": 0.35,
    },
    "misreading": {
        "condition_reading_bias": 1.0,
        "step_by_step_bias": 0.35,
        "self_check_bias": 0.25,
    },
    "calculation": {
        "step_by_step_bias": 0.35,
        "self_check_bias": 0.7,
    },
    "careless": {
        "self_check_bias": 1.0,
        "condition_reading_bias": 0.2,
    },
}

ERROR_TO_PRACTICE = {
    "concept_gap": {
        "leaf_first_bias": 1.0,
        "concept_card_bias": 1.0,
        "representative_question_bias": 0.45,
    },
    "missing_strategy": {
        "leaf_first_bias": 0.55,
        "method_card_bias": 1.0,
        "representative_question_bias": 0.85,
    },
    "misreading": {
        "question_first_bias": 0.7,
        "retry_recent_wrong_bias": 0.55,
        "representative_question_bias": 0.6,
    },
    "calculation": {
        "question_first_bias": 0.95,
        "retry_recent_wrong_bias": 1.0,
        "representative_question_bias": 0.5,
    },
    "careless": {
        "question_first_bias": 0.55,
        "retry_recent_wrong_bias": 0.8,
        "representative_question_bias": 0.4,
    },
}

INTERVENTION_TEXT = {
    "reteach_concept": "这个知识点需要先重新讲清概念或定义，再上题。",
    "show_strategy_first": "这个知识点更像是不会想思路，讲题时先讲中间目标和解题路线。",
    "drill_with_checklist": "这个知识点更适合多给几道代表题，并要求学生做过程检查。",
    "read_conditions_first": "这个知识点要先训练学生读条件、找限制，再开始动手算。",
    "stabilize_with_examples": "这个知识点已经接触过，但还不稳，适合叶子卡加代表题混合复习。",
}


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            text = normalize_text(item)
            if text:
                items.append(text)
        return items
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


def safe_round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def parse_datetime(value: Any) -> datetime | None:
    text = normalize_text(value)
    if text is None:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def now_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.isoformat()


def empty_error_counts() -> dict[str, int]:
    return {key: 0 for key in ERROR_TYPES}


def empty_dimension_scores(dimensions: tuple[str, ...]) -> dict[str, float]:
    return {key: 0.0 for key in dimensions}


def normalize_error_type(value: Any) -> str:
    text = normalize_text(value) or "concept_gap"
    return text if text in ERROR_TYPES else "concept_gap"


def sort_counter_items(counter: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(counter.items(), key=lambda item: (-int(item[1]), item[0]))


def dominant_error_type(counter: dict[str, int]) -> str | None:
    ranked = [item for item in sort_counter_items(counter) if item[1] > 0]
    if not ranked:
        return None
    return ranked[0][0]


def total_error_count(counter: dict[str, int]) -> int:
    return sum(int(value or 0) for value in counter.values())


def signal_strength(count: int, established_threshold: int) -> str | None:
    normalized_count = int(count or 0)
    if normalized_count <= 0:
        return None
    if normalized_count >= established_threshold:
        return ESTABLISHED_SIGNAL
    return TENTATIVE_SIGNAL


def total_wrong_pressure(node_memory: dict[str, Any]) -> int:
    return int(node_memory.get("observed_wrong_count", 0) or 0) + int(
        node_memory.get("review_wrong_count", 0) or 0
    )


def count_events(profile: dict[str, Any], event_type: str) -> int:
    return sum(
        1
        for event in profile.get("event_history", [])
        if normalize_text(event.get("event_type")) == event_type
    )


def profile_signal_snapshot(profile: dict[str, Any]) -> dict[str, Any]:
    diagnosis_event_count = count_events(profile, "diagnosis")
    coach_event_count = count_events(profile, "coach")
    review_event_count = count_events(profile, "review")
    distinct_question_count = sum(
        1
        for memory in profile.get("question_memories", [])
        if (
            int(memory.get("diagnosis_count", 0) or 0) > 0
            or int(memory.get("review_count", 0) or 0) > 0
            or int(memory.get("wrong_count", 0) or 0) > 0
        )
    )
    stage = EARLY_OBSERVATION_STAGE
    if (
        diagnosis_event_count >= ESTABLISHED_PROFILE_DIAGNOSIS_THRESHOLD
        or distinct_question_count >= ESTABLISHED_PROFILE_QUESTION_THRESHOLD
        or review_event_count >= ESTABLISHED_PROFILE_REVIEW_THRESHOLD
    ):
        stage = FORMING_PATTERN_STAGE
    return {
        "memory_stage": stage,
        "diagnosis_event_count": diagnosis_event_count,
        "coach_event_count": coach_event_count,
        "review_event_count": review_event_count,
        "distinct_question_count": distinct_question_count,
        "is_light_observation": stage == EARLY_OBSERVATION_STAGE,
    }


def leaf_title_from_node_id(node_id: str) -> str:
    text = normalize_text(node_id) or ""
    return text.split(".")[-1] if text else ""


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


def default_node_memory(node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "linked_question_ids": [],
        "error_type_counts": empty_error_counts(),
        "diagnosis_count": 0,
        "observed_wrong_count": 0,
        "review_wrong_count": 0,
        "review_correct_count": 0,
        "review_partial_count": 0,
        "practice_request_count": 0,
        "consecutive_wrong_count": 0,
        "mastery_hint": 0.0,
        "stability_hint": 0.0,
        "last_seen_at": None,
        "last_wrong_at": None,
        "last_event_at": None,
        "dominant_error_type": None,
        "recommended_intervention": None,
        "signal_strength": None,
        "observation_stage": EARLY_OBSERVATION_STAGE,
    }


def default_question_memory(question_id: str) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question_type": None,
        "linked_node_ids": [],
        "error_type_counts": empty_error_counts(),
        "diagnosis_count": 0,
        "review_count": 0,
        "wrong_count": 0,
        "correct_count": 0,
        "partial_count": 0,
        "last_result": "unseen",
        "last_error_type": None,
        "source_name": None,
        "source_section": None,
        "last_seen_at": None,
        "last_wrong_at": None,
        "last_event_at": None,
        "signal_strength": None,
        "observation_stage": EARLY_OBSERVATION_STAGE,
    }


def initialize_student_memory_profile(
    student_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now_iso(now)
    return {
        "record_id": f"student_memory.{student_id}",
        "student_id": student_id,
        "profile_version": PROFILE_VERSION,
        "generated_at": current,
        "updated_at": current,
        "error_type_counts": empty_error_counts(),
        "node_memories": [],
        "question_memories": [],
        "event_history": [],
        "teaching_preferences": {},
        "practice_preferences": {},
        "personalization_summary": {},
        "memory_graph": {"nodes": [], "edges": []},
        "agent_memory_text": "",
        "notes": {},
    }


def ensure_profile_shape(profile: dict[str, Any]) -> dict[str, Any]:
    student_id = normalize_text(profile.get("student_id")) or "unknown_student"
    profile.setdefault("record_id", f"student_memory.{student_id}")
    profile.setdefault("student_id", student_id)
    profile.setdefault("profile_version", PROFILE_VERSION)
    profile.setdefault("generated_at", now_iso())
    profile.setdefault("updated_at", profile["generated_at"])
    profile.setdefault("error_type_counts", empty_error_counts())
    profile.setdefault("node_memories", [])
    profile.setdefault("question_memories", [])
    profile.setdefault("event_history", [])
    profile.setdefault("teaching_preferences", {})
    profile.setdefault("practice_preferences", {})
    profile.setdefault("personalization_summary", {})
    profile.setdefault("memory_graph", {"nodes": [], "edges": []})
    profile.setdefault("agent_memory_text", "")
    profile.setdefault("notes", {})
    for key in ERROR_TYPES:
        profile["error_type_counts"].setdefault(key, 0)
    return profile


def build_node_lookup(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        entry["node_id"]: entry
        for entry in profile.get("node_memories", [])
        if isinstance(entry, dict) and "node_id" in entry
    }


def build_question_lookup(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        entry["question_id"]: entry
        for entry in profile.get("question_memories", [])
        if isinstance(entry, dict) and "question_id" in entry
    }


def get_or_create_node_memory(profile: dict[str, Any], node_id: str) -> dict[str, Any]:
    lookup = build_node_lookup(profile)
    node_memory = lookup.get(node_id)
    if node_memory is not None:
        return node_memory
    node_memory = default_node_memory(node_id)
    profile["node_memories"].append(node_memory)
    return node_memory


def get_or_create_question_memory(profile: dict[str, Any], question_id: str) -> dict[str, Any]:
    lookup = build_question_lookup(profile)
    question_memory = lookup.get(question_id)
    if question_memory is not None:
        return question_memory
    question_memory = default_question_memory(question_id)
    question_memory["error_type_counts"] = empty_error_counts()
    profile["question_memories"].append(question_memory)
    return question_memory


def update_node_derived_fields(node_memory: dict[str, Any]) -> None:
    dominant = dominant_error_type(node_memory.get("error_type_counts", {}))
    node_memory["dominant_error_type"] = dominant
    mastery_hint = clamp(float(node_memory.get("mastery_hint", 0.0) or 0.0), 0.0, 1.0)
    observed_wrong = int(node_memory.get("observed_wrong_count", 0) or 0)
    review_wrong = int(node_memory.get("review_wrong_count", 0) or 0)
    consecutive_wrong = int(node_memory.get("consecutive_wrong_count", 0) or 0)
    wrong_pressure = observed_wrong + review_wrong
    node_memory["signal_strength"] = signal_strength(
        wrong_pressure,
        ESTABLISHED_NODE_OBSERVATION_THRESHOLD,
    )
    node_memory["observation_stage"] = (
        FORMING_PATTERN_STAGE
        if node_memory["signal_strength"] == ESTABLISHED_SIGNAL
        else EARLY_OBSERVATION_STAGE
    )

    if dominant == "concept_gap" and (wrong_pressure >= 2 or mastery_hint < 0.4):
        node_memory["recommended_intervention"] = "reteach_concept"
    elif dominant == "missing_strategy" and (wrong_pressure >= 2 or consecutive_wrong >= 2):
        node_memory["recommended_intervention"] = "show_strategy_first"
    elif dominant in {"calculation", "careless"} and review_wrong >= 2:
        node_memory["recommended_intervention"] = "drill_with_checklist"
    elif dominant == "misreading":
        node_memory["recommended_intervention"] = "read_conditions_first"
    elif wrong_pressure >= 2:
        node_memory["recommended_intervention"] = "stabilize_with_examples"
    else:
        node_memory["recommended_intervention"] = None


def update_question_derived_fields(question_memory: dict[str, Any]) -> None:
    evidence_count = max(
        int(question_memory.get("diagnosis_count", 0) or 0),
        int(question_memory.get("review_count", 0) or 0),
        int(question_memory.get("wrong_count", 0) or 0),
    )
    question_memory["signal_strength"] = signal_strength(
        evidence_count,
        ESTABLISHED_NODE_OBSERVATION_THRESHOLD,
    )
    question_memory["observation_stage"] = (
        FORMING_PATTERN_STAGE
        if question_memory["signal_strength"] == ESTABLISHED_SIGNAL
        else EARLY_OBSERVATION_STAGE
    )


def append_capped_event(profile: dict[str, Any], event: dict[str, Any], *, limit: int = 200) -> None:
    history = profile.setdefault("event_history", [])
    history.append(event)
    if len(history) > limit:
        del history[:-limit]


def sync_from_review_state(
    profile: dict[str, Any],
    review_state: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = ensure_profile_shape(profile)
    current = now_iso(now)

    for question_state in review_state.get("example_question_states", []):
        question_id = normalize_text(question_state.get("question_id"))
        if question_id is None:
            continue
        question_memory = get_or_create_question_memory(profile, question_id)
        question_memory["question_type"] = (
            normalize_text(question_state.get("question_type"))
            or question_memory.get("question_type")
        )
        question_memory["linked_node_ids"] = unique_list(
            normalize_str_list(question_state.get("linked_node_ids"))
        )
        question_memory["source_name"] = normalize_text(question_state.get("source_batch_id"))
        question_memory["last_result"] = normalize_text(question_state.get("last_result")) or "unseen"
        question_memory["review_count"] = int(question_state.get("review_count", 0) or 0)
        question_memory["last_seen_at"] = normalize_text(
            question_state.get("last_reviewed_at") or question_state.get("first_seen_at")
        )
        question_memory["last_event_at"] = normalize_text(question_state.get("last_reviewed_at"))
        if question_memory["last_result"] == "wrong":
            question_memory["last_wrong_at"] = question_memory["last_event_at"]
        update_question_derived_fields(question_memory)

    for node_state in review_state.get("knowledge_point_states", []):
        node_id = normalize_text(node_state.get("node_id"))
        if node_id is None:
            continue
        node_memory = get_or_create_node_memory(profile, node_id)
        node_memory["linked_question_ids"] = unique_list(
            normalize_str_list(node_state.get("linked_question_ids"))
        )
        node_memory["mastery_hint"] = safe_round(
            clamp(float(node_state.get("mastery", 0.0) or 0.0), 0.0, 1.0)
        )
        node_memory["stability_hint"] = safe_round(
            max(float(node_state.get("stability", 0.0) or 0.0), 0.0)
        )
        node_memory["review_correct_count"] = int(node_state.get("correct_count", 0) or 0)
        node_memory["review_wrong_count"] = int(node_state.get("wrong_count", 0) or 0)
        node_memory["last_seen_at"] = normalize_text(
            node_state.get("last_reviewed_at") or node_state.get("first_seen_at")
        )
        node_memory["last_event_at"] = normalize_text(node_state.get("last_reviewed_at"))
        if int(node_state.get("wrong_count", 0) or 0) > 0:
            node_memory["last_wrong_at"] = normalize_text(node_state.get("last_reviewed_at"))
        update_node_derived_fields(node_memory)

    profile["updated_at"] = current
    refresh_personalization(profile)
    return profile


def apply_diagnosis_event(
    profile: dict[str, Any],
    diagnosis_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = ensure_profile_shape(profile)
    normalized_event = normalize_diagnosis_event_payload(diagnosis_event, now=now)
    occurred_at = normalize_text(normalized_event.get("occurred_at")) or now_iso(now)
    error_type = normalize_error_type(normalized_event.get("error_type"))
    question_id = normalize_text(normalized_event.get("question_id")) or "unknown_question"
    question_type = normalize_text(normalized_event.get("question_type"))
    primary_node_id = normalize_text(normalized_event.get("primary_node_id"))
    secondary_node_ids = normalize_str_list(normalized_event.get("secondary_node_ids"))
    linked_node_ids = unique_list(
        [node_id for node_id in [primary_node_id, *secondary_node_ids] if node_id]
    )

    profile["error_type_counts"][error_type] = int(profile["error_type_counts"].get(error_type, 0) or 0) + 1

    question_memory = get_or_create_question_memory(profile, question_id)
    question_memory.setdefault("error_type_counts", empty_error_counts())
    question_memory["question_type"] = question_type or question_memory.get("question_type")
    question_memory["diagnosis_count"] = int(question_memory.get("diagnosis_count", 0) or 0) + 1
    question_memory["wrong_count"] = int(question_memory.get("wrong_count", 0) or 0) + 1
    question_memory["last_result"] = "wrong"
    question_memory["last_error_type"] = error_type
    question_memory["source_name"] = normalize_text(normalized_event.get("source_name")) or question_memory.get("source_name")
    question_memory["source_section"] = normalize_text(normalized_event.get("source_section")) or question_memory.get("source_section")
    question_memory["linked_node_ids"] = unique_list(question_memory.get("linked_node_ids", []) + linked_node_ids)
    question_memory["last_seen_at"] = occurred_at
    question_memory["last_wrong_at"] = occurred_at
    question_memory["last_event_at"] = occurred_at
    question_memory["error_type_counts"][error_type] = int(question_memory["error_type_counts"].get(error_type, 0) or 0) + 1
    update_question_derived_fields(question_memory)

    for node_id in linked_node_ids:
        node_memory = get_or_create_node_memory(profile, node_id)
        node_memory["linked_question_ids"] = unique_list(
            node_memory.get("linked_question_ids", []) + [question_id]
        )
        node_memory["diagnosis_count"] = int(node_memory.get("diagnosis_count", 0) or 0) + 1
        node_memory["observed_wrong_count"] = int(node_memory.get("observed_wrong_count", 0) or 0) + 1
        node_memory["consecutive_wrong_count"] = int(node_memory.get("consecutive_wrong_count", 0) or 0) + 1
        node_memory["last_seen_at"] = occurred_at
        node_memory["last_wrong_at"] = occurred_at
        node_memory["last_event_at"] = occurred_at
        node_memory["error_type_counts"][error_type] = int(node_memory["error_type_counts"].get(error_type, 0) or 0) + 1
        update_node_derived_fields(node_memory)

    append_capped_event(
        profile,
        build_event_entry(
            event_type="diagnosis",
            occurred_at=occurred_at,
            details={
                "question_id": question_id,
                "question_type": question_type,
                "error_type": error_type,
                "primary_node_id": primary_node_id,
                "secondary_node_ids": secondary_node_ids,
                "reason": normalize_text(normalized_event.get("reason")),
                "evidence": normalize_text(normalized_event.get("evidence")),
                "confidence": normalized_event.get("confidence"),
                "coach_mode": normalize_text(normalized_event.get("coach_mode")),
                "coach_trap": normalize_text(normalized_event.get("coach_trap")),
                "coach_prompt": normalize_text(normalized_event.get("coach_prompt")),
                "diagnosis_source": normalize_text(normalized_event.get("diagnosis_source")),
            },
        ),
    )
    profile["updated_at"] = occurred_at
    refresh_personalization(profile)
    return profile


def apply_coach_event(
    profile: dict[str, Any],
    coach_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = ensure_profile_shape(profile)
    normalized_event = normalize_coach_event_payload(coach_event, now=now)
    occurred_at = normalize_text(normalized_event.get("occurred_at")) or now_iso(now)
    question_id = normalize_text(normalized_event.get("question_id")) or "unknown_question"
    question_type = normalize_text(normalized_event.get("question_type"))
    primary_node_id = normalize_text(normalized_event.get("primary_node_id"))
    secondary_node_ids = normalize_str_list(normalized_event.get("secondary_node_ids"))
    linked_node_ids = unique_list(
        [node_id for node_id in [primary_node_id, *secondary_node_ids] if node_id]
    )
    question_memory = get_or_create_question_memory(profile, question_id)
    question_memory.setdefault("error_type_counts", empty_error_counts())
    question_memory["question_type"] = question_type or question_memory.get("question_type")
    question_memory["source_name"] = normalize_text(normalized_event.get("source_name")) or question_memory.get("source_name")
    question_memory["source_section"] = normalize_text(normalized_event.get("source_section")) or question_memory.get("source_section")
    question_memory["linked_node_ids"] = unique_list(question_memory.get("linked_node_ids", []) + linked_node_ids)
    question_memory["last_seen_at"] = occurred_at
    question_memory["last_event_at"] = occurred_at
    update_question_derived_fields(question_memory)

    for node_id in linked_node_ids:
        node_memory = get_or_create_node_memory(profile, node_id)
        node_memory["linked_question_ids"] = unique_list(
            node_memory.get("linked_question_ids", []) + [question_id]
        )
        node_memory["last_seen_at"] = occurred_at
        node_memory["last_event_at"] = occurred_at
        update_node_derived_fields(node_memory)

    append_capped_event(
        profile,
        build_event_entry(
            event_type="coach",
            occurred_at=occurred_at,
            details={
                "question_id": question_id,
                "question_type": question_type,
                "primary_node_id": primary_node_id,
                "secondary_node_ids": secondary_node_ids,
                "error_type": normalize_text(normalized_event.get("error_type")),
                "coach_mode": normalize_text(normalized_event.get("coach_mode")),
                "coach_trap": normalize_text(normalized_event.get("coach_trap")),
                "coach_prompt": normalize_text(normalized_event.get("coach_prompt")),
                "reply_quality": normalize_text(normalized_event.get("reply_quality")),
                "understands": bool(normalized_event.get("understands")),
                "completed": bool(normalized_event.get("completed")),
                "turn_index": normalized_event.get("turn_index"),
                "done": bool(normalized_event.get("done")),
                "stop_reason": normalize_text(normalized_event.get("stop_reason")),
                "reason": normalize_text(normalized_event.get("reason")),
            },
        ),
    )
    profile["updated_at"] = occurred_at
    refresh_personalization(profile)
    return profile


def apply_review_event(
    profile: dict[str, Any],
    review_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = ensure_profile_shape(profile)
    normalized_event = normalize_review_event_payload(review_event, now=now)
    occurred_at = normalize_text(normalized_event.get("occurred_at")) or now_iso(now)
    action = normalize_text(normalized_event.get("action")) or "unknown"
    target_type = normalize_text(normalized_event.get("target_type")) or ""
    target_id = normalize_text(normalized_event.get("target_id")) or "unknown"
    result = normalize_text(normalized_event.get("result"))
    updated_payload = (
        normalized_event.get("updated_payload")
        if isinstance(normalized_event.get("updated_payload"), dict)
        else {}
    )

    question_lookup = build_question_lookup(profile)
    node_lookup = build_node_lookup(profile)

    linked_node_ids: list[str] = []
    if target_type == QUESTION_TARGET:
        question_memory = get_or_create_question_memory(profile, target_id)
        question_memory.setdefault("error_type_counts", empty_error_counts())
        used_question_snapshot = False
        if updated_payload:
            for state in updated_payload.get("example_question_states", []):
                if normalize_text(state.get("question_id")) == target_id:
                    question_memory["linked_node_ids"] = unique_list(
                        normalize_str_list(state.get("linked_node_ids"))
                    )
                    question_memory["last_result"] = normalize_text(state.get("last_result")) or question_memory.get("last_result", "unseen")
                    question_memory["review_count"] = int(state.get("review_count", question_memory.get("review_count", 0)) or 0)
                    question_memory["question_type"] = (
                        normalize_text(state.get("question_type"))
                        or question_memory.get("question_type")
                    )
                    used_question_snapshot = True
                    break
        linked_node_ids = unique_list(question_memory.get("linked_node_ids", []))
        if action == "review_result":
            if not used_question_snapshot:
                question_memory["review_count"] = int(question_memory.get("review_count", 0) or 0) + 1
            question_memory["last_result"] = normalize_text(result) or question_memory.get("last_result", "unseen")
            if result == "wrong":
                question_memory["wrong_count"] = int(question_memory.get("wrong_count", 0) or 0) + 1
                question_memory["last_wrong_at"] = occurred_at
            elif result == "correct":
                question_memory["correct_count"] = int(question_memory.get("correct_count", 0) or 0) + 1
            elif result == "partial":
                question_memory["partial_count"] = int(question_memory.get("partial_count", 0) or 0) + 1
            question_memory["last_seen_at"] = occurred_at
            question_memory["last_event_at"] = occurred_at
        elif action == "skip_temporarily":
            question_memory["last_seen_at"] = occurred_at
            question_memory["last_event_at"] = occurred_at
        update_question_derived_fields(question_memory)
    elif target_type == NODE_TARGET:
        node_memory = get_or_create_node_memory(profile, target_id)
        linked_node_ids = [target_id]
        if updated_payload:
            for state in updated_payload.get("knowledge_point_states", []):
                if normalize_text(state.get("node_id")) == target_id:
                    node_memory["mastery_hint"] = safe_round(
                        clamp(float(state.get("mastery", node_memory.get("mastery_hint", 0.0)) or 0.0), 0.0, 1.0)
                    )
                    node_memory["stability_hint"] = safe_round(
                        max(float(state.get("stability", node_memory.get("stability_hint", 0.0)) or 0.0), 0.0)
                    )
                    node_memory["linked_question_ids"] = unique_list(
                        normalize_str_list(state.get("linked_question_ids"))
                    )
                    break
        node_memory["last_seen_at"] = occurred_at
        node_memory["last_event_at"] = occurred_at
        if action == "node_needs_more_practice":
            node_memory["practice_request_count"] = int(node_memory.get("practice_request_count", 0) or 0) + 1
            node_memory["consecutive_wrong_count"] = int(node_memory.get("consecutive_wrong_count", 0) or 0) + 1
        elif action == "node_mastered_well":
            node_memory["consecutive_wrong_count"] = 0
        update_node_derived_fields(node_memory)

    for node_id in linked_node_ids:
        node_memory = node_lookup.get(node_id) or get_or_create_node_memory(profile, node_id)
        node_memory["last_seen_at"] = occurred_at
        node_memory["last_event_at"] = occurred_at
        if action == "review_result":
            if result == "wrong":
                node_memory["review_wrong_count"] = int(node_memory.get("review_wrong_count", 0) or 0) + 1
                node_memory["consecutive_wrong_count"] = int(node_memory.get("consecutive_wrong_count", 0) or 0) + 1
                node_memory["last_wrong_at"] = occurred_at
            elif result == "correct":
                node_memory["review_correct_count"] = int(node_memory.get("review_correct_count", 0) or 0) + 1
                node_memory["consecutive_wrong_count"] = 0
            elif result == "partial":
                node_memory["review_partial_count"] = int(node_memory.get("review_partial_count", 0) or 0) + 1
        update_node_derived_fields(node_memory)

    append_capped_event(
        profile,
        build_event_entry(event_type="review", occurred_at=occurred_at, details=normalized_event),
    )
    profile["updated_at"] = occurred_at
    refresh_personalization(profile)
    return profile


def apply_binding_event(
    profile: dict[str, Any],
    binding_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = ensure_profile_shape(profile)
    normalized_event = normalize_binding_event_payload(binding_event, now=now)
    occurred_at = normalize_text(normalized_event.get("occurred_at")) or now_iso(now)
    question_id = normalize_text(normalized_event.get("question_id")) or "unknown_question"
    question_type = normalize_text(normalized_event.get("question_type"))
    primary_node_id = normalize_text(normalized_event.get("primary_node_id"))
    secondary_node_ids = normalize_str_list(normalized_event.get("secondary_node_ids"))
    linked_node_ids = unique_list(
        [node_id for node_id in [primary_node_id, *secondary_node_ids] if node_id]
    )

    question_memory = get_or_create_question_memory(profile, question_id)
    question_memory["question_type"] = question_type or question_memory.get("question_type")
    question_memory["source_name"] = normalize_text(normalized_event.get("source_name")) or question_memory.get("source_name")
    question_memory["source_section"] = normalize_text(normalized_event.get("source_section")) or question_memory.get("source_section")
    question_memory["linked_node_ids"] = unique_list(
        question_memory.get("linked_node_ids", []) + linked_node_ids
    )
    question_memory["last_seen_at"] = occurred_at
    question_memory["last_event_at"] = occurred_at
    update_question_derived_fields(question_memory)

    for node_id in linked_node_ids:
        node_memory = get_or_create_node_memory(profile, node_id)
        node_memory["linked_question_ids"] = unique_list(
            node_memory.get("linked_question_ids", []) + [question_id]
        )
        node_memory["last_seen_at"] = occurred_at
        node_memory["last_event_at"] = occurred_at
        update_node_derived_fields(node_memory)

    append_capped_event(
        profile,
        build_event_entry(event_type="binding", occurred_at=occurred_at, details=normalized_event),
    )
    profile["updated_at"] = occurred_at
    refresh_personalization(profile)
    return profile


def apply_student_choice_event(
    profile: dict[str, Any],
    student_choice_event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    profile = ensure_profile_shape(profile)
    normalized_event = normalize_student_choice_event_payload(student_choice_event, now=now)
    occurred_at = normalize_text(normalized_event.get("occurred_at")) or now_iso(now)
    target_type = normalize_text(normalized_event.get("target_type")) or ""
    target_id = normalize_text(normalized_event.get("target_id")) or "unknown"
    question_id = normalize_text(normalized_event.get("question_id"))
    question_type = normalize_text(normalized_event.get("question_type"))
    primary_node_id = normalize_text(normalized_event.get("primary_node_id"))
    secondary_node_ids = normalize_str_list(normalized_event.get("secondary_node_ids"))
    selected_node_ids = unique_list(
        normalize_str_list(normalized_event.get("selected_node_ids"))
        + [node_id for node_id in [primary_node_id, *secondary_node_ids] if node_id]
    )

    if target_type == "question" or question_id is not None:
        effective_question_id = question_id or target_id
        question_memory = get_or_create_question_memory(profile, effective_question_id)
        question_memory["question_type"] = question_type or question_memory.get("question_type")
        question_memory["source_name"] = normalize_text(normalized_event.get("source_name")) or question_memory.get("source_name")
        question_memory["source_section"] = normalize_text(normalized_event.get("source_section")) or question_memory.get("source_section")
        question_memory["linked_node_ids"] = unique_list(
            question_memory.get("linked_node_ids", []) + selected_node_ids
        )
        question_memory["last_seen_at"] = occurred_at
        question_memory["last_event_at"] = occurred_at
        update_question_derived_fields(question_memory)

        for node_id in selected_node_ids:
            node_memory = get_or_create_node_memory(profile, node_id)
            node_memory["linked_question_ids"] = unique_list(
                node_memory.get("linked_question_ids", []) + [effective_question_id]
            )
            node_memory["last_seen_at"] = occurred_at
            node_memory["last_event_at"] = occurred_at
            update_node_derived_fields(node_memory)
    elif target_type == NODE_TARGET:
        node_memory = get_or_create_node_memory(profile, target_id)
        node_memory["last_seen_at"] = occurred_at
        node_memory["last_event_at"] = occurred_at
        update_node_derived_fields(node_memory)

    append_capped_event(
        profile,
        build_event_entry(
            event_type="student_choice",
            occurred_at=occurred_at,
            details=normalized_event,
        ),
    )
    profile["updated_at"] = occurred_at
    refresh_personalization(profile)
    return profile


def sort_memory_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        events,
        key=lambda item: (
            normalize_text(item.get("occurred_at")) or "",
            normalize_text(item.get("event_id")) or "",
            normalize_text(item.get("event_type")) or "",
        ),
    )


def apply_memory_event(
    profile: dict[str, Any],
    event: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    event_type = normalize_text(event.get("event_type")) or ""
    if event_type == "diagnosis":
        return apply_diagnosis_event(profile, event, now=now)
    if event_type == "coach":
        return apply_coach_event(profile, event, now=now)
    if event_type == "review":
        return apply_review_event(profile, event, now=now)
    if event_type == "binding":
        return apply_binding_event(profile, event, now=now)
    if event_type == "student_choice":
        return apply_student_choice_event(profile, event, now=now)
    return profile


def normalize_dimension_scores(raw_scores: dict[str, float]) -> dict[str, float]:
    max_score = max([float(value or 0.0) for value in raw_scores.values()], default=0.0)
    if max_score <= 0:
        return {key: 0.0 for key in raw_scores}
    return {key: safe_round(clamp(float(value or 0.0) / max_score, 0.0, 1.0)) for key, value in raw_scores.items()}


def build_teaching_preferences(profile: dict[str, Any]) -> dict[str, Any]:
    error_counts = profile.get("error_type_counts", {})
    raw_scores = empty_dimension_scores(TEACHING_DIMENSIONS)
    for error_type, count in error_counts.items():
        if int(count or 0) <= 0:
            continue
        for dimension, weight in ERROR_TO_TEACHING.get(error_type, {}).items():
            raw_scores[dimension] += float(count) * weight

    for node_memory in profile.get("node_memories", []):
        intervention = normalize_text(node_memory.get("recommended_intervention"))
        if intervention == "reteach_concept":
            raw_scores["concept_explain_bias"] += 1.2
            raw_scores["direct_explain_bias"] += 0.8
        elif intervention == "show_strategy_first":
            raw_scores["strategy_scaffold_bias"] += 1.2
            raw_scores["step_by_step_bias"] += 0.8
        elif intervention == "read_conditions_first":
            raw_scores["condition_reading_bias"] += 1.0
        elif intervention == "drill_with_checklist":
            raw_scores["self_check_bias"] += 0.8
        elif intervention == "stabilize_with_examples":
            raw_scores["step_by_step_bias"] += 0.4

    scores = normalize_dimension_scores(raw_scores)
    dominant = dominant_error_type(error_counts)
    recommended_mode = "balanced"
    if scores["concept_explain_bias"] >= max(scores.values(), default=0.0):
        recommended_mode = "concept_first"
    elif scores["strategy_scaffold_bias"] >= max(scores.values(), default=0.0):
        recommended_mode = "strategy_first"
    elif scores["condition_reading_bias"] >= max(scores.values(), default=0.0):
        recommended_mode = "condition_first"
    elif scores["self_check_bias"] >= max(scores.values(), default=0.0):
        recommended_mode = "checklist_first"

    return {
        "dominant_error_type": dominant,
        "scores": scores,
        "recommended_mode": recommended_mode,
    }


def build_practice_preferences(profile: dict[str, Any]) -> dict[str, Any]:
    error_counts = profile.get("error_type_counts", {})
    raw_scores = empty_dimension_scores(PRACTICE_DIMENSIONS)
    for error_type, count in error_counts.items():
        if int(count or 0) <= 0:
            continue
        for dimension, weight in ERROR_TO_PRACTICE.get(error_type, {}).items():
            raw_scores[dimension] += float(count) * weight

    recurrent_nodes = 0
    for node_memory in profile.get("node_memories", []):
        if normalize_text(node_memory.get("recommended_intervention")) in {
            "reteach_concept",
            "show_strategy_first",
            "stabilize_with_examples",
        }:
            recurrent_nodes += 1
    if recurrent_nodes > 0:
        raw_scores["leaf_first_bias"] += 0.6 * recurrent_nodes
        raw_scores["representative_question_bias"] += 0.35 * recurrent_nodes

    scores = normalize_dimension_scores(raw_scores)
    recommended_review_mode = "mixed"
    if scores["leaf_first_bias"] >= 0.75 and scores["leaf_first_bias"] > scores["question_first_bias"]:
        recommended_review_mode = "leaf_first"
    elif scores["question_first_bias"] >= 0.75 and scores["question_first_bias"] > scores["leaf_first_bias"]:
        recommended_review_mode = "question_first"

    return {
        "scores": scores,
        "recommended_review_mode": recommended_review_mode,
    }


def build_alerts(profile: dict[str, Any]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    global_counter = profile.get("error_type_counts", {})
    total = total_error_count(global_counter)
    dominant = dominant_error_type(global_counter)
    signal = profile_signal_snapshot(profile)
    if total > 0 and dominant is not None:
        dominant_share = int(global_counter.get(dominant, 0) or 0) / total
        if dominant_share >= 0.45:
            alerts.append(
                {
                    "kind": "dominant_error_pattern",
                    "error_type": dominant,
                    "share": safe_round(dominant_share),
                    "signal_strength": (
                        TENTATIVE_SIGNAL
                        if signal["is_light_observation"]
                        else ESTABLISHED_SIGNAL
                    ),
                    "reason": (
                        "Current evidence suggests one error pattern is leading recent mistakes."
                        if signal["is_light_observation"]
                        else "A single error pattern is dominating the student's recent mistakes."
                    ),
                }
            )

    for node_memory in profile.get("node_memories", []):
        wrong_pressure = total_wrong_pressure(node_memory)
        intervention = normalize_text(node_memory.get("recommended_intervention"))
        if wrong_pressure >= 2 and intervention is not None:
            alerts.append(
                {
                    "kind": "recurrent_node_confusion",
                    "node_id": node_memory["node_id"],
                    "intervention": intervention,
                    "signal_strength": normalize_text(node_memory.get("signal_strength")) or TENTATIVE_SIGNAL,
                    "reason": (
                        "This node is starting to show repeated confusion and may need targeted intervention."
                        if normalize_text(node_memory.get("signal_strength")) != ESTABLISHED_SIGNAL
                        else "This node has repeated confusion and should get targeted intervention."
                    ),
                }
            )
    return alerts


def build_personalization_summary(profile: dict[str, Any]) -> dict[str, Any]:
    global_counter = profile.get("error_type_counts", {})
    total = total_error_count(global_counter)
    dominant = dominant_error_type(global_counter)
    signal = profile_signal_snapshot(profile)
    dominant_strength = signal_strength(
        int(global_counter.get(dominant, 0) or 0) if dominant else 0,
        ESTABLISHED_ERROR_EVENT_THRESHOLD,
    )
    top_error_types = [
        {
            "error_type": key,
            "count": int(value),
            "signal_strength": signal_strength(
                int(value),
                ESTABLISHED_ERROR_EVENT_THRESHOLD,
            ),
        }
        for key, value in sort_counter_items(global_counter)
        if int(value) > 0
    ]
    troubled_nodes = sorted(
        profile.get("node_memories", []),
        key=lambda item: (
            -(
                int(item.get("observed_wrong_count", 0) or 0)
                + int(item.get("review_wrong_count", 0) or 0)
            ),
            item["node_id"],
        ),
    )
    top_nodes = [
        {
            "node_id": item["node_id"],
            "title": leaf_title_from_node_id(item["node_id"]),
            "dominant_error_type": item.get("dominant_error_type"),
            "recommended_intervention": item.get("recommended_intervention"),
            "signal_strength": item.get("signal_strength"),
            "observation_stage": item.get("observation_stage"),
        }
        for item in troubled_nodes[:5]
        if total_wrong_pressure(item) > 0
    ]

    teaching = profile.get("teaching_preferences", {})
    practice = profile.get("practice_preferences", {})
    alerts = build_alerts(profile)

    notes: list[str] = []
    if dominant == "missing_strategy":
        notes.append(
            "Current evidence suggests this student more often knows local facts but misses the solving route. Explain intermediate goals first."
            if signal["is_light_observation"]
            else "This student more often knows local facts but misses the solving route. Explain intermediate goals first."
        )
    elif dominant == "concept_gap":
        notes.append(
            "Current evidence suggests concept reteaching may help before more drilling on similar questions."
            if signal["is_light_observation"]
            else "This student needs concept reteaching before more drilling on similar questions."
        )
    elif dominant == "calculation":
        notes.append(
            "Current evidence suggests this student may benefit from repeated similar drills plus a checking checklist."
            if signal["is_light_observation"]
            else "This student benefits more from repeated similar drills plus a checking checklist."
        )
    elif dominant == "misreading":
        notes.append(
            "Current evidence suggests this student should restate conditions before solving."
            if signal["is_light_observation"]
            else "This student should be forced to restate conditions before solving."
        )
    elif dominant == "careless":
        notes.append(
            "Current evidence suggests this student should finish each solution with a short self-check routine."
            if signal["is_light_observation"]
            else "This student should finish each solution with a short self-check routine."
        )

    for node in top_nodes[:3]:
        intervention = normalize_text(node.get("recommended_intervention"))
        if intervention in INTERVENTION_TEXT:
            prefix = (
                "初步观察"
                if normalize_text(node.get("signal_strength")) != ESTABLISHED_SIGNAL
                else "稳定观察"
            )
            notes.append(f"{prefix} - {node['title']}: {INTERVENTION_TEXT[intervention]}")

    return {
        "dominant_error_type": dominant,
        "dominant_error_signal_strength": dominant_strength,
        "dominant_error_share": safe_round((int(global_counter.get(dominant, 0) or 0) / total), 4) if dominant and total > 0 else 0.0,
        "memory_stage": signal["memory_stage"],
        "observation_counts": {
            "diagnosis_event_count": signal["diagnosis_event_count"],
            "coach_event_count": signal["coach_event_count"],
            "review_event_count": signal["review_event_count"],
            "distinct_question_count": signal["distinct_question_count"],
        },
        "top_error_types": top_error_types,
        "top_recurrent_nodes": top_nodes,
        "recommended_teaching_mode": teaching.get("recommended_mode"),
        "recommended_review_mode": practice.get("recommended_review_mode"),
        "alerts": alerts,
        "notes": notes,
    }


def build_agent_memory_text(profile: dict[str, Any]) -> str:
    summary = profile.get("personalization_summary", {})
    teaching = profile.get("teaching_preferences", {})
    practice = profile.get("practice_preferences", {})
    parts = [
        f"Student ID: {profile.get('student_id')}",
        f"Memory stage: {summary.get('memory_stage') or EARLY_OBSERVATION_STAGE}",
        f"Dominant error type: {summary.get('dominant_error_type') or 'unknown'}",
        f"Dominant error signal: {summary.get('dominant_error_signal_strength') or 'none'}",
        f"Recommended teaching mode: {summary.get('recommended_teaching_mode') or 'balanced'}",
        f"Recommended review mode: {summary.get('recommended_review_mode') or 'mixed'}",
    ]

    top_errors = summary.get("top_error_types") or []
    if top_errors:
        parts.append(
            "Recent error mix: "
            + "; ".join(f"{item['error_type']}={item['count']}" for item in top_errors[:4])
        )

    top_nodes = summary.get("top_recurrent_nodes") or []
    if top_nodes:
        parts.append(
            "Recurrent trouble nodes: "
            + "; ".join(
                f"{item['title']}({item['dominant_error_type'] or 'unknown'})"
                for item in top_nodes[:4]
            )
        )

    teaching_scores = (teaching.get("scores") or {})
    if teaching_scores:
        parts.append(
            "Teaching emphasis: "
            + "; ".join(f"{key}={value}" for key, value in teaching_scores.items())
        )

    practice_scores = (practice.get("scores") or {})
    if practice_scores:
        parts.append(
            "Practice emphasis: "
            + "; ".join(f"{key}={value}" for key, value in practice_scores.items())
        )

    notes = summary.get("notes") or []
    if notes:
        parts.append("Personalization notes: " + " ".join(notes[:4]))

    return "\n".join(parts)


def build_memory_graph(profile: dict[str, Any]) -> dict[str, Any]:
    summary = profile.get("personalization_summary", {})
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    student_node_id = f"student:{profile.get('student_id')}"

    nodes.append(
        {
            "node_id": student_node_id,
            "node_type": "student_profile",
            "title": str(profile.get("student_id")),
            "embedding_text": build_agent_memory_text(profile),
        }
    )

    for item in summary.get("top_error_types", [])[:5]:
        error_type = item["error_type"]
        error_node_id = f"error_type:{error_type}"
        nodes.append(
            {
                "node_id": error_node_id,
                "node_type": "error_type",
                "title": error_type,
                "weight": item["count"],
                "embedding_text": f"Student repeatedly shows {error_type}. Count={item['count']}.",
            }
        )
        edges.append(
            {
                "source": student_node_id,
                "target": error_node_id,
                "relation": "shows_error_pattern",
                "weight": item["count"],
            }
        )

    for item in summary.get("top_recurrent_nodes", [])[:8]:
        node_id = item["node_id"]
        graph_node_id = f"leaf:{node_id}"
        intervention = normalize_text(item.get("recommended_intervention"))
        nodes.append(
            {
                "node_id": graph_node_id,
                "node_type": "knowledge_leaf",
                "title": item["title"],
                "embedding_text": (
                    f"Student recurrently struggles with {item['title']}. "
                    f"Dominant error={item.get('dominant_error_type') or 'unknown'}. "
                    f"Recommended intervention={intervention or 'none'}."
                ),
            }
        )
        edges.append(
            {
                "source": student_node_id,
                "target": graph_node_id,
                "relation": "recurrently_struggles_with",
                "weight": 1.0,
            }
        )

    for question_memory in sorted(
        profile.get("question_memories", []),
        key=lambda item: (-int(item.get("wrong_count", 0) or 0), item["question_id"]),
    )[:8]:
        if int(question_memory.get("wrong_count", 0) or 0) <= 0:
            continue
        question_node_id = f"question:{question_memory['question_id']}"
        nodes.append(
            {
                "node_id": question_node_id,
                "node_type": "wrong_question",
                "title": question_memory["question_id"],
                "embedding_text": (
                    f"Question {question_memory['question_id']} has wrong_count="
                    f"{int(question_memory.get('wrong_count', 0) or 0)} and last_error_type="
                    f"{question_memory.get('last_error_type') or 'unknown'}."
                ),
            }
        )
        for node_id in question_memory.get("linked_node_ids", [])[:3]:
            edges.append(
                {
                    "source": question_node_id,
                    "target": f"leaf:{node_id}",
                    "relation": "binds_to",
                    "weight": 1.0,
                }
            )

    return {"nodes": nodes, "edges": edges}


def refresh_personalization(profile: dict[str, Any]) -> dict[str, Any]:
    profile["teaching_preferences"] = build_teaching_preferences(profile)
    profile["practice_preferences"] = build_practice_preferences(profile)
    profile["personalization_summary"] = build_personalization_summary(profile)
    profile["memory_graph"] = build_memory_graph(profile)
    profile["agent_memory_text"] = build_agent_memory_text(profile)
    return profile


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_profile(
    *,
    student_id: str,
    review_state: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    diagnosis_events: list[dict[str, Any]] | None = None,
    review_events: list[dict[str, Any]] | None = None,
    coach_events: list[dict[str, Any]] | None = None,
    binding_events: list[dict[str, Any]] | None = None,
    student_choice_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    profile = initialize_student_memory_profile(student_id)
    if review_state is not None:
        sync_from_review_state(profile, review_state)
    replay_events = list(events or [])
    if not replay_events:
        replay_events.extend(diagnosis_events or [])
        replay_events.extend(review_events or [])
        replay_events.extend(coach_events or [])
        replay_events.extend(binding_events or [])
        replay_events.extend(student_choice_events or [])
    for event in sort_memory_events(replay_events):
        apply_memory_event(profile, event)
    refresh_personalization(profile)
    return profile


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--student-id", default="demo_student")
    parser.add_argument("--review-state")
    parser.add_argument("--diagnosis-events")
    parser.add_argument("--review-events")
    parser.add_argument("--coach-events")
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_PATH))
    args = parser.parse_args()

    review_state = load_json(Path(args.review_state)) if args.review_state else None
    diagnosis_events = load_json(Path(args.diagnosis_events)) if args.diagnosis_events else None
    review_events = load_json(Path(args.review_events)) if args.review_events else None
    coach_events = load_json(Path(args.coach_events)) if args.coach_events else None
    if diagnosis_events is not None and not isinstance(diagnosis_events, list):
        raise ValueError("diagnosis-events must be a JSON list")
    if review_events is not None and not isinstance(review_events, list):
        raise ValueError("review-events must be a JSON list")
    if coach_events is not None and not isinstance(coach_events, list):
        raise ValueError("coach-events must be a JSON list")

    profile = build_profile(
        student_id=args.student_id,
        review_state=review_state,
        diagnosis_events=diagnosis_events,
        review_events=review_events,
        coach_events=coach_events,
    )
    write_json(Path(args.out_json), profile)
    summary = profile.get("personalization_summary", {})
    print(
        "student_memory:"
        f" student_id={profile['student_id']}"
        f" dominant_error_type={summary.get('dominant_error_type') or 'unknown'}"
        f" recurrent_nodes={len(summary.get('top_recurrent_nodes') or [])}"
    )


if __name__ == "__main__":
    main()

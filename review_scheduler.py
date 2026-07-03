from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from student_memory_rules import (
    build_memory_node_lookup,
    build_memory_question_lookup,
    compute_node_memory_priority_boost as compute_node_memory_bias,
    compute_question_memory_priority_boost as compute_question_memory_bias,
    get_personalization_summary,
    normalize_text,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_REVIEW_SEED_PATH = (
    ROOT / "docs" / "rag_samples" / "taizhou_simulated_exam_review_seed_batch_01.json"
)

DEFAULT_NODE_LIMIT = 5
DEFAULT_QUESTION_LIMIT = 5
DEFAULT_BUNDLE_LIMIT = 5
DEFAULT_BUNDLE_QUESTION_LIMIT = 3
DEFAULT_BUNDLE_QUESTION_MIN = 2
DEFAULT_NEW_STATE_STABILITY_DAYS = 0.5
DEFAULT_NEW_STATE_FORGET_SCORE = 0.95
DEFAULT_MAX_SESSION_PRIORITY_BOOST = 0.8
DEFAULT_MAX_MEMORY_NODE_BOOST = 0.18
DEFAULT_MAX_MEMORY_QUESTION_BOOST = 0.2
QUESTION_REVIEW_MODE = "question_first"
KNOWLEDGE_REVIEW_MODE = "leaf_first"
MIXED_REVIEW_MODE = "mixed"


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


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def parse_datetime(value: Any) -> datetime | None:
    text = normalize_text(value)
    if text is None:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def ensure_timezone(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def now_from_value(value: str | None = None) -> datetime:
    if value:
        parsed = parse_datetime(value)
        if parsed is not None:
            return ensure_timezone(parsed)
    return datetime.now(timezone.utc)


def elapsed_days(now: datetime, last_reviewed_at: datetime | None) -> float:
    if last_reviewed_at is None:
        return 999.0
    delta_seconds = max((now - ensure_timezone(last_reviewed_at)).total_seconds(), 0.0)
    return delta_seconds / 86400.0


def hours_until(now: datetime, target_at: datetime | None) -> float | None:
    if target_at is None:
        return None
    delta_seconds = (ensure_timezone(target_at) - now).total_seconds()
    return delta_seconds / 3600.0


def is_temporarily_skipped(
    *,
    now: datetime,
    manual_skip_until: datetime | None,
) -> bool:
    if manual_skip_until is None:
        return False
    return ensure_timezone(manual_skip_until) > now


def compute_forget_score(
    *,
    now: datetime,
    last_reviewed_at: datetime | None,
    stability_days: float,
    state: str,
) -> float:
    normalized_state = (normalize_text(state) or "new").lower()
    if normalized_state == "new" or last_reviewed_at is None:
        return DEFAULT_NEW_STATE_FORGET_SCORE
    stability = max(stability_days, DEFAULT_NEW_STATE_STABILITY_DAYS)
    days = elapsed_days(now, last_reviewed_at)
    score = 1.0 - math.exp(-days / stability)
    return clamp(score, 0.0, 1.0)


def compute_due_score(
    *,
    now: datetime,
    next_review_at: datetime | None,
    state: str,
) -> float:
    normalized_state = (normalize_text(state) or "new").lower()
    if normalized_state == "new" or next_review_at is None:
        return 1.0
    hours_left = hours_until(now, next_review_at)
    if hours_left is None:
        return 1.0
    if hours_left <= 0:
        overdue_hours = min(abs(hours_left), 168.0)
        return clamp(0.7 + overdue_hours / 168.0 * 0.3, 0.0, 1.0)
    if hours_left <= 24:
        return clamp(0.4 + (24.0 - hours_left) / 24.0 * 0.3, 0.0, 1.0)
    return clamp(max(0.0, 1.0 - hours_left / 168.0) * 0.35, 0.0, 0.35)


def compute_session_priority(
    *,
    now: datetime,
    state: dict[str, Any],
) -> tuple[float, str | None, str | None]:
    boost = clamp(
        float(state.get("session_priority_boost", 0.0) or 0.0),
        -DEFAULT_MAX_SESSION_PRIORITY_BOOST,
        DEFAULT_MAX_SESSION_PRIORITY_BOOST,
    )
    until = parse_datetime(state.get("session_priority_until"))
    if boost == 0.0 or until is None:
        return 0.0, None, None
    until = ensure_timezone(until)
    if until <= now:
        return 0.0, None, None
    return boost, until.isoformat(), normalize_text(state.get("session_priority_reason"))


def compute_question_wrong_pressure(state: dict[str, Any]) -> float:
    review_count = max(float(state.get("review_count", 0) or 0), 0.0)
    last_result = (normalize_text(state.get("last_result")) or "unseen").lower()
    base = 0.0
    if last_result == "wrong":
        base = 1.0
    elif last_result == "partial":
        base = 0.6
    elif last_result == "unseen":
        base = 0.4
    else:
        base = 0.1
    repetition_penalty = min(review_count / 10.0, 0.2)
    return clamp(base + repetition_penalty, 0.0, 1.0)


def compute_node_wrong_pressure(
    node_state: dict[str, Any],
    question_lookup: dict[str, dict[str, Any]],
) -> float:
    linked_ids = normalize_str_list(node_state.get("linked_question_ids"))
    if not linked_ids:
        return 0.0
    pressures: list[float] = []
    for question_id in linked_ids:
        question_state = question_lookup.get(question_id)
        if question_state is None:
            continue
        pressures.append(compute_question_wrong_pressure(question_state))
    if not pressures:
        return 0.0
    return clamp(sum(pressures) / len(pressures), 0.0, 1.0)


def compute_node_memory_priority_boost(
    node_id: str,
    student_memory_lookup: dict[str, dict[str, Any]],
) -> tuple[float, str | None]:
    bias = compute_node_memory_bias(node_id, student_memory_lookup)
    return bias.boost, bias.reason


def compute_question_memory_priority_boost(
    question_id: str,
    student_memory_lookup: dict[str, dict[str, Any]],
) -> tuple[float, str | None]:
    bias = compute_question_memory_bias(question_id, student_memory_lookup)
    return bias.boost, bias.reason


def build_node_priority(
    *,
    node_state: dict[str, Any],
    question_lookup: dict[str, dict[str, Any]],
    student_memory_lookup: dict[str, dict[str, Any]] | None,
    now: datetime,
) -> dict[str, Any]:
    node_id = node_state["node_id"]
    mastery = clamp(float(node_state.get("mastery", 0.0) or 0.0), 0.0, 1.0)
    stability = max(float(node_state.get("stability", 0.0) or 0.0), 0.0)
    state = normalize_text(node_state.get("state")) or "new"
    last_reviewed_at = parse_datetime(node_state.get("last_reviewed_at"))
    next_review_at = parse_datetime(node_state.get("next_review_at"))
    manual_priority_bias = clamp(
        float(node_state.get("manual_priority_bias", 0.0) or 0.0),
        -0.5,
        0.5,
    )
    session_priority_boost, session_priority_until, session_priority_reason = compute_session_priority(
        now=now,
        state=node_state,
    )
    manual_skip_until = parse_datetime(node_state.get("manual_skip_until"))
    skipped = is_temporarily_skipped(
        now=now,
        manual_skip_until=manual_skip_until,
    )
    forget_score = compute_forget_score(
        now=now,
        last_reviewed_at=last_reviewed_at,
        stability_days=stability,
        state=state,
    )
    due_score = compute_due_score(
        now=now,
        next_review_at=next_review_at,
        state=state,
    )
    low_mastery_score = 1.0 - mastery
    linked_wrong_pressure = compute_node_wrong_pressure(node_state, question_lookup)
    new_item_bonus = 1.0 if state.lower() == "new" else 0.0
    memory_priority_boost, memory_priority_reason = compute_node_memory_priority_boost(
        node_id,
        student_memory_lookup or {},
    )

    priority_score = (
        0.35 * due_score
        + 0.25 * forget_score
        + 0.20 * low_mastery_score
        + 0.15 * linked_wrong_pressure
        + 0.05 * new_item_bonus
    )
    priority_score += manual_priority_bias
    priority_score += session_priority_boost
    priority_score += memory_priority_boost

    return {
        "node_id": node_id,
        "priority_score": safe_round(priority_score),
        "due_score": safe_round(due_score),
        "forget_score": safe_round(forget_score),
        "low_mastery_score": safe_round(low_mastery_score),
        "linked_wrong_pressure": safe_round(linked_wrong_pressure),
        "state": state,
        "mastery": safe_round(mastery),
        "stability": safe_round(stability),
        "next_review_at": (
            ensure_timezone(next_review_at).isoformat()
            if next_review_at is not None
            else None
        ),
        "is_due_now": bool(next_review_at is None or ensure_timezone(next_review_at) <= now),
        "linked_question_ids": normalize_str_list(node_state.get("linked_question_ids")),
        "priority_note": normalize_text(node_state.get("priority_note")),
        "manual_priority_bias": safe_round(manual_priority_bias),
        "session_priority_boost": safe_round(session_priority_boost),
        "session_priority_until": session_priority_until,
        "session_priority_reason": session_priority_reason,
        "memory_priority_boost": safe_round(memory_priority_boost),
        "memory_priority_reason": memory_priority_reason,
        "manual_skip_until": (
            ensure_timezone(manual_skip_until).isoformat()
            if manual_skip_until is not None
            else None
        ),
        "is_temporarily_skipped": skipped,
    }


def build_question_priority(
    *,
    question_state: dict[str, Any],
    node_lookup: dict[str, dict[str, Any]],
    student_memory_lookup: dict[str, dict[str, Any]] | None,
    now: datetime,
) -> dict[str, Any]:
    question_id = question_state["question_id"]
    stability = max(float(question_state.get("stability", 0.0) or 0.0), 0.0)
    state = normalize_text(question_state.get("state")) or "new"
    last_reviewed_at = parse_datetime(question_state.get("last_reviewed_at"))
    next_review_at = parse_datetime(question_state.get("next_review_at"))
    manual_priority_bias = clamp(
        float(question_state.get("manual_priority_bias", 0.0) or 0.0),
        -0.5,
        0.5,
    )
    session_priority_boost, session_priority_until, session_priority_reason = compute_session_priority(
        now=now,
        state=question_state,
    )
    manual_skip_until = parse_datetime(question_state.get("manual_skip_until"))
    skipped = is_temporarily_skipped(
        now=now,
        manual_skip_until=manual_skip_until,
    )
    forget_score = compute_forget_score(
        now=now,
        last_reviewed_at=last_reviewed_at,
        stability_days=stability,
        state=state,
    )
    due_score = compute_due_score(
        now=now,
        next_review_at=next_review_at,
        state=state,
    )
    wrong_pressure = compute_question_wrong_pressure(question_state)
    primary_node_ids = normalize_str_list(question_state.get("primary_node_ids"))
    primary_mastery = 0.0
    if primary_node_ids:
        matched = [
            clamp(float(node_lookup[node_id].get("mastery", 0.0) or 0.0), 0.0, 1.0)
            for node_id in primary_node_ids
            if node_id in node_lookup
        ]
        if matched:
            primary_mastery = sum(matched) / len(matched)

    node_weakness = 1.0 - primary_mastery
    memory_priority_boost, memory_priority_reason = compute_question_memory_priority_boost(
        question_id,
        student_memory_lookup or {},
    )
    priority_score = (
        0.35 * due_score
        + 0.25 * forget_score
        + 0.25 * wrong_pressure
        + 0.15 * node_weakness
    )
    priority_score += manual_priority_bias
    priority_score += session_priority_boost
    priority_score += memory_priority_boost

    return {
        "question_id": question_id,
        "priority_score": safe_round(priority_score),
        "due_score": safe_round(due_score),
        "forget_score": safe_round(forget_score),
        "wrong_pressure": safe_round(wrong_pressure),
        "primary_node_weakness": safe_round(node_weakness),
        "state": state,
        "last_result": normalize_text(question_state.get("last_result")) or "unseen",
        "next_review_at": (
            ensure_timezone(next_review_at).isoformat()
            if next_review_at is not None
            else None
        ),
        "is_due_now": bool(next_review_at is None or ensure_timezone(next_review_at) <= now),
        "linked_node_ids": normalize_str_list(question_state.get("linked_node_ids")),
        "primary_node_ids": primary_node_ids,
        "secondary_node_ids": normalize_str_list(question_state.get("secondary_node_ids")),
        "priority_note": normalize_text(question_state.get("priority_note")),
        "manual_priority_bias": safe_round(manual_priority_bias),
        "session_priority_boost": safe_round(session_priority_boost),
        "session_priority_until": session_priority_until,
        "session_priority_reason": session_priority_reason,
        "memory_priority_boost": safe_round(memory_priority_boost),
        "memory_priority_reason": memory_priority_reason,
        "manual_skip_until": (
            ensure_timezone(manual_skip_until).isoformat()
            if manual_skip_until is not None
            else None
        ),
        "is_temporarily_skipped": skipped,
    }


def sort_priority_items(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (-float(item.get(key, 0.0)), str(item.get("node_id") or item.get("question_id") or "")),
    )


def node_path_segments(node_id: str) -> list[str]:
    return [segment for segment in (normalize_text(node_id) or "").split(".") if segment]


def shared_prefix_depth(left: str, right: str) -> int:
    left_parts = node_path_segments(left)
    right_parts = node_path_segments(right)
    depth = 0
    for left_part, right_part in zip(left_parts, right_parts):
        if left_part != right_part:
            break
        depth += 1
    return depth


def question_relatedness_to_node(node_id: str, question_priority: dict[str, Any]) -> int:
    linked_node_ids = normalize_str_list(question_priority.get("linked_node_ids"))
    if not linked_node_ids:
        return 0
    return max(shared_prefix_depth(node_id, linked_node_id) for linked_node_id in linked_node_ids)


def choose_bundle_questions(
    *,
    node_id: str,
    node_priority: dict[str, Any],
    question_priorities: dict[str, dict[str, Any]],
    limit: int,
) -> list[str]:
    linked_ids = node_priority.get("linked_question_ids", [])
    candidates: list[dict[str, Any]] = []
    for question_id in linked_ids:
        priority = question_priorities.get(question_id)
        if priority is None:
            continue
        candidates.append(priority)
    ranked = sort_priority_items(candidates, "priority_score")
    due_ranked = [item for item in ranked if item.get("is_due_now")]
    chosen = due_ranked[:limit]
    if len(chosen) < DEFAULT_BUNDLE_QUESTION_MIN:
        seen = {item["question_id"] for item in chosen}
        for item in ranked:
            if item["question_id"] in seen:
                continue
            chosen.append(item)
            seen.add(item["question_id"])
            if len(chosen) >= max(limit, DEFAULT_BUNDLE_QUESTION_MIN):
                break
    if len(chosen) < DEFAULT_BUNDLE_QUESTION_MIN:
        seen = {item["question_id"] for item in chosen}
        related_candidates: list[dict[str, Any]] = []
        for item in question_priorities.values():
            if item["question_id"] in seen:
                continue
            relatedness = question_relatedness_to_node(node_id, item)
            if relatedness < 2:
                continue
            related_candidates.append(
                {
                    "question_id": item["question_id"],
                    "priority_score": item["priority_score"],
                    "relatedness": relatedness,
                }
            )
        related_candidates.sort(
            key=lambda item: (-int(item["relatedness"]), -float(item["priority_score"]), item["question_id"])
        )
        for item in related_candidates:
            priority = question_priorities.get(item["question_id"])
            if priority is None:
                continue
            chosen.append(priority)
            seen.add(item["question_id"])
            if len(chosen) >= max(limit, DEFAULT_BUNDLE_QUESTION_MIN):
                break
    return [item["question_id"] for item in chosen[:limit]]


def choose_mixed_mode(
    node_items: list[dict[str, Any]],
    question_items: list[dict[str, Any]],
) -> str:
    if not node_items and not question_items:
        return MIXED_REVIEW_MODE
    top_node = float(node_items[0]["priority_score"]) if node_items else 0.0
    top_question = float(question_items[0]["priority_score"]) if question_items else 0.0
    if top_question >= top_node + 0.08:
        return QUESTION_REVIEW_MODE
    if top_node >= top_question + 0.08:
        return KNOWLEDGE_REVIEW_MODE
    return MIXED_REVIEW_MODE


@dataclass(frozen=True)
class ReviewScheduleResult:
    now: str
    node_priorities: list[dict[str, Any]]
    question_priorities: list[dict[str, Any]]
    review_plan: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.now,
            "node_priorities": self.node_priorities,
            "question_priorities": self.question_priorities,
            "review_plan": self.review_plan,
        }


def build_review_schedule(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    node_limit: int = DEFAULT_NODE_LIMIT,
    question_limit: int = DEFAULT_QUESTION_LIMIT,
    bundle_limit: int = DEFAULT_BUNDLE_LIMIT,
    bundle_question_limit: int = DEFAULT_BUNDLE_QUESTION_LIMIT,
    user_mode: str | None = None,
    student_memory_profile: dict[str, Any] | None = None,
) -> ReviewScheduleResult:
    current_time = ensure_timezone(now or datetime.now(timezone.utc))
    node_states = payload.get("knowledge_point_states", [])
    question_states = payload.get("example_question_states", [])
    student_memory_node_lookup = build_memory_node_lookup(student_memory_profile)
    student_memory_question_lookup = build_memory_question_lookup(student_memory_profile)
    student_memory_summary = get_personalization_summary(student_memory_profile)

    node_lookup = {
        state["node_id"]: state
        for state in node_states
        if isinstance(state, dict) and "node_id" in state
    }
    question_lookup = {
        state["question_id"]: state
        for state in question_states
        if isinstance(state, dict) and "question_id" in state
    }

    node_priorities = [
        build_node_priority(
            node_state=state,
            question_lookup=question_lookup,
            student_memory_lookup=student_memory_node_lookup,
            now=current_time,
        )
        for state in node_states
        if isinstance(state, dict) and "node_id" in state
    ]
    node_priorities = sort_priority_items(node_priorities, "priority_score")

    question_priorities = [
        build_question_priority(
            question_state=state,
            node_lookup=node_lookup,
            student_memory_lookup=student_memory_question_lookup,
            now=current_time,
        )
        for state in question_states
        if isinstance(state, dict) and "question_id" in state
    ]
    question_priorities = sort_priority_items(question_priorities, "priority_score")

    active_nodes = [
        item for item in node_priorities if not item["is_temporarily_skipped"]
    ]
    active_questions = [
        item for item in question_priorities if not item["is_temporarily_skipped"]
    ]

    limited_nodes = active_nodes[:node_limit]
    limited_questions = active_questions[:question_limit]
    question_priority_lookup = {
        item["question_id"]: item for item in question_priorities
    }

    recommended_bundles: list[dict[str, Any]] = []
    for node_item in limited_nodes[:bundle_limit]:
        question_ids = choose_bundle_questions(
            node_id=node_item["node_id"],
            node_priority=node_item,
            question_priorities=question_priority_lookup,
            limit=bundle_question_limit,
        )
        recommended_bundles.append(
            {
                "node_id": node_item["node_id"],
                "question_ids": question_ids,
                "bundle_reason": "知识点到期，且需要配套题联动复习",
                "priority_score": node_item["priority_score"],
            }
        )

    chosen_mode = (
        normalize_text(user_mode)
        or choose_mixed_mode(limited_nodes, limited_questions)
    )

    review_plan = {
        "mode": chosen_mode,
        "recommended_node_ids": [item["node_id"] for item in limited_nodes],
        "recommended_question_ids": [
            item["question_id"] for item in limited_questions
        ],
        "recommended_bundles": recommended_bundles,
        "student_override_supported": True,
        "student_memory_bias_enabled": bool(student_memory_profile),
        "student_memory_stage": (
            normalize_text(student_memory_summary.get("memory_stage"))
            if isinstance(student_memory_summary, dict)
            else None
        ),
        "override_actions": [
            "mark_important",
            "skip_temporarily",
        ],
        "bundle_policy": {
            "bundle_limit": bundle_limit,
            "bundle_question_min": DEFAULT_BUNDLE_QUESTION_MIN,
            "bundle_question_max": bundle_question_limit,
            "due_time_anchor": "next_review_at",
        },
    }

    return ReviewScheduleResult(
        now=current_time.isoformat(),
        node_priorities=limited_nodes,
        question_priorities=limited_questions,
        review_plan=review_plan,
    )


def load_review_state(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if isinstance(payload.get("updated_payload"), dict):
            return payload["updated_payload"]
        if isinstance(payload.get("review_state"), dict):
            return payload["review_state"]
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--review-state",
        default=str(DEFAULT_REVIEW_SEED_PATH),
        help="Path to review state JSON",
    )
    parser.add_argument(
        "--out-json",
        help="Optional output JSON path",
    )
    parser.add_argument(
        "--mode",
        choices=[QUESTION_REVIEW_MODE, KNOWLEDGE_REVIEW_MODE, MIXED_REVIEW_MODE],
        help="Optional forced review mode",
    )
    parser.add_argument(
        "--student-memory-profile",
        help="Optional student memory profile JSON path",
    )
    parser.add_argument(
        "--now",
        help="Optional ISO-8601 timestamp for deterministic scheduling",
    )
    parser.add_argument("--node-limit", type=int, default=DEFAULT_NODE_LIMIT)
    parser.add_argument("--question-limit", type=int, default=DEFAULT_QUESTION_LIMIT)
    parser.add_argument("--bundle-limit", type=int, default=DEFAULT_BUNDLE_LIMIT)
    parser.add_argument(
        "--bundle-question-limit",
        type=int,
        default=DEFAULT_BUNDLE_QUESTION_LIMIT,
    )
    args = parser.parse_args()

    payload = load_review_state(Path(args.review_state))
    student_memory_profile = (
        json.loads(Path(args.student_memory_profile).read_text(encoding="utf-8"))
        if args.student_memory_profile
        else None
    )
    result = build_review_schedule(
        payload,
        now=now_from_value(args.now),
        node_limit=max(args.node_limit, 1),
        question_limit=max(args.question_limit, 1),
        bundle_limit=max(args.bundle_limit, 1),
        bundle_question_limit=max(args.bundle_question_limit, 1),
        user_mode=args.mode,
        student_memory_profile=student_memory_profile,
    )

    output = result.as_dict()
    if args.out_json:
        write_json(Path(args.out_json), output)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

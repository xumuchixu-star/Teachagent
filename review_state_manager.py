from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_REVIEW_SEED_PATH = (
    ROOT / "docs" / "rag_samples" / "taizhou_simulated_exam_review_seed_batch_01.json"
)

QUESTION_TARGET = "wrong_question"
NODE_TARGET = "knowledge_point"
SUPPORTED_RESULTS = {"correct", "wrong", "partial", "skip"}
SUPPORTED_ACTIONS = {
    "review_result",
    "mark_important",
    "skip_temporarily",
    "node_mastered_well",
    "node_needs_more_practice",
}

DEFAULT_CORRECT_NODE_MASTERY_DELTA = 0.10
DEFAULT_WRONG_NODE_MASTERY_DELTA = -0.14
DEFAULT_PARTIAL_NODE_MASTERY_DELTA = 0.03

DEFAULT_CORRECT_QUESTION_STABILITY_MULTIPLIER = 1.6
DEFAULT_WRONG_QUESTION_STABILITY_MULTIPLIER = 0.45
DEFAULT_PARTIAL_QUESTION_STABILITY_MULTIPLIER = 1.1

DEFAULT_CORRECT_NODE_STABILITY_MULTIPLIER = 1.45
DEFAULT_WRONG_NODE_STABILITY_MULTIPLIER = 0.55
DEFAULT_PARTIAL_NODE_STABILITY_MULTIPLIER = 1.05

DEFAULT_MIN_STABILITY_DAYS = 0.25
DEFAULT_MARK_IMPORTANT_BIAS = 0.25
DEFAULT_SKIP_DAYS = 3.0
DEFAULT_NODE_MASTERED_WELL_STABILITY_MULTIPLIER = 2.2
DEFAULT_NODE_MASTERED_WELL_MASTERY_DELTA = 0.16
DEFAULT_NODE_NEEDS_MORE_PRACTICE_STABILITY_MULTIPLIER = 0.65
DEFAULT_NODE_NEEDS_MORE_PRACTICE_MASTERY_DELTA = -0.08
DEFAULT_LINKED_QUESTION_PRACTICE_BIAS = 0.18
DEFAULT_SESSION_PRIORITY_HOURS = 8.0
DEFAULT_WRONG_QUESTION_SESSION_BOOST = 0.65
DEFAULT_PARTIAL_QUESTION_SESSION_BOOST = 0.35
DEFAULT_NODE_PRACTICE_SESSION_BOOST = 0.55
DEFAULT_NODE_MASTERED_SESSION_REDUCE = -0.2


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


def review_interval_days(stability: float) -> float:
    return max(stability, DEFAULT_MIN_STABILITY_DAYS)


def next_review_at_from_stability(now: datetime, stability: float) -> str:
    return (now + timedelta(days=review_interval_days(stability))).isoformat()


def set_session_priority(
    state: dict[str, Any],
    *,
    boost: float,
    now: datetime,
    hours: float = DEFAULT_SESSION_PRIORITY_HOURS,
    reason: str | None = None,
) -> None:
    state["session_priority_boost"] = safe_round(boost)
    state["session_priority_until"] = (now + timedelta(hours=hours)).isoformat()
    state["session_priority_reason"] = reason


def clear_session_priority(state: dict[str, Any]) -> None:
    state["session_priority_boost"] = 0.0
    state["session_priority_until"] = None
    state["session_priority_reason"] = None


def build_question_lookup(states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        state["question_id"]: state
        for state in states
        if isinstance(state, dict) and "question_id" in state
    }


def build_node_lookup(states: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        state["node_id"]: state
        for state in states
        if isinstance(state, dict) and "node_id" in state
    }


def apply_result_to_question_state(
    state: dict[str, Any],
    *,
    result: str,
    now: datetime,
) -> None:
    normalized = result.lower()
    mastery = clamp(float(state.get("mastery", 0.0) or 0.0), 0.0, 1.0)
    stability = max(float(state.get("stability", 0.0) or 0.0), DEFAULT_MIN_STABILITY_DAYS)
    review_count = int(state.get("review_count", 0) or 0)

    if normalized == "correct":
        mastery = clamp(mastery + 0.12, 0.0, 1.0)
        stability *= DEFAULT_CORRECT_QUESTION_STABILITY_MULTIPLIER
        state["state"] = "review" if mastery < 0.75 else "stable"
    elif normalized == "wrong":
        mastery = clamp(mastery - 0.16, 0.0, 1.0)
        stability *= DEFAULT_WRONG_QUESTION_STABILITY_MULTIPLIER
        state["state"] = "learning"
    elif normalized == "partial":
        mastery = clamp(mastery + 0.03, 0.0, 1.0)
        stability *= DEFAULT_PARTIAL_QUESTION_STABILITY_MULTIPLIER
        state["state"] = "learning"
    else:
        state["state"] = state.get("state", "new")

    state["mastery"] = safe_round(mastery)
    state["stability"] = safe_round(max(stability, DEFAULT_MIN_STABILITY_DAYS))
    state["last_result"] = normalized
    state["review_count"] = review_count + (0 if normalized == "skip" else 1)
    state["last_reviewed_at"] = now.isoformat()
    state["next_review_at"] = next_review_at_from_stability(now, stability)
    state["manual_skip_until"] = None
    if normalized == "wrong":
        set_session_priority(
            state,
            boost=DEFAULT_WRONG_QUESTION_SESSION_BOOST,
            now=now,
            reason="本轮刚做错，立即回炉复习",
        )
        state["next_review_at"] = now.isoformat()
    elif normalized == "partial":
        set_session_priority(
            state,
            boost=DEFAULT_PARTIAL_QUESTION_SESSION_BOOST,
            now=now,
            reason="本轮部分会做，建议继续趁热练",
        )
        state["next_review_at"] = now.isoformat()
    elif normalized == "correct":
        clear_session_priority(state)
    elif normalized == "skip":
        set_session_priority(
            state,
            boost=0.12,
            now=now,
            hours=4.0,
            reason="本轮跳过，稍后再提醒一次",
        )


def apply_delta_to_node_state(
    state: dict[str, Any],
    *,
    mastery_delta: float,
    stability_multiplier: float,
    now: datetime,
    result: str,
) -> None:
    mastery = clamp(float(state.get("mastery", 0.0) or 0.0), 0.0, 1.0)
    stability = max(float(state.get("stability", 0.0) or 0.0), DEFAULT_MIN_STABILITY_DAYS)
    correct_count = int(state.get("correct_count", 0) or 0)
    wrong_count = int(state.get("wrong_count", 0) or 0)

    mastery = clamp(mastery + mastery_delta, 0.0, 1.0)
    stability = max(stability * stability_multiplier, DEFAULT_MIN_STABILITY_DAYS)

    if result == "wrong":
        wrong_count += 1
        state["state"] = "learning"
    elif result == "correct":
        correct_count += 1
        state["state"] = "review" if mastery < 0.8 else "stable"
    elif result == "partial":
        state["state"] = "learning"

    state["mastery"] = safe_round(mastery)
    state["stability"] = safe_round(stability)
    state["correct_count"] = correct_count
    state["wrong_count"] = wrong_count
    state["last_reviewed_at"] = now.isoformat()
    state["next_review_at"] = next_review_at_from_stability(now, stability)
    state["manual_skip_until"] = None
    if result == "wrong":
        set_session_priority(
            state,
            boost=DEFAULT_NODE_PRACTICE_SESSION_BOOST,
            now=now,
            reason="关联题刚做错，当前知识点需要马上加强",
        )
        state["next_review_at"] = now.isoformat()
    elif result == "partial":
        set_session_priority(
            state,
            boost=0.28,
            now=now,
            reason="关联题部分会做，当前知识点建议继续跟进",
        )
        state["next_review_at"] = now.isoformat()
    elif result == "correct":
        clear_session_priority(state)


def propagate_question_result_to_nodes(
    question_state: dict[str, Any],
    *,
    node_lookup: dict[str, dict[str, Any]],
    result: str,
    now: datetime,
) -> None:
    primary_ids = normalize_str_list(question_state.get("primary_node_ids"))
    secondary_ids = normalize_str_list(question_state.get("secondary_node_ids"))

    if result == "correct":
        primary_delta = DEFAULT_CORRECT_NODE_MASTERY_DELTA
        primary_stability_multiplier = DEFAULT_CORRECT_NODE_STABILITY_MULTIPLIER
        secondary_delta = 0.05
        secondary_stability_multiplier = 1.2
    elif result == "wrong":
        primary_delta = DEFAULT_WRONG_NODE_MASTERY_DELTA
        primary_stability_multiplier = DEFAULT_WRONG_NODE_STABILITY_MULTIPLIER
        secondary_delta = -0.06
        secondary_stability_multiplier = 0.8
    elif result == "partial":
        primary_delta = DEFAULT_PARTIAL_NODE_MASTERY_DELTA
        primary_stability_multiplier = DEFAULT_PARTIAL_NODE_STABILITY_MULTIPLIER
        secondary_delta = 0.01
        secondary_stability_multiplier = 1.0
    else:
        return

    for node_id in primary_ids:
        state = node_lookup.get(node_id)
        if state is None:
            continue
        apply_delta_to_node_state(
            state,
            mastery_delta=primary_delta,
            stability_multiplier=primary_stability_multiplier,
            now=now,
            result=result,
        )

    for node_id in secondary_ids:
        state = node_lookup.get(node_id)
        if state is None:
            continue
        apply_delta_to_node_state(
            state,
            mastery_delta=secondary_delta,
            stability_multiplier=secondary_stability_multiplier,
            now=now,
            result=result,
        )


def apply_review_result(
    payload: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    result: str,
    now: datetime,
) -> dict[str, Any]:
    normalized_target_type = target_type.lower()
    normalized_result = result.lower()
    if normalized_result not in SUPPORTED_RESULTS:
        raise ValueError(f"Unsupported result: {result}")

    node_states = payload.get("knowledge_point_states", [])
    question_states = payload.get("example_question_states", [])
    node_lookup = build_node_lookup(node_states)
    question_lookup = build_question_lookup(question_states)

    if normalized_target_type == QUESTION_TARGET:
        question_state = question_lookup.get(target_id)
        if question_state is None:
            raise KeyError(f"Unknown question_id: {target_id}")
        apply_result_to_question_state(
            question_state,
            result=normalized_result,
            now=now,
        )
        propagate_question_result_to_nodes(
            question_state,
            node_lookup=node_lookup,
            result=normalized_result,
            now=now,
        )
    elif normalized_target_type == NODE_TARGET:
        node_state = node_lookup.get(target_id)
        if node_state is None:
            raise KeyError(f"Unknown node_id: {target_id}")
        if normalized_result == "correct":
            apply_delta_to_node_state(
                node_state,
                mastery_delta=DEFAULT_CORRECT_NODE_MASTERY_DELTA,
                stability_multiplier=DEFAULT_CORRECT_NODE_STABILITY_MULTIPLIER,
                now=now,
                result=normalized_result,
            )
        elif normalized_result == "wrong":
            apply_delta_to_node_state(
                node_state,
                mastery_delta=DEFAULT_WRONG_NODE_MASTERY_DELTA,
                stability_multiplier=DEFAULT_WRONG_NODE_STABILITY_MULTIPLIER,
                now=now,
                result=normalized_result,
            )
        elif normalized_result == "partial":
            apply_delta_to_node_state(
                node_state,
                mastery_delta=DEFAULT_PARTIAL_NODE_MASTERY_DELTA,
                stability_multiplier=DEFAULT_PARTIAL_NODE_STABILITY_MULTIPLIER,
                now=now,
                result=normalized_result,
            )
    else:
        raise ValueError(f"Unsupported target_type: {target_type}")

    return payload


def mark_important(
    payload: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
) -> dict[str, Any]:
    normalized_target_type = target_type.lower()
    if normalized_target_type == QUESTION_TARGET:
        lookup = build_question_lookup(payload.get("example_question_states", []))
        state = lookup.get(target_id)
        key = "question_id"
    elif normalized_target_type == NODE_TARGET:
        lookup = build_node_lookup(payload.get("knowledge_point_states", []))
        state = lookup.get(target_id)
        key = "node_id"
    else:
        raise ValueError(f"Unsupported target_type: {target_type}")

    if state is None:
        raise KeyError(f"Unknown {key}: {target_id}")

    current_bias = clamp(float(state.get("manual_priority_bias", 0.0) or 0.0), -0.5, 0.5)
    state["manual_priority_bias"] = safe_round(
        clamp(current_bias + DEFAULT_MARK_IMPORTANT_BIAS, -0.5, 0.5)
    )
    state["manual_skip_until"] = None
    return payload


def skip_temporarily(
    payload: dict[str, Any],
    *,
    target_type: str,
    target_id: str,
    now: datetime,
    skip_days: float = DEFAULT_SKIP_DAYS,
) -> dict[str, Any]:
    normalized_target_type = target_type.lower()
    if normalized_target_type == QUESTION_TARGET:
        lookup = build_question_lookup(payload.get("example_question_states", []))
        state = lookup.get(target_id)
        key = "question_id"
    elif normalized_target_type == NODE_TARGET:
        lookup = build_node_lookup(payload.get("knowledge_point_states", []))
        state = lookup.get(target_id)
        key = "node_id"
    else:
        raise ValueError(f"Unsupported target_type: {target_type}")

    if state is None:
        raise KeyError(f"Unknown {key}: {target_id}")

    state["manual_skip_until"] = (now + timedelta(days=skip_days)).isoformat()
    return payload


def node_mastered_well(
    payload: dict[str, Any],
    *,
    target_id: str,
    now: datetime,
) -> dict[str, Any]:
    node_lookup = build_node_lookup(payload.get("knowledge_point_states", []))
    node_state = node_lookup.get(target_id)
    if node_state is None:
        raise KeyError(f"Unknown node_id: {target_id}")

    apply_delta_to_node_state(
        node_state,
        mastery_delta=DEFAULT_NODE_MASTERED_WELL_MASTERY_DELTA,
        stability_multiplier=DEFAULT_NODE_MASTERED_WELL_STABILITY_MULTIPLIER,
        now=now,
        result="correct",
    )
    node_state["priority_note"] = "学生反馈：该知识点掌握很熟练，可后移复习。"
    set_session_priority(
        node_state,
        boost=DEFAULT_NODE_MASTERED_SESSION_REDUCE,
        now=now,
        reason="学生反馈当前很熟练，本轮先后移",
    )
    return payload


def node_needs_more_practice(
    payload: dict[str, Any],
    *,
    target_id: str,
    now: datetime,
) -> dict[str, Any]:
    node_lookup = build_node_lookup(payload.get("knowledge_point_states", []))
    question_lookup = build_question_lookup(payload.get("example_question_states", []))
    node_state = node_lookup.get(target_id)
    if node_state is None:
        raise KeyError(f"Unknown node_id: {target_id}")

    apply_delta_to_node_state(
        node_state,
        mastery_delta=DEFAULT_NODE_NEEDS_MORE_PRACTICE_MASTERY_DELTA,
        stability_multiplier=DEFAULT_NODE_NEEDS_MORE_PRACTICE_STABILITY_MULTIPLIER,
        now=now,
        result="wrong",
    )
    node_state["priority_note"] = "学生反馈：知识点看懂但还需要继续练题。"
    set_session_priority(
        node_state,
        boost=DEFAULT_NODE_PRACTICE_SESSION_BOOST,
        now=now,
        reason="学生希望继续围绕该知识点练题",
    )
    node_state["next_review_at"] = now.isoformat()

    for question_id in normalize_str_list(node_state.get("linked_question_ids")):
        question_state = question_lookup.get(question_id)
        if question_state is None:
            continue
        current_bias = clamp(
            float(question_state.get("manual_priority_bias", 0.0) or 0.0),
            -0.5,
            0.5,
        )
        question_state["manual_priority_bias"] = safe_round(
            clamp(current_bias + DEFAULT_LINKED_QUESTION_PRACTICE_BIAS, -0.5, 0.5)
        )
        question_state["manual_skip_until"] = None
        question_state["priority_note"] = "关联知识点复习后，学生选择继续练题。"
        set_session_priority(
            question_state,
            boost=DEFAULT_NODE_PRACTICE_SESSION_BOOST,
            now=now,
            reason="关联知识点刚复习完，学生要求立刻继续练这类题",
        )
        current_state = normalize_text(question_state.get("state")) or "new"
        if current_state == "stable":
            question_state["state"] = "review"
        if normalize_text(question_state.get("last_result")) in (None, "correct", "unseen"):
            question_state["last_result"] = "partial"
        if parse_datetime(question_state.get("next_review_at")) is None or (
            parse_datetime(question_state.get("next_review_at")) and
            ensure_timezone(parse_datetime(question_state.get("next_review_at"))) > now
        ):
            question_state["next_review_at"] = now.isoformat()
    return payload


@dataclass(frozen=True)
class ReviewStateUpdateResult:
    action: str
    target_type: str
    target_id: str
    updated_payload: dict[str, Any]
    executed_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "executed_at": self.executed_at,
            "updated_payload": self.updated_payload,
        }


def apply_review_action(
    payload: dict[str, Any],
    *,
    action: str,
    target_type: str,
    target_id: str,
    result: str | None = None,
    now: datetime | None = None,
    skip_days: float = DEFAULT_SKIP_DAYS,
) -> ReviewStateUpdateResult:
    current_time = ensure_timezone(now or datetime.now(timezone.utc))
    normalized_action = action.lower()
    if normalized_action not in SUPPORTED_ACTIONS:
        raise ValueError(f"Unsupported action: {action}")

    if normalized_action == "review_result":
        if result is None:
            raise ValueError("result is required for review_result")
        updated = apply_review_result(
            payload,
            target_type=target_type,
            target_id=target_id,
            result=result,
            now=current_time,
        )
    elif normalized_action == "mark_important":
        updated = mark_important(
            payload,
            target_type=target_type,
            target_id=target_id,
        )
    elif normalized_action == "node_mastered_well":
        if target_type.lower() != NODE_TARGET:
            raise ValueError("node_mastered_well only supports knowledge_point")
        updated = node_mastered_well(
            payload,
            target_id=target_id,
            now=current_time,
        )
    elif normalized_action == "node_needs_more_practice":
        if target_type.lower() != NODE_TARGET:
            raise ValueError("node_needs_more_practice only supports knowledge_point")
        updated = node_needs_more_practice(
            payload,
            target_id=target_id,
            now=current_time,
        )
    else:
        updated = skip_temporarily(
            payload,
            target_type=target_type,
            target_id=target_id,
            now=current_time,
            skip_days=skip_days,
        )

    return ReviewStateUpdateResult(
        action=normalized_action,
        target_type=target_type,
        target_id=target_id,
        updated_payload=updated,
        executed_at=current_time.isoformat(),
    )


def load_review_state(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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
        "--action",
        choices=sorted(SUPPORTED_ACTIONS),
        required=True,
        help="Action to apply",
    )
    parser.add_argument(
        "--target-type",
        choices=[QUESTION_TARGET, NODE_TARGET],
        required=True,
    )
    parser.add_argument("--target-id", required=True)
    parser.add_argument(
        "--result",
        choices=sorted(SUPPORTED_RESULTS),
        help="Result for review_result action",
    )
    parser.add_argument("--skip-days", type=float, default=DEFAULT_SKIP_DAYS)
    parser.add_argument("--now", help="Optional ISO-8601 timestamp")
    parser.add_argument("--out-json", help="Optional output file")
    args = parser.parse_args()

    payload = load_review_state(Path(args.review_state))
    result = apply_review_action(
        payload,
        action=args.action,
        target_type=args.target_type,
        target_id=args.target_id,
        result=args.result,
        now=now_from_value(args.now),
        skip_days=max(args.skip_days, 0.25),
    )

    output = result.as_dict()
    if args.out_json:
        write_json(Path(args.out_json), output)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

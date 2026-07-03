from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EARLY_OBSERVATION_STAGE = "early_observation"
FORMING_PATTERN_STAGE = "forming_pattern"
DEFAULT_MAX_MEMORY_NODE_BOOST = 0.18
DEFAULT_MAX_MEMORY_QUESTION_BOOST = 0.2


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_round(value: float, digits: int = 4) -> float:
    return round(float(value), digits)


def build_memory_node_lookup(
    student_memory_profile: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(student_memory_profile, dict):
        return {}
    return {
        item["node_id"]: item
        for item in student_memory_profile.get("node_memories", [])
        if isinstance(item, dict) and "node_id" in item
    }


def build_memory_question_lookup(
    student_memory_profile: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(student_memory_profile, dict):
        return {}
    return {
        item["question_id"]: item
        for item in student_memory_profile.get("question_memories", [])
        if isinstance(item, dict) and "question_id" in item
    }


def get_personalization_summary(
    student_memory_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(student_memory_profile, dict):
        return {}
    summary = student_memory_profile.get("personalization_summary")
    return summary if isinstance(summary, dict) else {}


@dataclass(frozen=True)
class CoachMemoryRule:
    memory_stage: str
    dominant_error_type: str
    dominant_signal_strength: str
    recommended_teaching_mode: str
    recommended_review_mode: str
    top_node_title: str | None
    note_lines: list[str]
    context_text: str
    strategy_note: str


def build_coach_memory_rule(
    student_memory_profile: dict[str, Any] | None,
) -> CoachMemoryRule:
    summary = get_personalization_summary(student_memory_profile)
    if not summary:
        return CoachMemoryRule(
            memory_stage=EARLY_OBSERVATION_STAGE,
            dominant_error_type="unknown",
            dominant_signal_strength="unknown",
            recommended_teaching_mode="balanced",
            recommended_review_mode="mixed",
            top_node_title=None,
            note_lines=[],
            context_text="",
            strategy_note="",
        )

    memory_stage = str(summary.get("memory_stage") or EARLY_OBSERVATION_STAGE)
    stage_text = (
        "初步观察"
        if memory_stage == EARLY_OBSERVATION_STAGE
        else "已形成一定模式"
    )
    dominant_error_type = str(summary.get("dominant_error_type") or "unknown")
    dominant_signal_strength = str(
        summary.get("dominant_error_signal_strength") or "unknown"
    )
    recommended_teaching_mode = str(
        summary.get("recommended_teaching_mode") or "balanced"
    )
    recommended_review_mode = str(
        summary.get("recommended_review_mode") or "mixed"
    )
    notes = summary.get("notes") if isinstance(summary.get("notes"), list) else []
    top_nodes = (
        summary.get("top_recurrent_nodes")
        if isinstance(summary.get("top_recurrent_nodes"), list)
        else []
    )
    top_node_title: str | None = None
    if top_nodes:
        first_node = top_nodes[0]
        if isinstance(first_node, dict):
            top_node_title = normalize_text(
                first_node.get("title") or first_node.get("node_id")
            )

    context_lines = [
        f"记忆阶段：{stage_text}",
        f"长期主错因：{dominant_error_type}",
        f"长期信号强度：{dominant_signal_strength}",
        f"长期教学偏好：{recommended_teaching_mode}",
        f"长期复习偏好：{recommended_review_mode}",
    ]
    if top_node_title:
        context_lines.append(f"当前最常卡叶子：{top_node_title}")
    note_lines = [str(item).strip() for item in notes[:2] if str(item).strip()]
    if note_lines:
        context_lines.append("辅助备注：" + " ".join(note_lines))
    context_text = "\n".join(context_lines)

    prefix = (
        "可轻度参考长期观察："
        if memory_stage == EARLY_OBSERVATION_STAGE
        else "结合长期画像："
    )
    note_map = {
        "concept_first": "优先先讲清概念、定义或判定依据，再回到当前题。",
        "strategy_first": "优先先点出中间目标和解题路线，不要只给局部结论。",
        "condition_first": "优先先让学生回到题干条件和求解目标，再推进当前题。",
        "checklist_first": "讲完关键步骤后，再补一句最短的检查方法。",
    }
    strategy_note_text = note_map.get(recommended_teaching_mode, "")
    strategy_note = prefix + strategy_note_text if strategy_note_text else ""

    return CoachMemoryRule(
        memory_stage=memory_stage,
        dominant_error_type=dominant_error_type,
        dominant_signal_strength=dominant_signal_strength,
        recommended_teaching_mode=recommended_teaching_mode,
        recommended_review_mode=recommended_review_mode,
        top_node_title=top_node_title,
        note_lines=note_lines,
        context_text=context_text,
        strategy_note=strategy_note,
    )


@dataclass(frozen=True)
class ReviewMemoryBias:
    boost: float
    reason: str | None
    signal_strength: str | None
    intervention: str | None


def compute_node_memory_priority_boost(
    node_id: str,
    student_memory_lookup: dict[str, dict[str, Any]],
) -> ReviewMemoryBias:
    memory = student_memory_lookup.get(node_id)
    if memory is None:
        return ReviewMemoryBias(0.0, None, None, None)
    observed_wrong = max(int(memory.get("observed_wrong_count", 0) or 0), 0)
    review_wrong = max(int(memory.get("review_wrong_count", 0) or 0), 0)
    practice_request_count = max(int(memory.get("practice_request_count", 0) or 0), 0)
    signal_strength = normalize_text(memory.get("signal_strength")) or None
    recommended_intervention = (
        normalize_text(memory.get("recommended_intervention")) or None
    )

    boost = 0.03 * observed_wrong + 0.02 * review_wrong + 0.015 * practice_request_count
    if signal_strength == "tentative":
        boost += 0.03
    elif signal_strength == "established":
        boost += 0.07
    if recommended_intervention in {"reteach_concept", "show_strategy_first"}:
        boost += 0.03

    boost = clamp(boost, 0.0, DEFAULT_MAX_MEMORY_NODE_BOOST)
    if boost <= 0:
        return ReviewMemoryBias(0.0, None, signal_strength, recommended_intervention)
    return ReviewMemoryBias(
        safe_round(boost),
        "学生长期记忆显示该知识点近期反复卡住，复习时轻度前移。",
        signal_strength,
        recommended_intervention,
    )


def compute_question_memory_priority_boost(
    question_id: str,
    student_memory_lookup: dict[str, dict[str, Any]],
) -> ReviewMemoryBias:
    memory = student_memory_lookup.get(question_id)
    if memory is None:
        return ReviewMemoryBias(0.0, None, None, None)
    wrong_count = max(int(memory.get("wrong_count", 0) or 0), 0)
    review_count = max(int(memory.get("review_count", 0) or 0), 0)
    signal_strength = normalize_text(memory.get("signal_strength")) or None
    last_result = (normalize_text(memory.get("last_result")) or "unseen").lower()

    boost = 0.04 * wrong_count + 0.015 * min(review_count, 3)
    if signal_strength == "tentative":
        boost += 0.02
    elif signal_strength == "established":
        boost += 0.05
    if last_result == "wrong":
        boost += 0.03

    boost = clamp(boost, 0.0, DEFAULT_MAX_MEMORY_QUESTION_BOOST)
    if boost <= 0:
        return ReviewMemoryBias(0.0, None, signal_strength, None)
    return ReviewMemoryBias(
        safe_round(boost),
        "学生长期记忆显示这道题或同类题近期容易反复做错，复习时轻度前移。",
        signal_strength,
        None,
    )


__all__ = [
    "EARLY_OBSERVATION_STAGE",
    "FORMING_PATTERN_STAGE",
    "CoachMemoryRule",
    "ReviewMemoryBias",
    "build_coach_memory_rule",
    "build_memory_node_lookup",
    "build_memory_question_lookup",
    "compute_node_memory_priority_boost",
    "compute_question_memory_priority_boost",
    "get_personalization_summary",
    "normalize_text",
]

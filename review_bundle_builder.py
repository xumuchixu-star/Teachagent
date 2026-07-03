from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from review_scheduler import (
    DEFAULT_BUNDLE_LIMIT,
    DEFAULT_BUNDLE_QUESTION_LIMIT,
    KNOWLEDGE_REVIEW_MODE,
    MIXED_REVIEW_MODE,
    QUESTION_REVIEW_MODE,
    build_review_schedule,
    load_review_state,
    now_from_value,
)


ROOT = Path(__file__).resolve().parent
LEAF_CARD_GLOB = ROOT / "docs" / "rag_samples" / "*leaf_cards.jsonl"
DEFAULT_EXAMPLE_MD_PATH = ROOT / "docs" / "rag_samples" / "taizhou_simulated_exam_examples_batch_01.md"


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def split_question_sections(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"^##\s+([A-Za-z0-9_]+)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(text))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        question_id = match.group(1)
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((question_id, text[start:end].strip()))
    return sections


def extract_field(block: str, label: str) -> str:
    pattern = re.compile(rf"- {re.escape(label)}：\n(.*?)(?=\n- [^\n]+：|\Z)", re.DOTALL)
    match = pattern.search(block)
    if not match:
        return ""
    return match.group(1).strip()


def load_example_map(path: Path) -> dict[str, dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    mapping: dict[str, dict[str, Any]] = {}
    for question_id, block in split_question_sections(text):
        mapping[question_id] = {
            "stem": extract_field(block, "题目"),
            "question_type": extract_field(block, "题型"),
            "correct_answer": extract_field(block, "标准答案"),
            "solution_text": extract_field(block, "参考解析"),
        }
    return mapping


def load_leaf_card_lookup() -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(ROOT.glob(str(LEAF_CARD_GLOB.relative_to(ROOT)))):
        with path.open(encoding="utf-8") as fp:
            for line in fp:
                text = line.strip()
                if not text:
                    continue
                row = json.loads(text)
                lookup.setdefault(row["node_id"], []).append(row)
    for node_id, rows in lookup.items():
        rows.sort(
            key=lambda row: (
                0 if row.get("is_primary") else 1,
                str(row.get("card_type") or ""),
                str(row.get("chunk_id") or ""),
            )
        )
    return lookup


def best_leaf_card(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    return rows[0] if rows else None


def question_payload_for_id(
    *,
    question_id: str,
    question_lookup: dict[str, dict[str, Any]],
    example_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    question_state = question_lookup.get(question_id) or {}
    payload = question_state.get("question_payload")
    if isinstance(payload, dict) and payload:
        return payload
    return example_map.get(question_id, {})


def build_leaf_card_view(card: dict[str, Any] | None) -> dict[str, Any] | None:
    if card is None:
        return None
    return {
        "chunk_id": card.get("chunk_id"),
        "node_id": card.get("node_id"),
        "title": card.get("title"),
        "card_type": card.get("card_type"),
        "node_kind": card.get("node_kind"),
        "path": card.get("path") or [],
        "keywords": card.get("keywords") or [],
        "text": card.get("text"),
        "review_cue": card.get("review_cue"),
        "structured_content": {
            "definition": card.get("definition"),
            "core_idea": card.get("core_idea"),
            "boundary": card.get("boundary"),
            "formula": card.get("formula"),
            "variable_notes": card.get("variable_notes"),
            "applicable_conditions": card.get("applicable_conditions"),
            "special_cases": card.get("special_cases"),
            "method_goal": card.get("method_goal"),
            "trigger_signals": card.get("trigger_signals"),
            "steps": card.get("steps"),
            "common_errors": card.get("common_errors"),
            "failure_modes": card.get("failure_modes"),
        },
        "student_actions": [
            {
                "label": "掌握很熟练",
                "action": "node_mastered_well",
                "target_type": "knowledge_point",
                "target_id": card.get("node_id"),
                "effect": "延后该知识点的下次复习时间",
            },
            {
                "label": "还要练题",
                "action": "node_needs_more_practice",
                "target_type": "knowledge_point",
                "target_id": card.get("node_id"),
                "effect": "提高该知识点关联题目的练习优先级",
            },
            {
                "label": "暂时跳过",
                "action": "skip_temporarily",
                "target_type": "knowledge_point",
                "target_id": card.get("node_id"),
                "effect": "短期内不再推送这个知识点",
            },
        ],
    }


def build_question_view(
    *,
    question_id: str,
    question_priority: dict[str, Any] | None,
    question_state: dict[str, Any] | None,
    question_payload: dict[str, Any],
) -> dict[str, Any]:
    fallback_last_result = None
    if isinstance(question_state, dict):
        fallback_last_result = normalize_text(question_state.get("last_result")) or "unseen"
    return {
        "question_id": question_id,
        "summary": {
            "question_type": question_payload.get("question_type"),
            "priority_score": question_priority.get("priority_score") if question_priority else None,
            "last_result": (
                question_priority.get("last_result")
                if question_priority
                else fallback_last_result
            ),
            "is_due_now": question_priority.get("is_due_now") if question_priority else None,
        },
        "content": {
            "stem": question_payload.get("stem"),
            "student_answer": question_payload.get("student_answer"),
        },
        "hidden_answer_block": {
            "revealed": False,
            "correct_answer": question_payload.get("correct_answer"),
            "solution_text": question_payload.get("solution_text"),
        },
        "student_actions": [
            {
                "label": "显示答案",
                "action": "reveal_answer",
                "target_type": "wrong_question",
                "target_id": question_id,
            },
            {
                "label": "这题做对了",
                "action": "review_result",
                "target_type": "wrong_question",
                "target_id": question_id,
                "result": "correct",
            },
            {
                "label": "这题没做对",
                "action": "review_result",
                "target_type": "wrong_question",
                "target_id": question_id,
                "result": "wrong",
            },
            {
                "label": "部分会做",
                "action": "review_result",
                "target_type": "wrong_question",
                "target_id": question_id,
                "result": "partial",
            },
            {
                "label": "先跳过",
                "action": "skip_temporarily",
                "target_type": "wrong_question",
                "target_id": question_id,
            },
        ],
    }


def build_bundle_reason(node_priority: dict[str, Any], question_ids: list[str]) -> str:
    if node_priority.get("is_due_now"):
        base = "知识点已到复习时间"
    else:
        base = "知识点接近复习时间"
    if question_ids:
        return f"{base}，并联动 {len(question_ids)} 道练习题一起复习"
    return f"{base}，当前先只展示知识点卡片"


def build_question_bundle_reason(question_priority: dict[str, Any], node_ids: list[str]) -> str:
    if question_priority.get("is_due_now"):
        base = "这道题已到复习时间"
    else:
        base = "这道题接近复习时间"
    if node_ids:
        return f"{base}，并附带 {len(node_ids)} 个关联知识点卡片"
    return f"{base}，当前没有补充知识点卡片"


@dataclass(frozen=True)
class ReviewBundleResult:
    generated_at: str
    review_state_record_id: str | None
    review_plan: dict[str, Any]
    review_bundles: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "review_state_record_id": self.review_state_record_id,
            "review_plan": self.review_plan,
            "review_bundles": self.review_bundles,
        }


def build_review_bundles(
    review_state: dict[str, Any],
    *,
    example_map: dict[str, dict[str, Any]],
    leaf_card_lookup: dict[str, list[dict[str, Any]]],
    now: datetime | None = None,
    mode: str | None = None,
    bundle_limit: int = DEFAULT_BUNDLE_LIMIT,
    bundle_question_limit: int = DEFAULT_BUNDLE_QUESTION_LIMIT,
    student_memory_profile: dict[str, Any] | None = None,
) -> ReviewBundleResult:
    question_state_count = len(
        [
            item
            for item in review_state.get("example_question_states", [])
            if isinstance(item, dict) and "question_id" in item
        ]
    )
    schedule = build_review_schedule(
        review_state,
        now=now,
        user_mode=mode,
        node_limit=max(bundle_limit, 1),
        question_limit=max(question_state_count, bundle_limit, 1),
        bundle_limit=max(bundle_limit, 1),
        bundle_question_limit=max(bundle_question_limit, 1),
        student_memory_profile=student_memory_profile,
    )

    node_priority_lookup = {
        item["node_id"]: item for item in schedule.node_priorities
    }
    question_priority_lookup = {
        item["question_id"]: item for item in schedule.question_priorities
    }
    question_state_lookup = {
        item["question_id"]: item
        for item in review_state.get("example_question_states", [])
        if isinstance(item, dict) and "question_id" in item
    }

    review_bundles: list[dict[str, Any]] = []
    selected_mode = schedule.review_plan.get("mode")
    if selected_mode == QUESTION_REVIEW_MODE:
        for rank, question_priority in enumerate(schedule.question_priorities[:bundle_limit], start=1):
            question_id = question_priority["question_id"]
            linked_node_ids = normalize_str_list(question_priority.get("primary_node_ids")) or normalize_str_list(
                question_priority.get("linked_node_ids")
            )
            linked_node_ids = linked_node_ids[:2]
            linked_cards = [
                build_leaf_card_view(best_leaf_card(leaf_card_lookup.get(node_id, [])))
                for node_id in linked_node_ids
            ]
            linked_cards = [item for item in linked_cards if item is not None]
            review_bundles.append(
                {
                    "bundle_id": f"bundle_{rank:02d}",
                    "mode": QUESTION_REVIEW_MODE,
                    "rank": rank,
                    "question_id": question_id,
                    "priority_score": question_priority.get("priority_score"),
                    "bundle_reason": build_question_bundle_reason(question_priority, linked_node_ids),
                    "question": build_question_view(
                        question_id=question_id,
                        question_priority=question_priority,
                        question_state=question_state_lookup.get(question_id),
                        question_payload=question_payload_for_id(
                            question_id=question_id,
                            question_lookup=question_state_lookup,
                            example_map=example_map,
                        ),
                    ),
                    "linked_leaf_cards": linked_cards,
                }
            )
    else:
        for rank, bundle in enumerate(schedule.review_plan.get("recommended_bundles", []), start=1):
            node_id = bundle["node_id"]
            node_priority = node_priority_lookup.get(node_id, {})
            card = best_leaf_card(leaf_card_lookup.get(node_id, []))
            question_views: list[dict[str, Any]] = []
            for question_id in bundle.get("question_ids", []):
                question_views.append(
                    build_question_view(
                        question_id=question_id,
                        question_priority=question_priority_lookup.get(question_id),
                        question_state=question_state_lookup.get(question_id),
                        question_payload=question_payload_for_id(
                            question_id=question_id,
                            question_lookup=question_state_lookup,
                            example_map=example_map,
                        ),
                    )
                )

            review_bundles.append(
                {
                    "bundle_id": f"bundle_{rank:02d}",
                    "mode": KNOWLEDGE_REVIEW_MODE,
                    "rank": rank,
                    "node_id": node_id,
                    "priority_score": node_priority.get("priority_score"),
                    "bundle_reason": build_bundle_reason(node_priority, bundle.get("question_ids", [])),
                    "leaf_card": build_leaf_card_view(card),
                    "question_count": len(question_views),
                    "questions": question_views,
                }
            )

    return ReviewBundleResult(
        generated_at=schedule.now,
        review_state_record_id=normalize_text(review_state.get("record_id")),
        review_plan=schedule.review_plan,
        review_bundles=review_bundles,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--review-state",
        required=True,
        help="Path to review state JSON",
    )
    parser.add_argument(
        "--out-json",
        required=True,
        help="Output bundled review JSON path",
    )
    parser.add_argument(
        "--mode",
        choices=[QUESTION_REVIEW_MODE, KNOWLEDGE_REVIEW_MODE, MIXED_REVIEW_MODE],
        default=KNOWLEDGE_REVIEW_MODE,
    )
    parser.add_argument(
        "--examples-md",
        default=str(DEFAULT_EXAMPLE_MD_PATH),
    )
    parser.add_argument("--bundle-limit", type=int, default=DEFAULT_BUNDLE_LIMIT)
    parser.add_argument("--bundle-question-limit", type=int, default=DEFAULT_BUNDLE_QUESTION_LIMIT)
    parser.add_argument("--now", help="Optional ISO-8601 timestamp")
    args = parser.parse_args()

    review_state = load_review_state(Path(args.review_state))
    example_map = load_example_map(Path(args.examples_md))
    leaf_card_lookup = load_leaf_card_lookup()
    result = build_review_bundles(
        review_state,
        example_map=example_map,
        leaf_card_lookup=leaf_card_lookup,
        now=now_from_value(args.now),
        mode=args.mode,
        bundle_limit=max(args.bundle_limit, 1),
        bundle_question_limit=max(args.bundle_question_limit, 1),
    )
    write_json(Path(args.out_json), result.as_dict())


if __name__ == "__main__":
    main()

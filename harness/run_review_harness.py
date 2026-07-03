from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from harness.common import (
    FIXTURES_ROOT,
    REPORTS_ROOT,
    build_case_result,
    build_failure_diagnostic,
    build_score_payload,
    build_suite_score,
    load_json,
    now_iso,
    rank_of_id,
    write_json,
)
from review_bundle_builder import build_review_bundles, load_example_map, load_leaf_card_lookup
from review_scheduler import now_from_value
from review_state_manager import apply_review_action


DEFAULT_FIXTURE_DIR = FIXTURES_ROOT / "review_flow"
DEFAULT_REPORT_PATH = REPORTS_ROOT / "review_flow_report.json"
DEFAULT_EXAMPLES_MD_PATH = ROOT / "docs" / "rag_samples" / "taizhou_simulated_exam_examples_batch_01.md"
DEFAULT_NOW = "2026-06-22T10:00:00+08:00"


def bundle_node_ids(bundle_payload: dict[str, Any]) -> list[str]:
    return [item["node_id"] for item in bundle_payload.get("review_bundles", []) if item.get("mode") == "leaf_first"]


def bundle_question_ids(bundle_payload: dict[str, Any]) -> list[str]:
    question_ids: list[str] = []
    for item in bundle_payload.get("review_bundles", []):
        if item.get("mode") == "question_first" and isinstance(item.get("question"), dict):
            question_id = item["question"].get("question_id")
            if question_id:
                question_ids.append(question_id)
    return question_ids


def resolve_target_id(
    *,
    step: dict[str, Any],
    captured_targets: dict[str, str],
) -> str:
    explicit = step.get("target_id")
    if explicit:
        return str(explicit)
    target_source = step.get("target_source")
    if target_source and target_source in captured_targets:
        return captured_targets[target_source]
    raise KeyError(f"could not resolve target id from step: {step}")


def evaluate_case(
    case: dict[str, Any],
    *,
    bundle_history: list[dict[str, Any]],
    captured_targets: dict[str, str],
) -> dict[str, Any]:
    expectation = case.get("expectation") or {}
    failed_expectations: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    rubric_items: list[dict[str, Any]] = []
    earned_points = 0.0
    total_points = 0.0

    initial_bundle = bundle_history[0] if bundle_history else {}
    final_bundle = bundle_history[-1] if bundle_history else {}

    before_top_nodes = bundle_node_ids(initial_bundle)
    after_top_nodes = bundle_node_ids(final_bundle)
    before_top_questions = bundle_question_ids(initial_bundle)
    after_top_questions = bundle_question_ids(final_bundle)

    first_node_id = captured_targets.get("first_bundle_node")
    first_question_id = captured_targets.get("first_bundle_question")

    if "first_node_should_remain_within_top_n" in expectation:
        limit = int(expectation["first_node_should_remain_within_top_n"])
        total_points += 1.0
        rank = rank_of_id(
            [{"node_id": node_id} for node_id in after_top_nodes],
            key="node_id",
            value=str(first_node_id),
        )
        if rank is None or rank > limit:
            failure_code = "first_node_did_not_remain_within_top_n"
            failed_expectations.append(failure_code)
            diagnostics.append(
                build_failure_diagnostic(
                    failure_code=failure_code,
                    layer="review.bundle_ranking",
                    message="知识点在动作后没有继续留在预期的前列位置。",
                    inspect_fields=["before_top_nodes", "after_top_nodes", "action_history"],
                    suggested_next_step="先检查 apply_review_action 是否正确写回状态，再看 bundle 排序有没有把 session boost 吃掉。",
                    actual={"rank": rank, "after_top_nodes": after_top_nodes},
                    expected={"max_rank": limit, "node_id": first_node_id},
                )
            )
            passed = False
        else:
            earned_points += 1.0
            passed = True
        rubric_items.append(
            {
                "metric": "first_node_remains_within_top_n",
                "weight": 1.0,
                "passed": passed,
                "actual": {"rank": rank, "node_id": first_node_id},
                "expected": {"max_rank": limit},
            }
        )

    if "first_node_should_drop_out_of_top_n" in expectation:
        limit = int(expectation["first_node_should_drop_out_of_top_n"])
        total_points += 1.0
        rank = rank_of_id(
            [{"node_id": node_id} for node_id in after_top_nodes],
            key="node_id",
            value=str(first_node_id),
        )
        if rank is not None and rank <= limit:
            failure_code = "first_node_did_not_drop_out_of_top_n"
            failed_expectations.append(failure_code)
            diagnostics.append(
                build_failure_diagnostic(
                    failure_code=failure_code,
                    layer="review.bundle_ranking",
                    message="知识点在标记为熟练后仍停留在顶部，没有后移。",
                    inspect_fields=["before_top_nodes", "after_top_nodes", "action_history"],
                    suggested_next_step="先查知识点状态是否更新为后移，再查 scheduler/bundle builder 是否正确消费后移信号。",
                    actual={"rank": rank, "after_top_nodes": after_top_nodes},
                    expected={"min_rank_exclusive": limit, "node_id": first_node_id},
                )
            )
            passed = False
        else:
            earned_points += 1.0
            passed = True
        rubric_items.append(
            {
                "metric": "first_node_drops_out_of_top_n",
                "weight": 1.0,
                "passed": passed,
                "actual": {"rank": rank, "node_id": first_node_id},
                "expected": {"min_rank_exclusive": limit},
            }
        )

    if "first_question_should_remain_within_top_n" in expectation:
        limit = int(expectation["first_question_should_remain_within_top_n"])
        total_points += 1.0
        rank = rank_of_id(
            [{"question_id": question_id} for question_id in after_top_questions],
            key="question_id",
            value=str(first_question_id),
        )
        if rank is None or rank > limit:
            failure_code = "first_question_did_not_remain_within_top_n"
            failed_expectations.append(failure_code)
            diagnostics.append(
                build_failure_diagnostic(
                    failure_code=failure_code,
                    layer="review.question_requeue",
                    message="题目做错后没有保持在高优先级位置。",
                    inspect_fields=["before_top_questions", "after_top_questions", "action_history"],
                    suggested_next_step="先看 wrong_question 状态更新，再看 question_first 模式下的重新入队排序。",
                    actual={"rank": rank, "after_top_questions": after_top_questions},
                    expected={"max_rank": limit, "question_id": first_question_id},
                )
            )
            passed = False
        else:
            earned_points += 1.0
            passed = True
        rubric_items.append(
            {
                "metric": "first_question_remains_within_top_n",
                "weight": 1.0,
                "passed": passed,
                "actual": {"rank": rank, "question_id": first_question_id},
                "expected": {"max_rank": limit},
            }
        )

    if "first_question_should_drop_out_of_top_n" in expectation:
        limit = int(expectation["first_question_should_drop_out_of_top_n"])
        total_points += 1.0
        rank = rank_of_id(
            [{"question_id": question_id} for question_id in after_top_questions],
            key="question_id",
            value=str(first_question_id),
        )
        if rank is not None and rank <= limit:
            failure_code = "first_question_did_not_drop_out_of_top_n"
            failed_expectations.append(failure_code)
            diagnostics.append(
                build_failure_diagnostic(
                    failure_code=failure_code,
                    layer="review.question_requeue",
                    message="题目答对后仍留在过高优先级，没有自然后移。",
                    inspect_fields=["before_top_questions", "after_top_questions", "action_history"],
                    suggested_next_step="先查答对后的 next_review_at / mastery 更新，再查 bundle 排序是否仍给它过强 boost。",
                    actual={"rank": rank, "after_top_questions": after_top_questions},
                    expected={"min_rank_exclusive": limit, "question_id": first_question_id},
                )
            )
            passed = False
        else:
            earned_points += 1.0
            passed = True
        rubric_items.append(
            {
                "metric": "first_question_drops_out_of_top_n",
                "weight": 1.0,
                "passed": passed,
                "actual": {"rank": rank, "question_id": first_question_id},
                "expected": {"min_rank_exclusive": limit},
            }
        )

    if "first_bundle_question_count_min" in expectation:
        minimum = int(expectation["first_bundle_question_count_min"])
        total_points += 1.0
        first_bundle = final_bundle.get("review_bundles", [{}])[0] if final_bundle.get("review_bundles") else {}
        question_count = int(first_bundle.get("question_count") or 0)
        if question_count < minimum:
            failure_code = "first_bundle_question_count_below_minimum"
            failed_expectations.append(failure_code)
            diagnostics.append(
                build_failure_diagnostic(
                    failure_code=failure_code,
                    layer="review.bundle_composition",
                    message="第一屏 bundle 里的配套题数量不足。",
                    inspect_fields=["after_top_nodes", "after_top_questions"],
                    suggested_next_step="先看 leaf 与 example 的关联是否断了，再看 bundle builder 的组装规则。",
                    actual={"question_count": question_count},
                    expected={"min_question_count": minimum},
                )
            )
            passed = False
        else:
            earned_points += 1.0
            passed = True
        rubric_items.append(
            {
                "metric": "first_bundle_question_count_min",
                "weight": 1.0,
                "passed": passed,
                "actual": {"question_count": question_count},
                "expected": {"min_question_count": minimum},
            }
        )

    details = {
        "expectation": expectation,
        "captured_targets": captured_targets,
        "before_top_nodes": before_top_nodes,
        "after_top_nodes": after_top_nodes,
        "before_top_questions": before_top_questions,
        "after_top_questions": after_top_questions,
    }
    return build_case_result(
        case_id=str(case["case_id"]),
        description=case.get("description"),
        passed=not failed_expectations,
        details=details,
        failed_expectations=failed_expectations,
        score=build_score_payload(
            earned_points=earned_points,
            total_points=total_points,
            rubric_items=rubric_items,
        ),
        diagnostics=diagnostics,
    )


def run_case(
    case: dict[str, Any],
    *,
    fixture_dir: Path,
    example_map: dict[str, dict[str, Any]],
    leaf_card_lookup: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    review_state_path = fixture_dir / str(case["review_state_fixture"])
    current_state = copy.deepcopy(load_json(review_state_path))
    current_time = now_from_value(case.get("now") or DEFAULT_NOW)
    mode = case["mode"]

    bundle_history: list[dict[str, Any]] = []
    action_history: list[dict[str, Any]] = []
    captured_targets: dict[str, str] = {}

    for step in case.get("steps", []):
        step_action = step["action"]
        if step_action == "build_bundle":
            bundle_result = build_review_bundles(
                current_state,
                example_map=example_map,
                leaf_card_lookup=leaf_card_lookup,
                now=current_time,
                mode=mode,
            )
            bundle_payload = bundle_result.as_dict()
            bundle_history.append(bundle_payload)
            review_bundles = bundle_payload.get("review_bundles", [])
            if review_bundles:
                first_bundle = review_bundles[0]
                if first_bundle.get("mode") == "leaf_first" and first_bundle.get("node_id"):
                    captured_targets.setdefault("first_bundle_node", first_bundle["node_id"])
                if (
                    first_bundle.get("mode") == "question_first"
                    and isinstance(first_bundle.get("question"), dict)
                    and first_bundle["question"].get("question_id")
                ):
                    captured_targets.setdefault(
                        "first_bundle_question",
                        first_bundle["question"]["question_id"],
                    )
        elif step_action == "review_action":
            target_id = resolve_target_id(
                step=step,
                captured_targets=captured_targets,
            )
            event = apply_review_action(
                current_state,
                action=step["review_action"],
                target_type=step["target_type"],
                target_id=target_id,
                result=step.get("result"),
                now=current_time,
            )
            current_state = event.updated_payload
            action_history.append(event.as_dict())
        else:
            raise ValueError(f"unsupported review harness step: {step_action}")

    case_report = evaluate_case(
        case,
        bundle_history=bundle_history,
        captured_targets=captured_targets,
    )
    case_report["fixture_path"] = str((fixture_dir / f"{case['case_id']}.json").relative_to(ROOT))
    case_report["details"]["action_history"] = action_history
    return case_report


def run_suite(
    *,
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    report_path: Path | None = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    example_map = load_example_map(DEFAULT_EXAMPLES_MD_PATH)
    leaf_card_lookup = load_leaf_card_lookup()

    case_reports: list[dict[str, Any]] = []
    for path in sorted(fixture_dir.glob("review_case_*.json")):
        case = load_json(path)
        case_report = run_case(
            case,
            fixture_dir=fixture_dir,
            example_map=example_map,
            leaf_card_lookup=leaf_card_lookup,
        )
        case_report["fixture_path"] = str(path.relative_to(ROOT))
        case_reports.append(case_report)

    passed_case_count = sum(1 for case in case_reports if case["passed"])
    failed_case_count = len(case_reports) - passed_case_count
    suite_report = {
        "generated_at": now_iso(),
        "suite_name": "review_flow",
        "fixture_dir": str(fixture_dir.relative_to(ROOT)),
        "passed_case_count": passed_case_count,
        "failed_case_count": failed_case_count,
        "score": build_suite_score(case_reports),
        "failure_flow": {
            "suite_layer": "review_flow",
            "when_failed_check_order": [
                "review.state_update",
                "review.question_requeue",
                "review.bundle_ranking",
                "review.bundle_composition",
            ],
            "note": "先看动作有没有正确写入状态，再看题/知识点是否重新排队，最后看 bundle 组装结果。",
        },
        "cases": case_reports,
    }
    if report_path is not None:
        write_json(report_path, suite_report)
    return suite_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fixture-dir",
        default=str(DEFAULT_FIXTURE_DIR),
    )
    parser.add_argument(
        "--out-json",
        default=str(DEFAULT_REPORT_PATH),
    )
    args = parser.parse_args()

    report = run_suite(
        fixture_dir=Path(args.fixture_dir),
        report_path=Path(args.out_json),
    )
    print(
        f"review_flow: passed={report['passed_case_count']} failed={report['failed_case_count']}"
    )
    if report["failed_case_count"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

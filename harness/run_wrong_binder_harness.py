from __future__ import annotations

import argparse
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
    write_json,
)
from wrong_question_binder import WrongQuestionBinder, summarize_result


DEFAULT_FIXTURE_DIR = FIXTURES_ROOT / "wrong_binder"
DEFAULT_REPORT_PATH = REPORTS_ROOT / "wrong_binder_report.json"
PRIMARY_WEIGHT = 0.15
TOP_K_WEIGHT = 0.65
COARSE_WEIGHT = 0.20


def evaluate_case(case: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    expectation = case.get("expectation") or {}
    failed_expectations: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    rubric_items: list[dict[str, Any]] = []
    earned_points = 0.0
    total_points = 0.0

    allowed_primary_node_ids = expectation.get("allowed_primary_node_ids") or []
    total_points += PRIMARY_WEIGHT
    if allowed_primary_node_ids:
        if summary["primary_node_id"] not in allowed_primary_node_ids:
            failure_code = "primary_node_id_not_in_allowed_set"
            failed_expectations.append(failure_code)
            diagnostics.append(
                build_failure_diagnostic(
                    failure_code=failure_code,
                    layer="binder.primary_selection",
                    message="主知识点没有落在允许集合内。",
                    inspect_fields=["primary_node_id", "top_k_node_ids", "coarse_subtrees"],
                    suggested_next_step="先看粗路由是否偏了，再看叶子排序规则是否把更细的叶子压下去了。",
                    actual=summary.get("primary_node_id"),
                    expected=allowed_primary_node_ids,
                )
            )
            passed = False
        else:
            earned_points += PRIMARY_WEIGHT
            passed = True
        rubric_items.append(
            {
                "metric": "primary_node_allowed",
                "weight": PRIMARY_WEIGHT,
                "passed": passed,
                "actual": summary.get("primary_node_id"),
                "expected": allowed_primary_node_ids,
            }
        )
    else:
        rubric_items.append(
            {
                "metric": "primary_node_allowed",
                "weight": PRIMARY_WEIGHT,
                "passed": True,
                "actual": summary.get("primary_node_id"),
                "expected": [],
                "note": "case 未配置 allowed_primary_node_ids，默认跳过此项。",
            }
        )

    must_hit_node_ids = expectation.get("must_hit_node_ids") or []
    must_hit_within_top_k = int(
        expectation.get("must_hit_within_top_k") or len(summary.get("top_k_node_ids") or [])
    )
    total_points += TOP_K_WEIGHT
    if must_hit_node_ids:
        top_k_slice = summary.get("top_k_node_ids", [])[:must_hit_within_top_k]
        missing = [node_id for node_id in must_hit_node_ids if node_id not in top_k_slice]
        if missing:
            failure_code = "missing_required_node_ids_within_top_k:" + ",".join(missing)
            failed_expectations.append(failure_code)
            diagnostics.append(
                build_failure_diagnostic(
                    failure_code="missing_required_node_ids_within_top_k",
                    layer="binder.top_k_recall",
                    message="预期知识点没有在要求的 top-k 范围内被召回。",
                    inspect_fields=["top_k_node_ids", "candidate_pool_size", "binding_confidence"],
                    suggested_next_step="优先检查候选池召回是否太窄，其次再看重排分数是否把目标叶子压低。",
                    actual=top_k_slice,
                    expected={
                        "must_hit_node_ids": must_hit_node_ids,
                        "must_hit_within_top_k": must_hit_within_top_k,
                    },
                )
            )
            passed = False
        else:
            earned_points += TOP_K_WEIGHT
            passed = True
        rubric_items.append(
            {
                "metric": "top_k_must_hit",
                "weight": TOP_K_WEIGHT,
                "passed": passed,
                "actual": top_k_slice,
                "expected": {
                    "must_hit_node_ids": must_hit_node_ids,
                    "must_hit_within_top_k": must_hit_within_top_k,
                },
            }
        )
    else:
        rubric_items.append(
            {
                "metric": "top_k_must_hit",
                "weight": TOP_K_WEIGHT,
                "passed": True,
                "actual": summary.get("top_k_node_ids", [])[:must_hit_within_top_k],
                "expected": [],
                "note": "case 未配置 must_hit_node_ids，默认跳过此项。",
            }
        )

    allowed_coarse_subtrees = expectation.get("allowed_coarse_subtrees") or []
    total_points += COARSE_WEIGHT
    if allowed_coarse_subtrees:
        coarse_subtrees = summary.get("coarse_subtrees") or []
        first_coarse = coarse_subtrees[0] if coarse_subtrees else None
        if first_coarse not in allowed_coarse_subtrees:
            failure_code = "top_coarse_subtree_not_allowed"
            failed_expectations.append(failure_code)
            diagnostics.append(
                build_failure_diagnostic(
                    failure_code=failure_code,
                    layer="binder.coarse_routing",
                    message="粗路由的第一子树方向不对。",
                    inspect_fields=["coarse_subtrees", "primary_node_id", "top_k_node_ids"],
                    suggested_next_step="先改粗粒度子树路由，再谈叶子层排序，否则后面的精排空间不够。",
                    actual=first_coarse,
                    expected=allowed_coarse_subtrees,
                )
            )
            passed = False
        else:
            earned_points += COARSE_WEIGHT
            passed = True
        rubric_items.append(
            {
                "metric": "coarse_subtree_allowed",
                "weight": COARSE_WEIGHT,
                "passed": passed,
                "actual": first_coarse,
                "expected": allowed_coarse_subtrees,
            }
        )
    else:
        rubric_items.append(
            {
                "metric": "coarse_subtree_allowed",
                "weight": COARSE_WEIGHT,
                "passed": True,
                "actual": (summary.get("coarse_subtrees") or [None])[0],
                "expected": [],
                "note": "case 未配置 allowed_coarse_subtrees，默认跳过此项。",
            }
        )

    details = {
        "summary": summary,
        "expectation": expectation,
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


def run_suite(
    *,
    fixture_dir: Path = DEFAULT_FIXTURE_DIR,
    report_path: Path | None = DEFAULT_REPORT_PATH,
) -> dict[str, Any]:
    binder = WrongQuestionBinder(enable_embeddings=False)
    case_reports: list[dict[str, Any]] = []
    for path in sorted(fixture_dir.glob("*.json")):
        case = load_json(path)
        payload = {
            "question_payload": case["question_payload"],
        }
        result = binder.bind(payload)
        summary = summarize_result(result)
        case_report = evaluate_case(case, summary)
        case_report["fixture_path"] = str(path.relative_to(ROOT))
        case_reports.append(case_report)

    passed_case_count = sum(1 for case in case_reports if case["passed"])
    failed_case_count = len(case_reports) - passed_case_count
    suite_report = {
        "generated_at": now_iso(),
        "suite_name": "wrong_binder",
        "fixture_dir": str(fixture_dir.relative_to(ROOT)),
        "passed_case_count": passed_case_count,
        "failed_case_count": failed_case_count,
        "score": build_suite_score(case_reports),
        "score_policy": {
            "primary_weight": PRIMARY_WEIGHT,
            "top_k_weight": TOP_K_WEIGHT,
            "coarse_weight": COARSE_WEIGHT,
            "note": "当前阶段以 top-k 召回为主，primary 只作为次级指标。",
        },
        "failure_flow": {
            "suite_layer": "wrong_question_binder",
            "when_failed_check_order": [
                "binder.coarse_routing",
                "binder.top_k_recall",
                "binder.primary_selection",
            ],
            "note": "先看大方向子树，再看候选召回，再看最终主知识点选择。",
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
        f"wrong_binder: passed={report['passed_case_count']} failed={report['failed_case_count']}"
    )
    if report["failed_case_count"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

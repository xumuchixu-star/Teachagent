from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from harness.common import REPORTS_ROOT, now_iso, write_json
from harness.common import rounded_score, safe_ratio
from harness.run_review_harness import run_suite as run_review_suite
from harness.run_wrong_binder_harness import run_suite as run_wrong_binder_suite


DEFAULT_REPORT_PATH = REPORTS_ROOT / "latest_report.json"
DEFAULT_REPORT_MD_PATH = REPORTS_ROOT / "latest_report.md"


def suite_purpose(suite_name: str) -> str:
    mapping = {
        "wrong_binder": "检查错题绑定是否还能把题目稳定路由到合理知识点。",
        "review_flow": "检查复习系统在学生点击按钮后，题目与知识点的前后顺序是否仍符合直觉。",
    }
    return mapping.get(suite_name, "当前 suite 未补充说明。")


def suite_checkpoints(suite_name: str) -> list[str]:
    mapping = {
        "wrong_binder": [
            "主知识点是否落在允许集合内",
            "目标叶子是否在要求的 top-k 内被召回",
            "粗路由的第一子树是否正确",
        ],
        "review_flow": [
            "知识点点击“还要练题”后是否继续靠前",
            "知识点点击“掌握很熟练”后是否后移",
            "题目答错后是否立即回炉",
            "题目答对后是否自然后移",
            "第一屏 bundle 的配套题数量是否足够",
        ],
    }
    return mapping.get(suite_name, [])


def format_score(score_payload: dict[str, Any] | None) -> str:
    score_payload = score_payload or {}
    return (
        f"{score_payload.get('earned_points', 0)} / {score_payload.get('total_points', 0)} "
        f"({score_payload.get('score_percent', 0)}%)"
    )


def render_case_markdown(case: dict[str, Any]) -> list[str]:
    lines = [
        f"### {case.get('case_id', 'unknown_case')}",
        f"- 说明：{case.get('description') or '无'}",
        f"- 结果：{'PASS' if case.get('passed') else 'FAIL'}",
        f"- 分数：{format_score(case.get('score'))}",
    ]
    failed_expectations = case.get("failed_expectations") or []
    if failed_expectations:
        lines.append(f"- 失败项：{', '.join(str(item) for item in failed_expectations)}")

    diagnostics = case.get("diagnostics") or []
    if diagnostics:
        lines.append("- 诊断：")
        for item in diagnostics:
            lines.append(
                "  - "
                f"[{item.get('layer', 'unknown_layer')}] "
                f"{item.get('message', '')} "
                f"下一步：{item.get('suggested_next_step', '')}"
            )
    return lines


def render_markdown_report(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "# TeachAgent Harness Report",
        "",
        "## Overall",
        f"- 生成时间：{report.get('generated_at')}",
        f"- Suite 数：{(report.get('summary') or {}).get('suite_count', 0)}",
        f"- Case 数：{(report.get('summary') or {}).get('case_count', 0)}",
        f"- 通过：{(report.get('summary') or {}).get('passed_case_count', 0)}",
        f"- 失败：{(report.get('summary') or {}).get('failed_case_count', 0)}",
        f"- 总分：{format_score(report.get('score'))}",
        "",
        "## Harness Parts",
    ]

    for suite in report.get("suites") or []:
        suite_name = str(suite.get("suite_name") or "unknown_suite")
        lines.extend(
            [
                "",
                f"## {suite_name}",
                f"- 作用：{suite_purpose(suite_name)}",
                f"- 当前分数：{format_score(suite.get('score'))}",
                f"- 当前通过：{suite.get('passed_case_count', 0)} / {len(suite.get('cases') or [])}",
            ]
        )

        checkpoints = suite_checkpoints(suite_name)
        if checkpoints:
            lines.append("- 主要检查点：")
            for item in checkpoints:
                lines.append(f"  - {item}")

        score_policy = suite.get("score_policy") or {}
        if score_policy:
            primary_weight = score_policy.get("primary_weight")
            top_k_weight = score_policy.get("top_k_weight")
            coarse_weight = score_policy.get("coarse_weight")
            if primary_weight is not None and top_k_weight is not None and coarse_weight is not None:
                lines.append(
                    "- 评分口径："
                    f" primary={primary_weight} | top-k={top_k_weight} | coarse={coarse_weight}"
                )
            note = score_policy.get("note")
            if note:
                lines.append(f"- 评分说明：{note}")

        failure_flow = suite.get("failure_flow") or {}
        order = failure_flow.get("when_failed_check_order") or []
        if order:
            lines.append(f"- 报错排查顺序：{' -> '.join(str(item) for item in order)}")
        note = failure_flow.get("note")
        if note:
            lines.append(f"- 排查说明：{note}")

        lines.append("")
        lines.append("### Cases")
        for case in suite.get("cases") or []:
            lines.extend(render_case_markdown(case))
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run_all(
    *,
    report_path: Path = DEFAULT_REPORT_PATH,
    report_md_path: Path = DEFAULT_REPORT_MD_PATH,
) -> dict:
    wrong_binder_report = run_wrong_binder_suite()
    review_report = run_review_suite()

    suites = [
        wrong_binder_report,
        review_report,
    ]
    summary = {
        "suite_count": len(suites),
        "case_count": sum(len(suite.get("cases", [])) for suite in suites),
        "passed_case_count": sum(int(suite.get("passed_case_count") or 0) for suite in suites),
        "failed_case_count": sum(int(suite.get("failed_case_count") or 0) for suite in suites),
    }
    earned_points = sum(float((suite.get("score") or {}).get("earned_points") or 0.0) for suite in suites)
    total_points = sum(float((suite.get("score") or {}).get("total_points") or 0.0) for suite in suites)
    report = {
        "generated_at": now_iso(),
        "summary": summary,
        "score": {
            "earned_points": rounded_score(earned_points),
            "total_points": rounded_score(total_points),
            "score_ratio": rounded_score(safe_ratio(earned_points, total_points)),
            "score_percent": round(safe_ratio(earned_points, total_points) * 100, 2),
        },
        "suites": suites,
    }
    write_json(report_path, report)
    report_md_path.parent.mkdir(parents=True, exist_ok=True)
    report_md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out-json",
        default=str(DEFAULT_REPORT_PATH),
    )
    parser.add_argument(
        "--out-md",
        default=str(DEFAULT_REPORT_MD_PATH),
    )
    args = parser.parse_args()

    report = run_all(
        report_path=Path(args.out_json),
        report_md_path=Path(args.out_md),
    )
    print(
        "all_harness:"
        f" suites={report['summary']['suite_count']}"
        f" cases={report['summary']['case_count']}"
        f" passed={report['summary']['passed_case_count']}"
        f" failed={report['summary']['failed_case_count']}"
    )
    if report["summary"]["failed_case_count"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

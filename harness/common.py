from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
HARNESS_ROOT = ROOT / "harness"
FIXTURES_ROOT = HARNESS_ROOT / "fixtures"
REPORTS_ROOT = HARNESS_ROOT / "reports"


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rank_of_id(items: list[dict[str, Any]], *, key: str, value: str) -> int | None:
    for index, item in enumerate(items, start=1):
        if str(item.get(key) or "") == value:
            return index
    return None


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def rounded_score(value: float) -> float:
    return round(float(value), 4)


def build_score_payload(
    *,
    earned_points: float,
    total_points: float,
    rubric_items: list[dict[str, Any]],
) -> dict[str, Any]:
    ratio = safe_ratio(earned_points, total_points)
    return {
        "earned_points": rounded_score(earned_points),
        "total_points": rounded_score(total_points),
        "score_ratio": rounded_score(ratio),
        "score_percent": round(ratio * 100, 2),
        "rubric_items": rubric_items,
    }


def build_failure_diagnostic(
    *,
    failure_code: str,
    layer: str,
    message: str,
    inspect_fields: list[str],
    suggested_next_step: str,
    actual: Any = None,
    expected: Any = None,
) -> dict[str, Any]:
    payload = {
        "failure_code": failure_code,
        "layer": layer,
        "message": message,
        "inspect_fields": inspect_fields,
        "suggested_next_step": suggested_next_step,
    }
    if actual is not None:
        payload["actual"] = actual
    if expected is not None:
        payload["expected"] = expected
    return payload


def build_suite_score(case_reports: list[dict[str, Any]]) -> dict[str, Any]:
    total_points = sum(float((case.get("score") or {}).get("total_points") or 0.0) for case in case_reports)
    earned_points = sum(float((case.get("score") or {}).get("earned_points") or 0.0) for case in case_reports)
    return {
        "earned_points": rounded_score(earned_points),
        "total_points": rounded_score(total_points),
        "score_ratio": rounded_score(safe_ratio(earned_points, total_points)),
        "score_percent": round(safe_ratio(earned_points, total_points) * 100, 2),
    }


def build_case_result(
    *,
    case_id: str,
    description: str | None,
    passed: bool,
    details: dict[str, Any],
    failed_expectations: list[str],
    score: dict[str, Any] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "description": description,
        "passed": passed,
        "failed_expectations": failed_expectations,
        "score": score or {},
        "diagnostics": diagnostics or [],
        "details": details,
    }

from __future__ import annotations

import argparse
import cgi
import copy
from datetime import datetime
import hashlib
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

def resolve_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


ROOT = resolve_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from review_bundle_builder import (
    DEFAULT_EXAMPLE_MD_PATH,
    build_review_bundles,
    load_example_map,
    load_leaf_card_lookup,
)
from review_scheduler import (
    KNOWLEDGE_REVIEW_MODE,
    MIXED_REVIEW_MODE,
    QUESTION_REVIEW_MODE,
    load_review_state,
    now_from_value,
)
from review_state_manager import apply_review_action
from diagnosis_agent import FoundryDiagnosisAgent, diagnosis_environment
from coach_agent import FoundryCoachAgent, diagnose_environment
from diagnosis_orchestrator import (
    FoundryDiagnosisOrchestrator,
    DiagnosisFlowSession,
    OrchestratorResult,
    orchestrator_environment,
)
from student_memory_events import (
    binding_result_to_memory_event,
    coach_response_to_memory_event,
    diagnosis_result_to_memory_event,
    review_state_update_to_memory_event,
    student_choice_to_memory_event,
)
from student_memory_store import append_event, build_profile_from_store
from student_memory_manager import build_profile, initialize_student_memory_profile
from teachagent_postgres_store import (
    TeachAgentPostgresStore,
    database_url_from_env,
    load_teachagent_env,
)

APP_ROOT = ROOT / "app"
STATIC_DIR = APP_ROOT / "static"
TREE_DATA_PATH = ROOT / "docs" / "rag_inventory" / "knowledge_tree_typed_full.json"
DEFAULT_STATE_PATH = (
    ROOT / "scratch" / "student_annotation_merged" / "student_annotation_merged_review_state.json"
)
DEFAULT_MEMORY_PROFILE_PATH = (
    ROOT / "scratch" / "teachagent_system_overview" / "student_memory_profile_demo.json"
)
SESSION_STATE_PATH = APP_ROOT / "data" / "review_state.session.json"
TREE_NOTEBOOK_PATH = APP_ROOT / "data" / "tree_notes.session.json"
TREE_CUSTOM_NODES_PATH = APP_ROOT / "data" / "tree_custom_nodes.session.json"
WRONGBOOK_CUSTOM_QUESTIONS_PATH = APP_ROOT / "data" / "wrongbook_custom_questions.session.json"
MEMORY_EVENTS_PATH = ROOT / "data" / "student_memory" / "student_memory_events.jsonl"
SESSION_MEMORY_PROFILE_PATH = APP_ROOT / "data" / "student_memory_profile.session.json"
STUDENT_DATA_ROOT = APP_ROOT / "data" / "students"
OCR_UPLOAD_DIR = ROOT / "scratch" / "ocr_uploads"
OCR_RUNS_DIR = ROOT / "scratch" / "mineru_runs"
MINERU_WRAPPER_PATH = ROOT / "scripts" / "run_mineru_extract.py"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".heic", ".heif"}
ANSWER_POLISH_MAX_TOKENS = int(os.getenv("ANSWER_POLISH_MAX_TOKENS", "520"))
ANSWER_MARKERS = ["【答案】", "答案：", "答案:", "Answer:"]
SOLUTION_MARKERS = ["【锤子数学解析】", "【解析】", "解析：", "解析:", "参考解析：", "参考解析:"]
COMBINED_ANSWER_SOLUTION_MARKERS = [
    "答案解析",
    "答案解析：",
    "答案解析:",
    "答案与解析",
    "答案与解析：",
    "答案与解析:",
    "参考答案与解析",
    "参考答案与解析：",
    "参考答案与解析:",
]
OCR_ROLE_LABELS = {
    "question": "题目",
    "answer": "答案",
    "solution": "解析",
    "answer_solution": "答案+解析",
    "mixed": "混合",
    "unknown": "未判断",
}
TRUTHY_TEXT = {"1", "true", "yes", "y", "on"}
FALSY_TEXT = {"0", "false", "no", "n", "off"}
DEFAULT_SERVER_HOST = "127.0.0.1"
DEFAULT_DEPLOY_HOST = "0.0.0.0"
DEFAULT_SERVER_PORT = 8765


def empty_review_state(*, student_id: str) -> dict[str, Any]:
    generated_at = datetime.now().astimezone().isoformat()
    return {
        "record_id": f"review_state.blank.{student_id}",
        "student_id": student_id,
        "generated_at": generated_at,
        "knowledge_point_states": [],
        "example_question_states": [],
        "review_plan": {},
        "notes": {},
    }
QUESTION_CUES = [
    "已知",
    "求",
    "若",
    "设",
    "下列",
    "函数",
    "方程",
    "数列",
    "不等式",
    "双曲线",
    "椭圆",
    "抛物线",
    "直线",
    "圆",
    "证明",
]
SOLUTION_LEAD_PATTERNS = [
    r"^(解|解析|证明|思路|点拨|分析|点评)[：:]",
    r"^故选[：: ]?",
    r"^故填[：: ]?",
    r"^答案[：: ]?",
    r"^由.*得",
]
SHORT_ANSWER_PATTERNS = [
    r"^[A-D](?:\s*[,，、/]\s*[A-D])*$",
    r"^(正确|错误|对|错)$",
    r"^[+-]?\d+(?:\.\d+)?$",
    r"^[+-]?\d+\s*/\s*\d+$",
]

ALLOWED_MODES = {
    KNOWLEDGE_REVIEW_MODE,
    QUESTION_REVIEW_MODE,
    MIXED_REVIEW_MODE,
}


def now_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def slugify_text(value: str) -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value.strip(), flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "upload"


def stable_question_id_from_text(prefix: str, text: str) -> str:
    normalized = re.sub(r"\s+", " ", str(text or "").strip())
    digest = hashlib.md5(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def strip_known_marker_prefix(text: str) -> str:
    stripped = strip_leading_structural_markup(text.strip())
    ordered_markers = sorted(
        [*COMBINED_ANSWER_SOLUTION_MARKERS, *ANSWER_MARKERS, *SOLUTION_MARKERS],
        key=len,
        reverse=True,
    )
    for marker in ordered_markers:
        if stripped.startswith(marker):
            return stripped[len(marker):].lstrip(" ：:\n")
    return stripped


def strip_leading_structural_markup(text: str) -> str:
    current = text.lstrip()
    while current:
        updated = current
        updated = re.sub(r"^#{1,6}\s*", "", updated, count=1)
        updated = re.sub(r"^>\s*", "", updated, count=1)
        updated = re.sub(r"^[-*+]\s+", "", updated, count=1)
        updated = re.sub(r"^\*{1,2}\s*", "", updated, count=1)
        updated = re.sub(r"^_{1,2}\s*", "", updated, count=1)
        updated = updated.lstrip()
        if updated == current:
            break
        current = updated
    return current


def first_clean_nonempty_line(text: str) -> str:
    for raw_line in text.splitlines():
        cleaned = strip_leading_structural_markup(raw_line).strip()
        if cleaned:
            return cleaned
    return ""


def detect_ocr_content_role(text: str, split_result: dict[str, Any]) -> dict[str, Any]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = strip_leading_structural_markup(normalized)
    first_line = first_clean_nonempty_line(normalized)
    question_text = str(split_result.get("question_text") or "").strip()
    answer_text = str(split_result.get("answer_text") or "").strip()
    solution_text = str(split_result.get("solution_text") or "").strip()

    has_question = bool(question_text)
    has_answer = bool(answer_text)
    has_solution = bool(solution_text)

    starts_with_combined_marker = any(
        first_line.startswith(marker) or cleaned.startswith(marker)
        for marker in COMBINED_ANSWER_SOLUTION_MARKERS
    )
    starts_with_answer_marker = any(
        first_line.startswith(marker) or cleaned.startswith(marker)
        for marker in ANSWER_MARKERS
    )
    starts_with_solution_marker = any(
        first_line.startswith(marker) or cleaned.startswith(marker)
        for marker in SOLUTION_MARKERS
    )
    starts_with_solution_pattern = any(
        re.match(pattern, first_line) or re.match(pattern, cleaned)
        for pattern in SOLUTION_LEAD_PATTERNS
    )
    short_answer_like = len(cleaned) <= 48 and any(
        re.fullmatch(pattern, cleaned)
        for pattern in SHORT_ANSWER_PATTERNS
    )
    question_cue_hits = sum(1 for cue in QUESTION_CUES if cue in cleaned[:240])

    role = "unknown"
    confidence = 0.45
    reasons: list[str] = []

    if starts_with_combined_marker:
        role = "answer_solution"
        confidence = 0.97
        reasons.append("开头命中“答案解析/答案与解析”类标题。")
    elif has_question and (has_answer or has_solution):
        role = "mixed"
        confidence = 0.88
        reasons.append("同一文件里同时识别出题干和答案/解析内容。")
    elif has_answer and has_solution:
        role = "answer_solution"
        confidence = 0.9
        reasons.append("已切出答案和解析两部分。")
    elif starts_with_solution_marker or starts_with_solution_pattern:
        role = "solution"
        confidence = 0.86
        reasons.append("开头更像解析讲解语气，例如“解：”“故选”“由…得”。")
    elif has_solution and not has_question:
        role = "solution"
        confidence = 0.83
        reasons.append("该文件只切出了解析内容，没有稳定题干。")
    elif starts_with_answer_marker:
        role = "answer"
        confidence = 0.84
        reasons.append("开头命中答案标记。")
    elif has_answer and not has_question and not has_solution:
        role = "answer"
        confidence = 0.8
        reasons.append("该文件只切出了答案内容，没有稳定题干。")
    elif short_answer_like:
        role = "answer"
        confidence = 0.74
        reasons.append("文本很短，形态更像选项或数值答案。")
    elif has_question and not has_answer and not has_solution:
        role = "question"
        confidence = 0.76
        reasons.append("该文件主要被识别为题干，没有切出答案或解析。")
    elif question_cue_hits >= 2:
        role = "question"
        confidence = 0.68
        reasons.append("命中多个题目常见提示词，例如“已知/求/设/下列”。")
    else:
        reasons.append("没有足够强的结构标记，建议人工确认。")

    return {
        "role": role,
        "role_label": OCR_ROLE_LABELS.get(role, role),
        "confidence": round(confidence, 4),
        "reasons": reasons,
    }


def has_meaningful_prefix_text(text: str) -> bool:
    return bool(strip_leading_structural_markup(text).strip())


def find_first_marker(text: str, markers: list[str]) -> tuple[int | None, str | None]:
    hits: list[tuple[int, str]] = []
    for marker in markers:
        index = text.find(marker)
        if index >= 0:
            hits.append((index, marker))
    if not hits:
        return None, None
    hits.sort(key=lambda item: item[0])
    return hits[0]


def split_ocr_preview_text(text: str) -> dict[str, Any]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    warnings: list[str] = []
    answer_count = sum(normalized.count(marker) for marker in ANSWER_MARKERS)
    question_number_count = len(re.findall(r"(?m)^\s*\d+[\.．、]", normalized))
    if answer_count > 1 or question_number_count > 1:
        warnings.append("检测到多题或多答案标记，建议裁剪成单题后再导入。")

    combined_index, _ = find_first_marker(normalized, COMBINED_ANSWER_SOLUTION_MARKERS)
    answer_index, _ = find_first_marker(normalized, ANSWER_MARKERS)
    solution_index, _ = find_first_marker(normalized, SOLUTION_MARKERS)

    question_text = normalized
    answer_text = ""
    solution_text = ""
    saw_structured_split = False

    earliest_index = min(
        [index for index in [combined_index, answer_index, solution_index] if index is not None],
        default=None,
    )

    if combined_index is not None and combined_index == earliest_index:
        saw_structured_split = True
        prefix = normalized[:combined_index]
        question_text = prefix.strip() if has_meaningful_prefix_text(prefix) else ""
        solution_text = normalized[combined_index:].strip()
        warnings.append("检测到“答案解析/答案与解析”标题，本页按答案与解析内容处理。")
    elif answer_index is not None and answer_index == earliest_index:
        saw_structured_split = True
        prefix = normalized[:answer_index]
        question_text = prefix.strip() if has_meaningful_prefix_text(prefix) else ""
        answer_block = normalized[answer_index:].strip()
        if solution_index is not None and solution_index > answer_index:
            answer_text = normalized[answer_index:solution_index].strip()
            solution_text = normalized[solution_index:].strip()
        else:
            answer_lines = answer_block.splitlines()
            if answer_lines:
                answer_text = answer_lines[0].strip()
                tail_text = "\n".join(answer_lines[1:]).strip()
                if tail_text:
                    solution_text = tail_text
    elif solution_index is not None:
        saw_structured_split = True
        prefix = normalized[:solution_index]
        question_text = prefix.strip() if has_meaningful_prefix_text(prefix) else ""
        solution_text = normalized[solution_index:].strip()

    if not question_text and not saw_structured_split:
        question_text = normalized
        warnings.append("没有可靠切出题干，已回退为整段 OCR 文本。")

    answer_text = strip_known_marker_prefix(answer_text)
    solution_text = strip_known_marker_prefix(solution_text)

    if not normalized:
        warnings.append("OCR 文本为空。")
    elif len(normalized) < 24:
        warnings.append("OCR 文本较短，可能需要人工补充。")

    return {
        "full_text": normalized,
        "question_text": question_text.strip(),
        "answer_text": answer_text.strip(),
        "solution_text": solution_text.strip(),
        "warnings": warnings,
        "answer_marker_count": answer_count,
        "question_number_count": question_number_count,
    }


def join_non_empty(parts: list[str], *, separator: str = "\n\n") -> str:
    return separator.join([part.strip() for part in parts if str(part).strip()])


def merge_ocr_split_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    full_text = join_non_empty([str(item.get("full_text") or "") for item in results])
    question_parts: list[str] = []
    answer_parts: list[str] = []
    solution_parts: list[str] = []
    warnings: list[str] = []
    answer_marker_count = 0
    question_number_count = 0

    for item in results:
        question_text = str(item.get("question_text") or "").strip()
        answer_text = str(item.get("answer_text") or "").strip()
        solution_text = str(item.get("solution_text") or "").strip()
        full_text_item = str(item.get("full_text") or "").strip()
        role_guess = item.get("role_guess") or {}
        role = str(role_guess.get("role") or "").strip() or "unknown"

        if role == "question":
            if question_text or full_text_item:
                question_parts.append(question_text or full_text_item)
            if answer_text:
                answer_parts.append(answer_text)
            if solution_text:
                solution_parts.append(solution_text)
        elif role == "answer":
            candidate_answer = answer_text or strip_known_marker_prefix(full_text_item)
            if candidate_answer:
                answer_parts.append(candidate_answer)
            if question_text and question_text != full_text_item and has_meaningful_prefix_text(question_text):
                question_parts.append(question_text)
            if solution_text:
                solution_parts.append(solution_text)
        elif role == "solution":
            candidate_solution = solution_text or strip_known_marker_prefix(full_text_item)
            if candidate_solution:
                solution_parts.append(candidate_solution)
            if question_text and question_text != full_text_item and has_meaningful_prefix_text(question_text):
                question_parts.append(question_text)
            if answer_text:
                answer_parts.append(answer_text)
        elif role == "answer_solution":
            if answer_text:
                answer_parts.append(answer_text)
            candidate_solution = solution_text or strip_known_marker_prefix(full_text_item)
            if candidate_solution:
                solution_parts.append(candidate_solution)
            if question_text and question_text != full_text_item and has_meaningful_prefix_text(question_text):
                question_parts.append(question_text)
        else:
            if question_text:
                question_parts.append(question_text)
            if answer_text:
                answer_parts.append(answer_text)
            if solution_text:
                solution_parts.append(solution_text)
        warnings.extend([str(w).strip() for w in item.get("warnings") or [] if str(w).strip()])
        answer_marker_count += int(item.get("answer_marker_count") or 0)
        question_number_count += int(item.get("question_number_count") or 0)

    merged_question = join_non_empty(question_parts)
    merged_answer = join_non_empty(answer_parts)
    merged_solution = join_non_empty(solution_parts)

    if len(results) > 1:
        warnings.append("本次导入已合并多张图片 / 多个文件，请人工确认题干、答案、解析顺序。")

    return {
        "full_text": full_text,
        "question_text": merged_question or full_text,
        "answer_text": merged_answer,
        "solution_text": merged_solution,
        "warnings": unique_str_list(warnings),
        "answer_marker_count": answer_marker_count,
        "question_number_count": question_number_count,
    }


def build_ocr_prefill(
    *,
    target: str,
    field_mode: str,
    filename: str,
    split_result: dict[str, Any],
) -> dict[str, str]:
    full_text = str(split_result.get("full_text") or "").strip()
    question_text = str(split_result.get("question_text") or "").strip() or full_text
    answer_text = str(split_result.get("answer_text") or "").strip()
    solution_text = str(split_result.get("solution_text") or "").strip()
    source_name = f"MinerU OCR · {filename}"

    if target == "diagnosis":
        if field_mode == "problem":
            return {"problem_text": full_text}
        if field_mode == "reference":
            return {"reference_answer": full_text}
        return {
            "problem_text": question_text or full_text,
            "reference_answer": join_non_empty([answer_text, solution_text]),
        }

    if target == "coach":
        if field_mode == "student_reply":
            return {"student_reply": full_text}
        return {"problem_text": question_text or full_text}

    if target == "wrongbook":
        if field_mode == "stem":
            return {
                "stem": full_text,
                "source_name": source_name,
            }
        if field_mode == "answer_solution":
            return {
                "correct_answer": answer_text or full_text,
                "solution_text": solution_text or (full_text if not answer_text else ""),
                "source_name": source_name,
            }
        return {
            "stem": question_text or full_text,
            "correct_answer": answer_text,
            "solution_text": solution_text,
            "source_name": source_name,
        }

    raise ValueError(f"Unsupported OCR target: {target}")


def resolve_python_command() -> str:
    python3_path = shutil.which("python3")
    if python3_path:
        return python3_path
    if sys.executable:
        return sys.executable
    raise FileNotFoundError("python3 is not available in PATH.")


def save_uploaded_ocr_file(*, filename: str, content: bytes) -> Path:
    suffix = Path(filename).suffix
    safe_stem = slugify_text(Path(filename).stem)
    target_dir = OCR_UPLOAD_DIR / now_slug()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{safe_stem}_{uuid4().hex[:8]}{suffix}"
    target_path.write_bytes(content)
    return target_path


def run_mineru_ocr(upload_path: Path, *, target: str) -> tuple[dict[str, Any], str]:
    if not MINERU_WRAPPER_PATH.exists():
        raise FileNotFoundError(f"MinerU wrapper not found: {MINERU_WRAPPER_PATH}")

    run_name = f"app_{target}_{now_slug()}_{slugify_text(upload_path.stem)}"
    method = "ocr" if upload_path.suffix.lower() in IMAGE_SUFFIXES else "auto"
    command = [
        resolve_python_command(),
        str(MINERU_WRAPPER_PATH),
        "--input",
        str(upload_path),
        "--run-name",
        run_name,
        "--backend",
        "pipeline",
        "--lang",
        "ch",
        "--method",
        method,
        "--formula",
        "--no-table",
        "--force",
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        check=False,
    )
    run_dir = OCR_RUNS_DIR / run_name
    summary_path = run_dir / "ocr_run_summary.json"
    if not summary_path.exists():
        error_text = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(error_text or "MinerU did not produce an OCR summary.")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    preview_path = Path(summary.get("preview_text_path") or "")
    preview_text = (
        preview_path.read_text(encoding="utf-8").strip()
        if preview_path.exists()
        else ""
    )
    if completed.returncode != 0:
        error_text = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            error_text
            or f"MinerU failed. Check {summary.get('stderr_path') or summary_path}."
        )
    return summary, preview_text


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def unique_str_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        items.append(value)
    return items


def build_answer_polish_prompt(
    *,
    question_text: str,
    answer_text: str,
    solution_text: str,
) -> str:
    return f"""
你是数学题答案整理助手。

任务：
根据题目、答案、解析，输出一个严格 JSON，对答案进行轻整理，并提炼学生可读的“解题思路”。

输出要求：
1. 只能输出一个 JSON 对象。
2. 不要输出 Markdown、代码块、解释、前缀。
3. JSON 必须包含两个字段：
   - polished_answer: 整理后的标准答案，保持数学含义不变，尽量更顺。
   - thinking_summary: 用中文概括这道题的解题思路，控制在 3-5 句，强调“先做什么，再做什么”，不要只抄解析原文。
4. 如果原答案很短，可以适度补成一句完整话；但不要凭空编造不存在的步骤。
5. 如果解析里有明显主线，thinking_summary 要优先提炼主线，而不是细枝末节。

【题目】
{question_text.strip() or "无"}

【答案】
{answer_text.strip() or "无"}

【解析】
{solution_text.strip() or "无"}
""".strip()


def parse_answer_polish_response(raw_text: str) -> dict[str, str] | None:
    text = raw_text.strip()
    if not text:
        return None
    if not (text.startswith("{") and text.endswith("}")):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start : end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    polished_answer = str(data.get("polished_answer") or "").strip()
    thinking_summary = str(data.get("thinking_summary") or "").strip()
    if not polished_answer and not thinking_summary:
        return None
    return {
        "polished_answer": polished_answer,
        "thinking_summary": thinking_summary,
    }


def build_ocr_extract_response(
    *,
    target: str,
    field_mode: str,
    uploads: list[dict[str, Any]],
) -> dict[str, Any]:
    if target not in {"diagnosis", "coach", "wrongbook"}:
        raise ValueError("target must be diagnosis / coach / wrongbook")
    if not uploads:
        raise ValueError("At least one uploaded file is required.")

    upload_records: list[dict[str, Any]] = []
    split_results: list[dict[str, Any]] = []
    all_generated_files: list[str] = []

    for upload in uploads:
        filename = str(upload.get("filename") or "").strip()
        file_bytes = upload.get("content") or b""
        if not filename:
            raise ValueError("Uploaded file name is empty.")
        if not file_bytes:
            raise ValueError(f"Uploaded file is empty: {filename}")
        upload_path = save_uploaded_ocr_file(filename=filename, content=file_bytes)
        summary, preview_text = run_mineru_ocr(upload_path, target=target)
        split_result = split_ocr_preview_text(preview_text)
        role_guess = detect_ocr_content_role(preview_text, split_result)
        split_result["role_guess"] = role_guess
        split_results.append(split_result)
        all_generated_files.extend([str(item) for item in summary.get("generated_files") or [] if str(item).strip()])
        upload_records.append(
            {
                "filename": filename,
                "upload_path": str(upload_path),
                "run_dir": summary.get("run_dir"),
                "generated_files": summary.get("generated_files") or [],
                "preview_text": split_result.get("full_text"),
                "preview_excerpt": str(split_result.get("full_text") or "")[:300],
                "question_text": split_result.get("question_text"),
                "answer_text": split_result.get("answer_text"),
                "solution_text": split_result.get("solution_text"),
                "detected_role": role_guess.get("role"),
                "detected_role_label": role_guess.get("role_label"),
                "detected_role_confidence": role_guess.get("confidence"),
                "detected_role_reasons": role_guess.get("reasons") or [],
                "warnings": split_result.get("warnings") or [],
            }
        )

    split_result = merge_ocr_split_results(split_results)
    display_name = " + ".join([record["filename"] for record in upload_records[:3]])
    if len(upload_records) > 3:
        display_name += f" + {len(upload_records) - 3} more"
    prefill = build_ocr_prefill(
        target=target,
        field_mode=field_mode,
        filename=display_name,
        split_result=split_result,
    )
    return {
        "ocr": {
            "target": target,
            "field_mode": field_mode,
            "filename": display_name,
            "file_count": len(upload_records),
            "files": upload_records,
            "upload_path": upload_records[0]["upload_path"],
            "run_dir": upload_records[0]["run_dir"],
            "generated_files": unique_str_list(all_generated_files),
            "preview_text": split_result.get("full_text"),
            "preview_excerpt": str(split_result.get("full_text") or "")[:800],
            "question_text": split_result.get("question_text"),
            "answer_text": split_result.get("answer_text"),
            "solution_text": split_result.get("solution_text"),
            "warnings": split_result.get("warnings") or [],
            "prefill": prefill,
        }
    }


class ReviewAppState:
    def __init__(self) -> None:
        self.example_map = load_example_map(DEFAULT_EXAMPLE_MD_PATH)
        self.leaf_card_lookup = load_leaf_card_lookup()
        self.tree_inventory = read_json(TREE_DATA_PATH)
        self.base_review_state = load_review_state(DEFAULT_STATE_PATH)
        self.base_memory_profile = read_json(DEFAULT_MEMORY_PROFILE_PATH)
        default_student_id = (
            str(self.base_review_state.get("student_id") or "").strip()
            or str(self.base_memory_profile.get("student_id") or "").strip()
            or "app_student_local"
        )
        self.legacy_student_id = self._detect_legacy_student_id(default_student_id)
        self.student_id = (
            str(os.getenv("TEACHAGENT_DEFAULT_STUDENT_ID") or "").strip()
            or self.legacy_student_id
            or default_student_id
        )
        self.store = self._build_store()
        if self.using_database_store():
            if self.store.count_knowledge_nodes(source_scope="system") == 0:
                inventory_nodes = [
                    node
                    for node in self.tree_inventory.get("nodes", [])
                    if isinstance(node, dict)
                ]
                if inventory_nodes:
                    self.store.upsert_knowledge_nodes(inventory_nodes)
            self.store.get_or_create_student(self.student_id)
        self.session_id = f"app_session_{uuid4().hex[:12]}"
        self.last_diagnosis_request: dict[str, Any] = {}
        self.last_coach_request: dict[str, Any] = {}
        self.custom_question_states = self._load_custom_question_states()
        self.current_review_state = self._load_current_review_state()
        self.current_memory_profile = self._load_current_memory_profile()
        self.tree_notes = self._load_tree_notes()
        self.tree_custom_nodes = self._load_tree_custom_nodes()
        if self.using_database_store() and (
            self.tree_custom_nodes.get("nodes") or self.tree_notes
        ):
            self.persist_tree_state()
        self.last_mode = KNOWLEDGE_REVIEW_MODE
        self.last_now = None
        self.diagnosis_agent: FoundryDiagnosisAgent | None = None
        self.coach_agent: FoundryCoachAgent | None = None
        self.diagnosis_orchestrator: FoundryDiagnosisOrchestrator | None = None
        self.diagnosis_flow_session: DiagnosisFlowSession | None = None
        self.coach_chat_session = None
        self.diagnosis_chat_history: list[dict[str, Any]] = []
        self.coach_chat_history: list[dict[str, Any]] = []
        self.active_diagnosis_question_id: str | None = None
        self.active_coach_question_id: str | None = None
        self.answer_polish_cache: dict[str, dict[str, str]] = {}
        self.persist_session_state()

    def _detect_legacy_student_id(self, default_student_id: str) -> str:
        for path in (SESSION_STATE_PATH, SESSION_MEMORY_PROFILE_PATH):
            if not path.exists():
                continue
            try:
                payload = read_json(path)
            except Exception:
                continue
            student_id = str(payload.get("student_id") or "").strip()
            if student_id:
                return student_id
        return default_student_id

    def _normalize_student_id(self, value: str) -> str:
        student_id = str(value or "").strip()
        if not student_id:
            raise ValueError("student_id is required")
        return student_id

    def _student_storage_slug(self, student_id: str | None = None) -> str:
        raw_student_id = self._normalize_student_id(student_id or self.student_id)
        slug = re.sub(r"[^0-9A-Za-z._-]+", "_", raw_student_id).strip("._")
        if not slug:
            slug = f"student_{hashlib.md5(raw_student_id.encode('utf-8')).hexdigest()[:12]}"
        if len(slug) > 80:
            suffix = hashlib.md5(raw_student_id.encode("utf-8")).hexdigest()[:12]
            slug = f"{slug[:67]}_{suffix}"
        return slug

    def _student_data_dir(self, student_id: str | None = None) -> Path:
        return STUDENT_DATA_ROOT / self._student_storage_slug(student_id)

    def _student_review_state_path(self, student_id: str | None = None) -> Path:
        return self._student_data_dir(student_id) / "review_state.session.json"

    def _student_memory_profile_path(self, student_id: str | None = None) -> Path:
        return self._student_data_dir(student_id) / "student_memory_profile.session.json"

    def _student_tree_notes_path(self, student_id: str | None = None) -> Path:
        return self._student_data_dir(student_id) / "tree_notes.session.json"

    def _student_tree_custom_nodes_path(self, student_id: str | None = None) -> Path:
        return self._student_data_dir(student_id) / "tree_custom_nodes.session.json"

    def _student_wrongbook_questions_path(self, student_id: str | None = None) -> Path:
        return self._student_data_dir(student_id) / "wrongbook_custom_questions.session.json"

    def _student_memory_events_path(self, student_id: str | None = None) -> Path:
        return self._student_data_dir(student_id) / "student_memory_events.jsonl"

    def _allows_legacy_local_fallback(self, student_id: str | None = None) -> bool:
        return self._normalize_student_id(student_id or self.student_id) == self.legacy_student_id

    def _load_optional_student_json(
        self,
        primary_path: Path,
        *,
        default: dict[str, Any],
        legacy_path: Path | None = None,
        use_legacy_fallback: bool = False,
    ) -> dict[str, Any]:
        if primary_path.exists():
            return read_json(primary_path)
        if use_legacy_fallback and legacy_path is not None and legacy_path.exists():
            return read_json(legacy_path)
        return copy.deepcopy(default)

    def _reset_runtime_state(self) -> None:
        self.last_diagnosis_request = {}
        self.last_coach_request = {}
        self.last_mode = KNOWLEDGE_REVIEW_MODE
        self.last_now = None
        self.diagnosis_flow_session = None
        self.coach_chat_session = None
        self.diagnosis_chat_history = []
        self.coach_chat_history = []
        self.active_diagnosis_question_id = None
        self.active_coach_question_id = None
        self.answer_polish_cache = {}

    def _persist_current_student_locally(self) -> None:
        self.persist_wrongbook_state()
        self.persist_tree_state()
        self.persist_session_state()
        self.persist_memory_profile()

    def _collect_local_student_summary(
        self,
        *,
        student_id: str,
        review_state_path: Path,
        memory_profile_path: Path,
        tree_notes_path: Path,
        tree_custom_nodes_path: Path,
    ) -> dict[str, Any]:
        review_state = empty_review_state(student_id=student_id)
        if review_state_path.exists():
            try:
                payload = load_review_state(review_state_path)
                if isinstance(payload, dict):
                    review_state = payload
            except Exception:
                pass

        question_states = [
            item
            for item in review_state.get("example_question_states", [])
            if isinstance(item, dict)
        ]
        wrongbook_question_count = len(
            [item for item in question_states if self._is_wrongbook_question_state(item)]
        )

        custom_nodes_payload = {"nodes": []}
        if tree_custom_nodes_path.exists():
            try:
                payload = read_json(tree_custom_nodes_path)
                if isinstance(payload, dict):
                    custom_nodes_payload = payload
            except Exception:
                pass

        tree_notes_payload: dict[str, Any] = {}
        if tree_notes_path.exists():
            try:
                payload = read_json(tree_notes_path)
                if isinstance(payload, dict):
                    tree_notes_payload = payload
            except Exception:
                pass

        display_name = None
        grade_level = None
        if memory_profile_path.exists():
            try:
                payload = read_json(memory_profile_path)
                if isinstance(payload, dict):
                    summary = payload.get("personalization_summary") or {}
                    display_name = str(summary.get("display_name") or "").strip() or None
                    grade_level = str(payload.get("grade_level") or "").strip() or None
            except Exception:
                pass

        candidate_paths = [
            path
            for path in [
                review_state_path,
                memory_profile_path,
                tree_notes_path,
                tree_custom_nodes_path,
            ]
            if path.exists()
        ]
        if candidate_paths:
            updated_at = datetime.fromtimestamp(
                max(path.stat().st_mtime for path in candidate_paths)
            ).astimezone().isoformat()
        else:
            updated_at = None

        return {
            "student_id": student_id,
            "display_name": display_name,
            "grade_level": grade_level,
            "status": "active",
            "question_count": len(question_states),
            "wrongbook_question_count": wrongbook_question_count,
            "custom_node_count": len(custom_nodes_payload.get("nodes") or []),
            "note_count": len(
                [
                    value
                    for value in tree_notes_payload.values()
                    if isinstance(value, str) and value.strip()
                ]
            ),
            "updated_at": updated_at,
            "last_activity_at": updated_at,
        }

    def list_student_summaries(self) -> list[dict[str, Any]]:
        storage_mode = "postgres" if self.using_database_store() else "local_json"
        storage_label = "PostgreSQL" if self.using_database_store() else "本地 JSON"
        summaries: list[dict[str, Any]] = []

        if self.using_database_store():
            summaries = [
                item
                for item in self.store.list_students()
                if not str(item.get("student_id") or "").startswith("tmp_")
            ]
        else:
            seen_ids: set[str] = set()
            if STUDENT_DATA_ROOT.exists():
                for student_dir in sorted(
                    [path for path in STUDENT_DATA_ROOT.iterdir() if path.is_dir()],
                    key=lambda item: item.name,
                ):
                    candidate_id = None
                    for candidate_path in (
                        student_dir / "review_state.session.json",
                        student_dir / "student_memory_profile.session.json",
                    ):
                        if not candidate_path.exists():
                            continue
                        try:
                            payload = read_json(candidate_path)
                        except Exception:
                            continue
                        if isinstance(payload, dict):
                            text = str(payload.get("student_id") or "").strip()
                            if text:
                                candidate_id = text
                                break
                    student_id = candidate_id or student_dir.name
                    if student_id.startswith("tmp_"):
                        continue
                    if student_id in seen_ids:
                        continue
                    seen_ids.add(student_id)
                    summaries.append(
                        self._collect_local_student_summary(
                            student_id=student_id,
                            review_state_path=student_dir / "review_state.session.json",
                            memory_profile_path=student_dir / "student_memory_profile.session.json",
                            tree_notes_path=student_dir / "tree_notes.session.json",
                            tree_custom_nodes_path=student_dir / "tree_custom_nodes.session.json",
                        )
                    )

            if (
                self.legacy_student_id
                and self.legacy_student_id not in seen_ids
                and (SESSION_STATE_PATH.exists() or SESSION_MEMORY_PROFILE_PATH.exists())
            ):
                summaries.append(
                    self._collect_local_student_summary(
                        student_id=self.legacy_student_id,
                        review_state_path=SESSION_STATE_PATH,
                        memory_profile_path=SESSION_MEMORY_PROFILE_PATH,
                        tree_notes_path=TREE_NOTEBOOK_PATH,
                        tree_custom_nodes_path=TREE_CUSTOM_NODES_PATH,
                    )
                )

        summaries = sorted(
            summaries,
            key=lambda item: (
                0 if str(item.get("student_id") or "") == self.student_id else 1,
                str(item.get("last_activity_at") or ""),
                str(item.get("student_id") or ""),
            ),
            reverse=False,
        )
        ranked = (
            [item for item in summaries if str(item.get("student_id") or "") == self.student_id]
            + sorted(
                [
                    item
                    for item in summaries
                    if str(item.get("student_id") or "") != self.student_id
                ],
                key=lambda item: (
                    str(item.get("last_activity_at") or ""),
                    str(item.get("student_id") or ""),
                ),
                reverse=True,
            )
        )

        return [
            {
                **item,
                "storage_mode": storage_mode,
                "storage_label": storage_label,
                "is_current": str(item.get("student_id") or "") == self.student_id,
            }
            for item in ranked
        ]

    def build_student_payload(self) -> dict[str, Any]:
        storage_mode = "postgres" if self.using_database_store() else "local_json"
        storage_label = "PostgreSQL" if self.using_database_store() else "本地 JSON"
        return {
            "student_id": self.student_id,
            "storage_mode": storage_mode,
            "storage_label": storage_label,
            "database_enabled": self.using_database_store(),
        }

    def build_workspace_payload(self) -> dict[str, Any]:
        return {
            "student": self.build_student_payload(),
            "students": self.list_student_summaries(),
            "dashboard": self.build_dashboard_payload(mode=self.last_mode),
            "tree": self.build_tree_payload(),
            "wrongbook": self.build_wrongbook_payload(),
            "flow": self.build_diagnosis_flow_payload(),
            "chat": self.build_coach_chat_payload(),
        }

    def switch_student(self, student_id: str) -> dict[str, Any]:
        normalized_student_id = self._normalize_student_id(student_id)
        if normalized_student_id == self.student_id:
            return self.build_workspace_payload()

        self._persist_current_student_locally()
        self.student_id = normalized_student_id
        self.session_id = f"app_session_{uuid4().hex[:12]}"
        if self.using_database_store():
            self.store.get_or_create_student(self.student_id)

        self.custom_question_states = self._load_custom_question_states()
        self.current_review_state = self._load_current_review_state()
        self.current_memory_profile = self._load_current_memory_profile()
        self.tree_notes = self._load_tree_notes()
        self.tree_custom_nodes = self._load_tree_custom_nodes()
        if self.using_database_store() and (
            self.tree_custom_nodes.get("nodes") or self.tree_notes
        ):
            self.persist_tree_state()
        self._reset_runtime_state()
        self.persist_session_state()
        self.persist_memory_profile()
        self.persist_wrongbook_state()
        return self.build_workspace_payload()

    def _build_store(self) -> TeachAgentPostgresStore | None:
        database_url = str(database_url_from_env() or "").strip()
        if not database_url:
            return None
        try:
            return TeachAgentPostgresStore()
        except Exception as exc:
            print(f"[TeachAgent] PostgreSQL store disabled: {exc}")
            return None

    def using_database_store(self) -> bool:
        return self.store is not None

    def _load_optional_json(self, path: Path, *, default: dict[str, Any]) -> dict[str, Any]:
        if path.exists():
            return read_json(path)
        return copy.deepcopy(default)

    def _diagnosis_store_uid(self) -> str:
        return self.active_diagnosis_question_id or f"diag:{self.session_id}"

    def _coach_store_uid(self) -> str:
        return self.active_coach_question_id or f"coach:{self.session_id}"

    def _compose_review_state(self) -> dict[str, Any]:
        payload = copy.deepcopy(self.base_review_state)
        payload["student_id"] = self.student_id
        question_states = list(payload.get("example_question_states") or [])
        existing_ids = {
            str(item.get("question_id") or "").strip()
            for item in question_states
            if isinstance(item, dict)
        }
        for item in self.custom_question_states.get("questions", []):
            question_id = str(item.get("question_id") or "").strip()
            if not question_id or question_id in existing_ids:
                continue
            question_states.append(copy.deepcopy(item))
            existing_ids.add(question_id)
        payload["example_question_states"] = question_states
        return payload

    def _compose_blank_review_state(self) -> dict[str, Any]:
        payload = empty_review_state(student_id=self.student_id)
        question_states = list(payload.get("example_question_states") or [])
        existing_ids = set()
        for item in self.custom_question_states.get("questions", []):
            question_id = str(item.get("question_id") or "").strip()
            if not question_id or question_id in existing_ids:
                continue
            question_states.append(copy.deepcopy(item))
            existing_ids.add(question_id)
        payload["example_question_states"] = question_states
        return payload

    def _load_custom_question_states(self) -> dict[str, Any]:
        if self.using_database_store():
            review_state = self.store.load_review_state(self.student_id)
            if isinstance(review_state, dict):
                questions = []
                for item in review_state.get("example_question_states", []):
                    if not isinstance(item, dict):
                        continue
                    if self._is_wrongbook_question_state(item):
                        questions.append(copy.deepcopy(item))
                return {"questions": questions}
            return self._load_optional_student_json(
                self._student_wrongbook_questions_path(),
                default={"questions": []},
                legacy_path=WRONGBOOK_CUSTOM_QUESTIONS_PATH,
                use_legacy_fallback=self._allows_legacy_local_fallback(),
            )
        return self._load_optional_student_json(
            self._student_wrongbook_questions_path(),
            default={"questions": []},
            legacy_path=WRONGBOOK_CUSTOM_QUESTIONS_PATH,
            use_legacy_fallback=self._allows_legacy_local_fallback(),
        )

    def _load_tree_notes(self) -> dict[str, Any]:
        if self.using_database_store():
            payload = self.store.load_question_notes(self.student_id)
            if payload:
                return payload
            return self._load_optional_student_json(
                self._student_tree_notes_path(),
                default={},
                legacy_path=TREE_NOTEBOOK_PATH,
                use_legacy_fallback=self._allows_legacy_local_fallback(),
            )
        return self._load_optional_student_json(
            self._student_tree_notes_path(),
            default={},
            legacy_path=TREE_NOTEBOOK_PATH,
            use_legacy_fallback=self._allows_legacy_local_fallback(),
        )

    def _load_tree_custom_nodes(self) -> dict[str, Any]:
        if self.using_database_store():
            payload = self.store.load_custom_nodes(self.student_id)
            if payload.get("nodes"):
                return payload
            return self._load_optional_student_json(
                self._student_tree_custom_nodes_path(),
                default={"nodes": []},
                legacy_path=TREE_CUSTOM_NODES_PATH,
                use_legacy_fallback=self._allows_legacy_local_fallback(),
            )
        return self._load_optional_student_json(
            self._student_tree_custom_nodes_path(),
            default={"nodes": []},
            legacy_path=TREE_CUSTOM_NODES_PATH,
            use_legacy_fallback=self._allows_legacy_local_fallback(),
        )

    def _load_current_review_state(self) -> dict[str, Any]:
        if self.using_database_store():
            payload = self.store.load_review_state(self.student_id)
            if isinstance(payload, dict) and payload.get("student_id") == self.student_id:
                return payload
        review_state_path = self._student_review_state_path()
        legacy_review_state_path = (
            SESSION_STATE_PATH if self._allows_legacy_local_fallback() else None
        )
        for path in [review_state_path, legacy_review_state_path]:
            if path is None or not path.exists():
                continue
            try:
                payload = load_review_state(path)
                if isinstance(payload, dict) and payload.get("student_id") == self.student_id:
                    return payload
            except Exception:
                pass
        return self._compose_blank_review_state()

    def _load_current_memory_profile(self) -> dict[str, Any]:
        if self.using_database_store():
            payload = self.store.load_memory_profile(self.student_id)
            if isinstance(payload, dict) and payload.get("student_id") == self.student_id:
                return payload
        memory_profile_path = self._student_memory_profile_path()
        legacy_memory_profile_path = (
            SESSION_MEMORY_PROFILE_PATH if self._allows_legacy_local_fallback() else None
        )
        for path in [memory_profile_path, legacy_memory_profile_path]:
            if path is None or not path.exists():
                continue
            try:
                payload = read_json(path)
                if isinstance(payload, dict) and payload.get("student_id") == self.student_id:
                    return payload
            except Exception:
                pass
        return initialize_student_memory_profile(self.student_id)

    def persist_session_state(self) -> None:
        if self.using_database_store():
            self.store.save_review_state(self.current_review_state)
        write_json(self._student_review_state_path(), self.current_review_state)

    def persist_memory_profile(self) -> None:
        if self.using_database_store():
            self.store.save_memory_profile(self.current_memory_profile)
        write_json(self._student_memory_profile_path(), self.current_memory_profile)

    def persist_tree_state(self) -> None:
        if self.using_database_store():
            custom_nodes = [
                node
                for node in self.tree_custom_nodes.get("nodes", [])
                if isinstance(node, dict)
            ]
            if custom_nodes:
                self.store.upsert_knowledge_nodes(
                    custom_nodes,
                    owner_student_uid=self.student_id,
                )
            for question_id, note in self.tree_notes.items():
                if str(question_id).strip() and str(note).strip():
                    self.store.save_question_note(
                        self.student_id,
                        str(question_id),
                        str(note),
                    )
        write_json(self._student_tree_notes_path(), self.tree_notes)
        write_json(self._student_tree_custom_nodes_path(), self.tree_custom_nodes)

    def persist_wrongbook_state(self) -> None:
        write_json(
            self._student_wrongbook_questions_path(),
            self.custom_question_states,
        )

    def reset(self) -> dict[str, Any]:
        if self.using_database_store():
            self.store.reset_student_runtime(self.student_id)
        self.custom_question_states = {"questions": []}
        self.tree_notes = {}
        self.tree_custom_nodes = {"nodes": []}
        self.current_review_state = self._compose_blank_review_state()
        self.current_memory_profile = initialize_student_memory_profile(self.student_id)
        self._reset_runtime_state()
        self.persist_session_state()
        self.persist_memory_profile()
        self.persist_wrongbook_state()
        events_path = self._student_memory_events_path()
        events_path.parent.mkdir(parents=True, exist_ok=True)
        events_path.write_text("", encoding="utf-8")
        return self.build_dashboard_payload(mode=self.last_mode)

    def _ensure_review_nodes_for_question_state(self, question_state: dict[str, Any]) -> None:
        linked_node_ids = unique_str_list(
            [
                *list(question_state.get("primary_node_ids") or []),
                *list(question_state.get("secondary_node_ids") or []),
                *list(question_state.get("linked_node_ids") or []),
            ]
        )
        if not linked_node_ids:
            return

        node_lookup = {
            str(item.get("node_id") or "").strip(): item
            for item in self.current_review_state.get("knowledge_point_states", [])
            if isinstance(item, dict) and item.get("node_id")
        }
        source_batch_id = str(question_state.get("source_batch_id") or "wrongbook_manual_ui").strip() or "wrongbook_manual_ui"
        question_id = str(question_state.get("question_id") or "").strip()
        priority_note = str(question_state.get("priority_note") or "").strip()
        now_iso = datetime.now().astimezone().isoformat()

        for node_id in linked_node_ids:
            if node_id in node_lookup:
                linked_questions = unique_str_list(
                    [
                        *list(node_lookup[node_id].get("linked_question_ids") or []),
                        question_id,
                    ]
                )
                node_lookup[node_id]["linked_question_ids"] = linked_questions
                if priority_note and not str(node_lookup[node_id].get("priority_note") or "").strip():
                    node_lookup[node_id]["priority_note"] = priority_note
                continue

            self.current_review_state.setdefault("knowledge_point_states", []).append(
                {
                    "node_id": node_id,
                    "state": "new",
                    "mastery": 0.0,
                    "stability": 0.0,
                    "linked_question_ids": [question_id] if question_id else [],
                    "source_batch_ids": [source_batch_id],
                    "first_seen_at": now_iso,
                    "next_review_at": now_iso,
                    "priority_note": priority_note or "学生手动加入错题本后新建的复习节点。",
                    "correct_count": 0,
                    "wrong_count": 0,
                    "last_reviewed_at": None,
                    "manual_skip_until": None,
                    "session_priority_boost": 0.0,
                    "session_priority_until": None,
                    "session_priority_reason": None,
                }
            )

    def _source_section_from_question_payload(self, question_payload: dict[str, Any]) -> str | None:
        return str(
            question_payload.get("source_section")
            or question_payload.get("source_chapter")
            or ""
        ).strip() or None

    def _refresh_memory_profile_from_store(self) -> None:
        if self.using_database_store():
            events = self.store.load_memory_events(student_uid=self.student_id)
            self.current_memory_profile = build_profile(
                student_id=self.student_id,
                review_state=self.current_review_state,
                events=events,
            )
        else:
            self.current_memory_profile = build_profile_from_store(
                student_id=self.student_id,
                path=self._student_memory_events_path(),
                review_state=self.current_review_state,
            )
        self.persist_memory_profile()

    def _append_memory_event(self, event: dict[str, Any]) -> None:
        if self.using_database_store():
            self.store.append_memory_event(event)
        else:
            append_event(event, path=self._student_memory_events_path())
        self._refresh_memory_profile_from_store()

    def _question_id_for_problem(self, prefix: str, problem_text: str) -> str:
        return stable_question_id_from_text(prefix, problem_text)

    def _review_state_for_question_id(self, question_id: str) -> dict[str, Any] | None:
        for question_state in self.current_review_state.get("example_question_states", []):
            if str(question_state.get("question_id") or "").strip() == question_id:
                return question_state
        return None

    def _question_context(self, question_state: dict[str, Any]) -> tuple[str, str | None, str | None]:
        question_payload = question_state.get("question_payload") or {}
        question_id = str(question_state.get("question_id") or "").strip()
        question_type = str(question_payload.get("question_type") or "").strip() or None
        source_name = str(question_payload.get("source_name") or "").strip() or None
        source_section = self._source_section_from_question_payload(question_payload)
        return question_id, question_type, source_name, source_section

    def _log_binding_for_question_state(
        self,
        question_state: dict[str, Any],
        *,
        binding_source: str,
        candidate_node_ids: list[str] | None = None,
        binding_confidence: float | str | None = None,
    ) -> None:
        question_id, question_type, source_name, source_section = self._question_context(question_state)
        event = binding_result_to_memory_event(
            question_id=question_id,
            question_type=question_type,
            primary_node_id=(question_state.get("primary_node_ids") or [None])[0],
            secondary_node_ids=list(question_state.get("secondary_node_ids") or []),
            candidate_node_ids=candidate_node_ids or list(question_state.get("linked_node_ids") or []),
            binding_source=binding_source,
            source_name=source_name,
            source_section=source_section,
            student_id=self.student_id,
            session_id=self.session_id,
            binding_confidence=binding_confidence,
        )
        self._append_memory_event(event)

    def _log_student_choice_for_question_state(
        self,
        question_state: dict[str, Any],
        *,
        action_type: str,
        note: str | None = None,
    ) -> None:
        question_id, question_type, source_name, source_section = self._question_context(question_state)
        selected_node_ids = list(question_state.get("linked_node_ids") or [])
        target_id = question_id or ((question_state.get("primary_node_ids") or [None])[0] or "unknown")
        event = student_choice_to_memory_event(
            action_type=action_type,
            target_type="question",
            target_id=target_id,
            question_id=question_id,
            question_type=question_type,
            selected_node_ids=selected_node_ids,
            note=note,
            source_name=source_name,
            source_section=source_section,
            student_id=self.student_id,
            session_id=self.session_id,
        )
        self._append_memory_event(event)

    def _log_review_event(self, update_payload: dict[str, Any]) -> None:
        target_type = str(update_payload.get("target_type") or "").strip()
        target_id = str(update_payload.get("target_id") or "").strip()
        source_name = None
        source_section = None
        if target_type == "wrong_question":
            question_state = self._review_state_for_question_id(target_id)
            if question_state is not None:
                _, _, source_name, source_section = self._question_context(question_state)
        event = review_state_update_to_memory_event(
            {
                **update_payload,
                "result": update_payload.get("updated_payload", {})
                and next(
                    (
                        item.get("last_result")
                        for item in update_payload.get("updated_payload", {}).get("example_question_states", [])
                        if str(item.get("question_id") or "").strip() == target_id
                    ),
                    update_payload.get("result"),
                ),
                "source_name": source_name,
                "source_section": source_section,
            },
            student_id=self.student_id,
            session_id=self.session_id,
        )
        self._append_memory_event(event)

    def _log_diagnosis_event(
        self,
        *,
        diagnosis_payload: dict[str, Any],
        question_id: str,
        question_type: str | None,
        source_name: str | None,
        source_section: str | None,
        binding: dict[str, Any] | None = None,
    ) -> None:
        event = diagnosis_result_to_memory_event(
            diagnosis_payload,
            question_id=question_id,
            question_type=question_type,
            binding=binding,
            source_name=source_name,
            source_section=source_section,
            student_id=self.student_id,
            session_id=self.session_id,
        )
        self._append_memory_event(event)

    def _log_coach_event(
        self,
        *,
        coach_payload: dict[str, Any],
        question_id: str,
        question_type: str | None,
        error_type: str | None,
        source_name: str | None,
        source_section: str | None,
        binding: dict[str, Any] | None = None,
    ) -> None:
        event = coach_response_to_memory_event(
            coach_payload,
            question_id=question_id,
            question_type=question_type,
            binding=binding,
            error_type=error_type,
            source_name=source_name,
            source_section=source_section,
            student_id=self.student_id,
            session_id=self.session_id,
        )
        self._append_memory_event(event)

    def build_dashboard_payload(
        self,
        *,
        mode: str | None = None,
        now_value: str | None = None,
    ) -> dict[str, Any]:
        selected_mode = mode if mode in ALLOWED_MODES else self.last_mode
        self.last_mode = selected_mode
        self.last_now = now_value or self.last_now
        bundle_result = build_review_bundles(
            self.current_review_state,
            example_map=self.example_map,
            leaf_card_lookup=self.leaf_card_lookup,
            now=now_from_value(self.last_now),
            mode=selected_mode,
            student_memory_profile=self.current_memory_profile,
        )
        bundles = bundle_result.as_dict()
        profile_summary = (
            self.current_memory_profile.get("personalization_summary") or {}
        )
        return {
            "student": self.build_student_payload(),
            "session": {
                "student_id": self.student_id,
                "storage_mode": (
                    "postgres" if self.using_database_store() else "local_json"
                ),
                "storage_label": (
                    "PostgreSQL" if self.using_database_store() else "本地 JSON"
                ),
                "mode": selected_mode,
                "review_state_record_id": bundles.get("review_state_record_id"),
                "generated_at": bundles.get("generated_at"),
                "bundle_count": len(bundles.get("review_bundles", [])),
            },
            "memory_summary": {
                "memory_stage": profile_summary.get("memory_stage"),
                "recommended_review_mode": profile_summary.get("recommended_review_mode"),
                "recommended_teaching_mode": profile_summary.get("recommended_teaching_mode"),
                "dominant_error_type": profile_summary.get("dominant_error_type"),
                "notes": profile_summary.get("notes") or [],
                "alerts": profile_summary.get("alerts") or [],
                "top_recurrent_nodes": profile_summary.get("top_recurrent_nodes") or [],
            },
            "review_state_summary": {
                "student_id": self.current_review_state.get("student_id"),
                "knowledge_point_count": len(
                    self.current_review_state.get("knowledge_point_states", [])
                ),
                "question_count": len(
                    self.current_review_state.get("example_question_states", [])
                ),
            },
            "bundles": bundles,
        }

    def get_diagnosis_agent(self) -> FoundryDiagnosisAgent:
        if self.diagnosis_agent is None:
            self.diagnosis_agent = FoundryDiagnosisAgent(
                use_default_credential=should_use_default_credential()
            )
        return self.diagnosis_agent

    def get_coach_agent(self) -> FoundryCoachAgent:
        if self.coach_agent is None:
            self.coach_agent = FoundryCoachAgent(
                use_default_credential=should_use_default_credential()
            )
        return self.coach_agent

    def polish_answer_and_solution(
        self,
        *,
        question_text: str,
        answer_text: str,
        solution_text: str,
    ) -> dict[str, Any]:
        cache_key = hashlib.md5(
            "||".join(
                [
                    question_text.strip(),
                    answer_text.strip(),
                    solution_text.strip(),
                ]
            ).encode("utf-8")
        ).hexdigest()
        cached = self.answer_polish_cache.get(cache_key)
        if cached is not None:
            return {
                "polish": {
                    **cached,
                    "cached": True,
                }
            }

        prompt = build_answer_polish_prompt(
            question_text=question_text,
            answer_text=answer_text,
            solution_text=solution_text,
        )
        response = self.get_coach_agent().client.chat.completions.create(
            model=self.get_coach_agent().model_deployment,
            messages=[
                {
                    "role": "system",
                    "content": "你必须只输出一个合法 JSON 对象，不能输出任何解释。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=ANSWER_POLISH_MAX_TOKENS,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = parse_answer_polish_response(raw)
        if parsed is None:
            raise ValueError("模型返回的答案整理结果无法解析。")
        self.answer_polish_cache[cache_key] = parsed
        return {
            "polish": {
                **parsed,
                "cached": False,
            }
        }

    def get_diagnosis_orchestrator(self) -> FoundryDiagnosisOrchestrator:
        if self.diagnosis_orchestrator is None:
            self.diagnosis_orchestrator = FoundryDiagnosisOrchestrator(
                diagnosis_agent=self.get_diagnosis_agent(),
                coach_agent=self.get_coach_agent(),
            )
        return self.diagnosis_orchestrator

    def apply_action(
        self,
        *,
        action: str,
        target_type: str,
        target_id: str,
        result: str | None,
        mode: str | None,
    ) -> dict[str, Any]:
        update = apply_review_action(
            self.current_review_state,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            now=now_from_value(self.last_now),
        )
        self.current_review_state = update.updated_payload
        self.persist_session_state()
        self._log_review_event(
            {
                **update.as_dict(),
                "result": result,
            }
        )
        return {
            "update": update.as_dict(),
            "dashboard": self.build_dashboard_payload(mode=mode or self.last_mode),
        }

    def _all_nodes(self) -> list[dict[str, Any]]:
        return list(self.tree_inventory.get("nodes") or []) + list(
            self.tree_custom_nodes.get("nodes") or []
        )

    def _build_tree_node_graph(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        node_lookup = {
            node["node_id"]: {
                **node,
                "children": [],
            }
            for node in self._all_nodes()
            if isinstance(node, dict) and node.get("node_id")
        }
        for node in node_lookup.values():
            parent_id = node.get("parent_id")
            if parent_id and parent_id in node_lookup:
                node_lookup[parent_id]["children"].append(node)
        roots = [node for node in node_lookup.values() if not node.get("parent_id")]
        return node_lookup, roots

    def _build_question_lookup(self) -> dict[str, dict[str, Any]]:
        return {
            str(question.get("question_id")): question
            for question in self.current_review_state.get("example_question_states", [])
            if isinstance(question, dict) and question.get("question_id")
        }

    def _is_wrongbook_question_state(self, question: dict[str, Any]) -> bool:
        question_id = str(question.get("question_id") or "").strip()
        source_batch_id = str(question.get("source_batch_id") or "").strip()
        payload = question.get("question_payload") or {}
        source_type = str(
            question.get("source_type")
            or (payload.get("source_type") if isinstance(payload, dict) else "")
            or ""
        ).strip()
        return (
            question_id.startswith("wq_")
            or source_batch_id == "wrongbook_manual_ui"
            or source_type in {
                "manual_entry",
                "ocr_direct",
                "diagnosis_transfer",
                "coach_transfer",
                "binder_import",
            }
        )

    def _build_wrongbook_question_lookup(self) -> dict[str, dict[str, Any]]:
        return {
            str(question.get("question_id")): question
            for question in self.current_review_state.get("example_question_states", [])
            if (
                isinstance(question, dict)
                and question.get("question_id")
                and self._is_wrongbook_question_state(question)
            )
        }

    def _question_payload(self, question: dict[str, Any]) -> dict[str, Any]:
        return question.get("question_payload") or self.example_map.get(
            question.get("question_id"),
            {},
        )

    def _build_question_view(
        self,
        question: dict[str, Any],
        *,
        matched_node_id: str,
        direct: bool,
    ) -> dict[str, Any]:
        payload = self._question_payload(question)
        return {
            "question_id": question.get("question_id"),
            "last_result": question.get("last_result"),
            "priority_note": question.get("priority_note"),
            "source_batch_id": question.get("source_batch_id"),
            "source_type": question.get("source_type") or payload.get("source_type"),
            "primary_node_ids": question.get("primary_node_ids") or [],
            "secondary_node_ids": question.get("secondary_node_ids") or [],
            "question_payload": payload,
            "note": self.tree_notes.get(question.get("question_id"), ""),
            "linked_via_node_ids": [matched_node_id],
            "is_direct_link": direct,
        }

    def build_tree_payload(self) -> dict[str, Any]:
        custom_nodes = list(self.tree_custom_nodes.get("nodes") or [])
        node_lookup, roots = self._build_tree_node_graph()
        question_lookup = self._build_question_lookup()

        def attach_payload(node: dict[str, Any]) -> dict[str, Any]:
            node_id = node["node_id"]
            children = sorted(
                [attach_payload(child) for child in node.get("children", [])],
                key=lambda item: (0 if item.get("is_leaf") else 1, item.get("name") or item.get("node_id")),
            )
            linked_question_map: dict[str, dict[str, Any]] = {}

            for question in question_lookup.values():
                linked_ids = question.get("linked_node_ids") or []
                if node_id not in linked_ids:
                    continue
                question_id = str(question.get("question_id") or "").strip()
                if not question_id:
                    continue
                linked_question_map[question_id] = self._build_question_view(
                    question,
                    matched_node_id=node_id,
                    direct=True,
                )

            for child in children:
                for child_question in child.get("linked_questions", []):
                    question_id = str(child_question.get("question_id") or "").strip()
                    if not question_id:
                        continue
                    existing = linked_question_map.get(question_id)
                    if existing is None:
                        linked_question_map[question_id] = {
                            **child_question,
                            "linked_via_node_ids": list(child_question.get("linked_via_node_ids") or []),
                            "is_direct_link": False,
                        }
                        continue
                    merged_via_ids = sorted(
                        {
                            *[str(item).strip() for item in existing.get("linked_via_node_ids") or [] if str(item).strip()],
                            *[str(item).strip() for item in child_question.get("linked_via_node_ids") or [] if str(item).strip()],
                        }
                    )
                    existing["linked_via_node_ids"] = merged_via_ids

            linked_questions = sorted(
                linked_question_map.values(),
                key=lambda item: str(item.get("question_id") or ""),
            )
            return {
                "node_id": node_id,
                "name": node.get("name"),
                "parent_id": node.get("parent_id"),
                "level": node.get("level"),
                "is_leaf": bool(node.get("is_leaf")),
                "node_kind": node.get("node_kind"),
                "path": node.get("path") or [],
                "path_text": node.get("path_text"),
                "aliases": node.get("aliases") or [],
                "common_errors": node.get("common_errors") or [],
                "typing_source": node.get("typing_source"),
                "is_custom": str(node.get("typing_source") or "").startswith("custom"),
                "linked_questions": linked_questions,
                "children": children,
            }

        tree = sorted(
            [attach_payload(root) for root in roots],
            key=lambda item: item.get("name") or item.get("node_id"),
        )
        return {
            "tree": tree,
            "note_count": len([value for value in self.tree_notes.values() if str(value).strip()]),
            "custom_node_count": len(custom_nodes),
        }

    def build_wrongbook_payload(self) -> dict[str, Any]:
        custom_nodes = list(self.tree_custom_nodes.get("nodes") or [])
        custom_questions = list(self.custom_question_states.get("questions") or [])
        node_lookup, roots = self._build_tree_node_graph()
        question_lookup = self._build_wrongbook_question_lookup()

        def attach_payload(node: dict[str, Any]) -> dict[str, Any]:
            node_id = node["node_id"]
            children = [
                attach_payload(child)
                for child in sorted(
                    node.get("children", []),
                    key=lambda item: (0 if item.get("is_leaf") else 1, item.get("name") or item.get("node_id")),
                )
            ]
            direct_question_map: dict[str, dict[str, Any]] = {}
            linked_question_map: dict[str, dict[str, Any]] = {}

            for question in question_lookup.values():
                linked_ids = question.get("linked_node_ids") or []
                if node_id not in linked_ids:
                    continue
                question_id = str(question.get("question_id") or "").strip()
                if not question_id:
                    continue
                question_view = self._build_question_view(
                    question,
                    matched_node_id=node_id,
                    direct=True,
                )
                direct_question_map[question_id] = question_view
                linked_question_map[question_id] = question_view

            for child in children:
                for child_question in child.get("linked_questions", []):
                    question_id = str(child_question.get("question_id") or "").strip()
                    if not question_id:
                        continue
                    existing = linked_question_map.get(question_id)
                    if existing is None:
                        linked_question_map[question_id] = {
                            **child_question,
                            "linked_via_node_ids": list(child_question.get("linked_via_node_ids") or []),
                            "is_direct_link": False,
                        }
                        continue
                    merged_via_ids = sorted(
                        {
                            *[
                                str(item).strip()
                                for item in existing.get("linked_via_node_ids") or []
                                if str(item).strip()
                            ],
                            *[
                                str(item).strip()
                                for item in child_question.get("linked_via_node_ids") or []
                                if str(item).strip()
                            ],
                        }
                    )
                    existing["linked_via_node_ids"] = merged_via_ids

            direct_questions = sorted(
                direct_question_map.values(),
                key=lambda item: str(item.get("question_id") or ""),
            )
            linked_questions = sorted(
                linked_question_map.values(),
                key=lambda item: str(item.get("question_id") or ""),
            )
            return {
                "node_id": node_id,
                "name": node.get("name"),
                "parent_id": node.get("parent_id"),
                "level": node.get("level"),
                "is_leaf": bool(node.get("is_leaf")),
                "node_kind": node.get("node_kind"),
                "path": node.get("path") or [],
                "path_text": node.get("path_text"),
                "aliases": node.get("aliases") or [],
                "common_errors": node.get("common_errors") or [],
                "typing_source": node.get("typing_source"),
                "is_custom": str(node.get("typing_source") or "").startswith("custom"),
                "question_count": len(linked_questions),
                "direct_question_count": len(direct_questions),
                "direct_questions": direct_questions,
                "linked_questions": linked_questions,
                "children": children,
                "has_wrong_questions": bool(linked_questions),
            }

        tree = [
            attach_payload(root)
            for root in sorted(roots, key=lambda item: item.get("name") or item.get("node_id"))
        ]

        def count_nodes(items: list[dict[str, Any]]) -> int:
            total = 0
            for item in items:
                total += 1 + count_nodes(item.get("children", []))
            return total

        def count_active_nodes(items: list[dict[str, Any]]) -> int:
            total = 0
            for item in items:
                total += (1 if item.get("question_count", 0) > 0 else 0) + count_active_nodes(
                    item.get("children", [])
                )
            return total

        question_count = len(question_lookup)
        node_count = count_nodes(tree)
        active_wrong_node_count = count_active_nodes(tree)
        return {
            "tree": tree,
            "question_count": question_count,
            "node_count": node_count,
            "active_wrong_node_count": active_wrong_node_count,
            "custom_question_count": len(custom_questions),
            "custom_node_count": len(custom_nodes),
            "note_count": len([value for value in self.tree_notes.values() if str(value).strip()]),
        }

    def save_question_note(self, *, question_id: str, note: str) -> dict[str, Any]:
        self.tree_notes[question_id] = note
        if self.using_database_store():
            self.store.save_question_note(self.student_id, question_id, note)
        self.persist_tree_state()
        return self.build_tree_payload()

    def save_wrongbook_note(self, *, question_id: str, note: str) -> dict[str, Any]:
        self.tree_notes[question_id] = note
        if self.using_database_store():
            self.store.save_question_note(self.student_id, question_id, note)
        self.persist_tree_state()
        return {
            "tree": self.build_tree_payload(),
            "wrongbook": self.build_wrongbook_payload(),
        }

    def create_custom_node(
        self,
        *,
        parent_node_id: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        parent_node_id = parent_node_id.strip()
        title = title.strip()
        if not parent_node_id or not title:
            raise ValueError("parent_node_id and title are required")
        existing_nodes = list(self.tree_inventory.get("nodes") or []) + list(self.tree_custom_nodes.get("nodes") or [])
        parent = next((node for node in existing_nodes if node.get("node_id") == parent_node_id), None)
        if parent is None:
            raise KeyError(f"Unknown parent node: {parent_node_id}")
        slug = title.replace(" ", "_").replace("/", "_")
        node_id = f"{parent_node_id}.{slug}"
        if any(node.get("node_id") == node_id for node in existing_nodes):
            raise ValueError("Custom node already exists")
        parent_path = list(parent.get("path") or [parent.get("name") or parent_node_id])
        node = {
            "node_id": node_id,
            "name": title,
            "parent_id": parent_node_id,
            "level": int(parent.get("level") or 0) + 1,
            "is_leaf": True,
            "node_kind": "custom",
            "review_role": "core",
            "binding_role": "primary_allowed",
            "path": parent_path + [title],
            "path_text": " > ".join(parent_path + [title]),
            "aliases": [],
            "prerequisites": [],
            "common_errors": [description] if description else [],
            "typing_source": "custom_ui",
        }
        self.tree_custom_nodes.setdefault("nodes", []).append(node)
        if self.using_database_store():
            self.store.save_custom_node(self.student_id, node)
        self.persist_tree_state()
        return self.build_tree_payload()

    def create_wrongbook_node(
        self,
        *,
        parent_node_id: str,
        title: str,
        description: str,
    ) -> dict[str, Any]:
        self.create_custom_node(
            parent_node_id=parent_node_id,
            title=title,
            description=description,
        )
        return {
            "tree": self.build_tree_payload(),
            "wrongbook": self.build_wrongbook_payload(),
        }

    def add_wrongbook_question(
        self,
        *,
        primary_node_id: str,
        secondary_node_ids: list[str],
        question_id: str,
        question_type: str,
        stem: str,
        student_answer: str,
        correct_answer: str,
        solution_text: str,
        source_name: str,
        source_type: str,
        source_chapter: str,
        priority_note: str,
        note: str,
    ) -> dict[str, Any]:
        primary_node_id = primary_node_id.strip()
        stem = stem.strip()
        if not primary_node_id:
            raise ValueError("primary_node_id is required")
        if not stem:
            raise ValueError("stem is required")

        node_lookup = {
            str(node.get("node_id")): node
            for node in self._all_nodes()
            if isinstance(node, dict) and node.get("node_id")
        }
        if primary_node_id not in node_lookup:
            raise KeyError(f"Unknown node_id: {primary_node_id}")

        normalized_secondary = unique_str_list(secondary_node_ids)
        linked_node_ids = unique_str_list([primary_node_id] + normalized_secondary)
        unknown_ids = [node_id for node_id in linked_node_ids if node_id not in node_lookup]
        if unknown_ids:
            raise KeyError(f"Unknown linked node ids: {', '.join(unknown_ids)}")
        resolved_source_type = source_type.strip() or "manual_entry"

        explicit_question_id = question_id.strip()
        existing_ids = {
            str(item.get("question_id") or "").strip()
            for item in self.current_review_state.get("example_question_states", [])
            if isinstance(item, dict)
        }
        if explicit_question_id:
            if explicit_question_id in existing_ids:
                raise ValueError("question_id already exists")
            resolved_question_id = explicit_question_id
        else:
            counter = 1
            while True:
                candidate = f"wq_manual_{counter:03d}"
                if candidate not in existing_ids:
                    resolved_question_id = candidate
                    break
                counter += 1

        question_state = {
            "question_id": resolved_question_id,
            "state": "new",
            "linked_node_ids": linked_node_ids,
            "primary_node_ids": [primary_node_id],
            "secondary_node_ids": [node_id for node_id in linked_node_ids if node_id != primary_node_id],
            "source_batch_id": "wrongbook_manual_ui",
            "source_type": resolved_source_type,
            "question_payload": {
                "question_type": question_type.strip() or "未标注",
                "stem": stem,
                "student_answer": student_answer.strip(),
                "correct_answer": correct_answer.strip(),
                "solution_text": solution_text.strip(),
                "source_name": source_name.strip(),
                "source_type": resolved_source_type,
                "source_chapter": source_chapter.strip(),
            },
            "last_result": "wrong",
            "review_count": 0,
            "priority_note": priority_note.strip() or "学生手动加入错题本。",
        }
        self.custom_question_states.setdefault("questions", []).append(copy.deepcopy(question_state))
        self.current_review_state.setdefault("example_question_states", []).append(copy.deepcopy(question_state))
        self._ensure_review_nodes_for_question_state(question_state)
        if note.strip():
            self.tree_notes[resolved_question_id] = note.strip()
        self.persist_wrongbook_state()
        self.persist_tree_state()
        self.persist_session_state()
        self._log_binding_for_question_state(
            question_state,
            binding_source=(
                "student_created_new_node"
                if resolved_source_type == "manual_entry" and str(primary_node_id).count(".") > 3 and str(node_lookup[primary_node_id].get("typing_source") or "").startswith("custom")
                else "student_confirmed"
            ),
            candidate_node_ids=linked_node_ids,
            binding_confidence=1.0,
        )
        self._log_student_choice_for_question_state(
            question_state,
            action_type="attach_wrong_question",
            note=priority_note.strip() or note.strip() or "学生将题目挂到知识点下。",
        )
        return {
            "dashboard": self.build_dashboard_payload(mode=self.last_mode),
            "tree": self.build_tree_payload(),
            "wrongbook": self.build_wrongbook_payload(),
            "created_question_id": resolved_question_id,
        }

    def run_diagnosis(
        self,
        *,
        problem_text: str,
        reference_answer: str,
        student_answer: str,
        student_profile: str,
        max_turns: int = 8,
    ) -> dict[str, Any]:
        orchestrator = self.get_diagnosis_orchestrator()
        session = orchestrator.create_session(
            problem_text=problem_text,
            reference_answer=reference_answer,
            student_profile=student_profile,
            student_memory_profile=self.current_memory_profile,
            coach_max_turns=max(1, max_turns),
        )
        # App flow always gives the student one confirmation round before coach.
        session.direct_to_coach_confidence = 1.01
        result = orchestrator.start(student_answer, session=session)
        self.diagnosis_flow_session = session
        self.coach_chat_session = None
        self.coach_chat_history = []
        self.active_diagnosis_question_id = self._question_id_for_problem("diag", problem_text)
        self.active_coach_question_id = None
        self.last_coach_request = {}
        self.last_diagnosis_request = {
            "problem_text": problem_text,
            "reference_answer": reference_answer,
            "student_answer": student_answer,
            "student_profile": student_profile,
            "max_turns": max_turns,
        }
        self.diagnosis_chat_history = [
            {
                "role": "student",
                "kind": "initial_answer",
                "content": student_answer.strip(),
            }
        ]
        self.diagnosis_chat_history.append(
            self._build_diagnosis_assistant_message(result)
        )
        if result.diagnosis is not None:
            self._log_diagnosis_event(
                diagnosis_payload=result.diagnosis.as_dict(),
                question_id=self.active_diagnosis_question_id or self._question_id_for_problem("diag", problem_text),
                question_type=None,
                source_name="diagnosis_app_input",
                source_section="diagnosis",
                binding=None,
            )
        if self.using_database_store():
            self.store.save_diagnosis_flow(
                student_uid=self.student_id,
                diagnosis_uid=self._diagnosis_store_uid(),
                flow_payload=self.build_diagnosis_flow_payload(),
                request_payload=self.last_diagnosis_request,
                question_uid=self.active_diagnosis_question_id,
            )
        return {
            "environment": {
                "diagnosis_environment": diagnosis_environment(),
                "orchestrator_environment": orchestrator_environment(),
            },
            "flow": self.build_diagnosis_flow_payload(),
        }

    def continue_diagnosis(
        self,
        *,
        student_reply: str,
    ) -> dict[str, Any]:
        if self.diagnosis_flow_session is None:
            raise RuntimeError("No active diagnosis flow.")
        orchestrator = self.get_diagnosis_orchestrator()
        result = orchestrator.handle_student_reply(
            student_reply,
            session=self.diagnosis_flow_session,
        )
        self.diagnosis_chat_history.append(
            {
                "role": "student",
                "kind": "confirmation_reply",
                "content": student_reply.strip(),
            }
        )
        self.diagnosis_chat_history.append(
            self._build_diagnosis_assistant_message(result)
        )
        if result.action == "enter_coach":
            self.coach_chat_session = result.coach_session
            self.active_coach_question_id = self.active_diagnosis_question_id
        if result.diagnosis is not None:
            self._log_diagnosis_event(
                diagnosis_payload=result.diagnosis.as_dict(),
                question_id=self.active_diagnosis_question_id or "diag_unknown",
                question_type=None,
                source_name="diagnosis_app_followup",
                source_section="diagnosis",
                binding=None,
            )
        if self.using_database_store():
            self.store.save_diagnosis_flow(
                student_uid=self.student_id,
                diagnosis_uid=self._diagnosis_store_uid(),
                flow_payload=self.build_diagnosis_flow_payload(),
                request_payload=self.last_diagnosis_request,
                question_uid=self.active_diagnosis_question_id,
            )
        return {
            "environment": {
                "diagnosis_environment": diagnosis_environment(),
                "orchestrator_environment": orchestrator_environment(),
            },
            "flow": self.build_diagnosis_flow_payload(),
        }

    def cancel_diagnosis_flow(self) -> dict[str, Any]:
        diagnosis_question_id = self.active_diagnosis_question_id
        self.diagnosis_flow_session = None
        self.diagnosis_chat_history = []
        self.active_diagnosis_question_id = None
        if (
            diagnosis_question_id
            and self.active_coach_question_id == diagnosis_question_id
            and not self.coach_chat_history
        ):
            self.coach_chat_session = None
            self.active_coach_question_id = None
            self.last_coach_request = {}
        return {
            "flow": self.build_diagnosis_flow_payload(),
        }

    def start_coach(
        self,
        *,
        problem_text: str,
        error_type: str,
        student_reply: str,
        student_profile: str,
        max_turns: int,
    ) -> dict[str, Any]:
        agent = self.get_coach_agent()
        session = agent.create_session(
            problem_text=problem_text,
            error_type=error_type,
            student_profile=student_profile,
            student_memory_profile=self.current_memory_profile,
            max_turns=max_turns,
        )
        self.coach_chat_session = session
        self.coach_chat_history = []
        self.active_coach_question_id = self._question_id_for_problem("coach", problem_text)
        self.last_coach_request = {
            "problem_text": problem_text,
            "error_type": error_type,
            "student_profile": student_profile,
            "max_turns": max_turns,
        }
        response = agent.reply(student_reply, session=session)
        self.coach_chat_history.append(
            {
                "role": "student",
                "kind": "reply",
                "content": student_reply.strip(),
            }
        )
        self.coach_chat_history.append(
            self._build_coach_assistant_message(response)
        )
        self._log_coach_event(
            coach_payload=response.as_dict(),
            question_id=self.active_coach_question_id or self._question_id_for_problem("coach", problem_text),
            question_type=None,
            error_type=error_type,
            source_name="coach_app_input",
            source_section="coach",
            binding=None,
        )
        if self.using_database_store():
            self.store.save_coach_chat(
                student_uid=self.student_id,
                coach_uid=self._coach_store_uid(),
                chat_payload=self.build_coach_chat_payload(),
                request_payload=self.last_coach_request,
                question_uid=self.active_coach_question_id,
            )
        return {
            "environment": diagnose_environment(),
            "chat": self.build_coach_chat_payload(),
        }

    def continue_coach(
        self,
        *,
        student_reply: str,
    ) -> dict[str, Any]:
        if self.coach_chat_session is None:
            raise RuntimeError("No active coach session.")
        response = self.get_coach_agent().reply(student_reply, session=self.coach_chat_session)
        self.coach_chat_history.append(
            {
                "role": "student",
                "kind": "reply",
                "content": student_reply.strip(),
            }
        )
        self.coach_chat_history.append(
            self._build_coach_assistant_message(response)
        )
        self._log_coach_event(
            coach_payload=response.as_dict(),
            question_id=self.active_coach_question_id or "coach_unknown",
            question_type=None,
            error_type=(self.coach_chat_session.error_type.value if self.coach_chat_session is not None else None),
            source_name="coach_app_followup",
            source_section="coach",
            binding=None,
        )
        if self.using_database_store():
            self.store.save_coach_chat(
                student_uid=self.student_id,
                coach_uid=self._coach_store_uid(),
                chat_payload=self.build_coach_chat_payload(),
                request_payload=self.last_coach_request,
                question_uid=self.active_coach_question_id,
            )
        return {
            "environment": diagnose_environment(),
            "chat": self.build_coach_chat_payload(),
        }

    def resume_coach(self) -> dict[str, Any]:
        if self.coach_chat_session is None:
            raise RuntimeError("No active coach session.")
        self.coach_chat_session.done = False
        self.coach_chat_session.stop_reason = "continue"
        return {
            "environment": diagnose_environment(),
            "chat": self.build_coach_chat_payload(),
        }

    def cancel_coach(self) -> dict[str, Any]:
        self.coach_chat_session = None
        self.coach_chat_history = []
        self.active_coach_question_id = None
        return {
            "chat": self.build_coach_chat_payload(),
        }

    def start_coach_from_diagnosis(self) -> dict[str, Any]:
        if self.diagnosis_flow_session is None:
            raise RuntimeError("No active diagnosis flow.")
        pending = self.diagnosis_flow_session.pending_diagnosis
        if pending is None:
            raise RuntimeError("Diagnosis result is not ready.")
        result: OrchestratorResult | None = None
        if self.active_coach_question_id != self.active_diagnosis_question_id:
            self.coach_chat_session = None
            self.coach_chat_history = []

        if self.coach_chat_session is None:
            if self.diagnosis_flow_session.coach_session is not None:
                self.coach_chat_session = self.diagnosis_flow_session.coach_session
            else:
                orchestrator = self.get_diagnosis_orchestrator()
                result = orchestrator._enter_coach(  # noqa: SLF001 - app MVP directly reuses orchestrator state transition
                    pending,
                    session=self.diagnosis_flow_session,
                    confirmation_analysis=None,
                    forced=True,
                )
                self.coach_chat_session = result.coach_session
                self.diagnosis_chat_history.append(
                    self._build_diagnosis_assistant_message(result)
                )
        self.active_coach_question_id = self.active_diagnosis_question_id
        self.diagnosis_flow_session.coach_session = self.coach_chat_session
        self.last_coach_request = {
            "problem_text": (
                getattr(self.coach_chat_session, "problem_text", "")
                if self.coach_chat_session is not None
                else ""
            ),
            "error_type": (
                self.coach_chat_session.error_type.value
                if self.coach_chat_session is not None
                else None
            ),
            "student_profile": "",
            "max_turns": (
                int(self.coach_chat_session.max_turns)
                if self.coach_chat_session is not None
                else 0
            ),
        }
        if self.coach_chat_session is not None and not self.coach_chat_history:
            initial_reply = (
                (
                    result.coach_initial_student_reply
                    if result is not None
                    else getattr(self.coach_chat_session, "initial_student_reply", "")
                )
                or getattr(self.coach_chat_session, "initial_student_reply", "")
                or "我不会"
            ).strip()
            coach_response = self.get_coach_agent().start(self.coach_chat_session, student_reply=initial_reply)
            self.coach_chat_history.append(
                {
                    "role": "student",
                    "kind": "reply",
                    "content": initial_reply,
                }
            )
            self.coach_chat_history.append(
                self._build_coach_assistant_message(coach_response)
            )
            self._log_coach_event(
                coach_payload=coach_response.as_dict(),
                question_id=self.active_coach_question_id or "coach_unknown",
                question_type=None,
                error_type=(self.coach_chat_session.error_type.value if self.coach_chat_session is not None else None),
                source_name="diagnosis_to_coach",
                source_section="coach",
                binding=None,
            )
            if self.using_database_store():
                self.store.save_coach_chat(
                    student_uid=self.student_id,
                    coach_uid=self._coach_store_uid(),
                    chat_payload=self.build_coach_chat_payload(),
                    request_payload=self.last_coach_request,
                    question_uid=self.active_coach_question_id,
                )
        if self.using_database_store():
            self.store.save_diagnosis_flow(
                student_uid=self.student_id,
                diagnosis_uid=self._diagnosis_store_uid(),
                flow_payload=self.build_diagnosis_flow_payload(),
                request_payload=self.last_diagnosis_request,
                question_uid=self.active_diagnosis_question_id,
            )
        return {
            "environment": {
                "diagnosis_environment": diagnosis_environment(),
                "orchestrator_environment": orchestrator_environment(),
            },
            "flow": self.build_diagnosis_flow_payload(),
            "chat": self.build_coach_chat_payload(),
        }

    def build_diagnosis_flow_payload(self) -> dict[str, Any]:
        session = self.diagnosis_flow_session
        pending = session.pending_diagnosis.as_dict() if session and session.pending_diagnosis else None
        coach_ready = bool(session and session.coach_session is not None)
        return {
            "active": session is not None,
            "phase": session.phase if session is not None else "idle",
            "stop_reason": session.stop_reason if session is not None else None,
            "pending_diagnosis": pending,
            "chat_history": copy.deepcopy(self.diagnosis_chat_history) if session is not None else [],
            "can_continue": bool(session and session.phase == "await_confirmation" and not session.done),
            "can_enter_coach": coach_ready or bool(session and pending),
            "coach_ready": coach_ready,
        }

    def build_coach_chat_payload(self) -> dict[str, Any]:
        session = self.coach_chat_session
        return {
            "active": session is not None,
            "done": bool(session.done) if session is not None else False,
            "stop_reason": session.stop_reason if session is not None else None,
            "turn_index": int(session.turn_index) if session is not None else 0,
            "max_turns": int(session.max_turns) if session is not None else 0,
            "stuck_turns": int(getattr(session, "consecutive_stuck_turns", 0)) if session is not None else 0,
            "problem_text": session.problem_text if session is not None else "",
            "error_type": session.error_type.value if session is not None else "",
            "student_profile": session.student_profile if session is not None else "",
            "chat_history": copy.deepcopy(self.coach_chat_history) if session is not None else [],
        }

    def _build_diagnosis_assistant_message(
        self,
        result: OrchestratorResult,
    ) -> dict[str, Any]:
        diagnosis = result.diagnosis.as_dict() if result.diagnosis is not None else None
        confirmation = (
            result.confirmation_analysis.as_dict()
            if result.confirmation_analysis is not None
            else None
        )
        return {
            "role": "assistant",
            "kind": "diagnosis_result",
            "content": (
                "这轮诊断已经完成，你可以先确认是否说中了你的卡点；如果认可，也可以直接进入 coach。"
                if result.action == "enter_coach"
                else result.content
            ),
            "action": result.action,
            "stop_reason": result.stop_reason,
            "diagnosis": diagnosis,
            "confirmation_analysis": confirmation,
            "coach_ready": result.action == "enter_coach",
        }

    def _build_coach_assistant_message(self, response) -> dict[str, Any]:
        payload = response.as_dict()
        closing = ""
        if payload.get("stop_reason") == "continue":
            closing = "请继续。"
        elif payload.get("stop_reason") == "student_understood":
            closing = "这一题先收在这里，希望这轮讲解对你有帮助。"
        elif payload.get("stop_reason") == "max_turns":
            closing = "这轮先到这里，你可以返回重输，或者稍后继续整理思路。"
        content = payload.get("content", "").strip()
        if closing and closing not in content:
            content = f"{content}\n{closing}".strip()
        payload["content"] = content
        return {
            "role": "assistant",
            "kind": "coach_reply",
            "content": content,
            "response": payload,
        }

APP_STATE: ReviewAppState | None = None


def get_app_state() -> ReviewAppState:
    global APP_STATE
    if APP_STATE is None:
        APP_STATE = ReviewAppState()
    return APP_STATE


class TeachAgentAppHandler(BaseHTTPRequestHandler):
    server_version = "TeachAgentApp/0.1"

    def do_GET(self) -> None:
        state = get_app_state()
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.serve_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            return
        if parsed.path == "/styles.css":
            self.serve_file(STATIC_DIR / "styles.css", "text/css; charset=utf-8")
            return
        if parsed.path == "/app.js":
            self.serve_file(
                STATIC_DIR / "app.js",
                "application/javascript; charset=utf-8",
            )
            return
        if parsed.path == "/healthz":
            self.respond_json(
                {
                    "status": "ok",
                    "student_id": state.student_id,
                    "storage_label": (
                        "PostgreSQL" if state.using_database_store() else "本地 JSON"
                    ),
                    "database_enabled": state.using_database_store(),
                }
            )
            return
        if parsed.path == "/api/dashboard":
            params = parse_qs(parsed.query)
            mode = first_query_value(params, "mode")
            now_value = first_query_value(params, "now")
            self.respond_json(
                state.build_dashboard_payload(mode=mode, now_value=now_value)
            )
            return
        if parsed.path == "/api/student":
            self.respond_json(state.build_student_payload())
            return
        if parsed.path == "/api/students":
            self.respond_json({"students": state.list_student_summaries()})
            return
        if parsed.path == "/api/tree":
            self.respond_json(state.build_tree_payload())
            return
        if parsed.path == "/api/wrongbook":
            self.respond_json(state.build_wrongbook_payload())
            return
        if parsed.path == "/api/agent-meta":
            self.respond_json(
                {
                    "diagnosis_environment": diagnosis_environment(),
                    "coach_environment": diagnose_environment(),
                    "orchestrator_environment": orchestrator_environment(),
                }
            )
            return
        if parsed.path == "/api/diagnosis/state":
            self.respond_json({"flow": state.build_diagnosis_flow_payload()})
            return
        if parsed.path == "/api/coach/state":
            self.respond_json({"chat": state.build_coach_chat_payload()})
            return
        if parsed.path == "/api/reset":
            self.respond_json(state.reset())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        state = get_app_state()
        parsed = urlparse(self.path)
        if parsed.path not in {
            "/api/action",
            "/api/student/switch",
            "/api/ocr/extract",
            "/api/import/polish-answer",
            "/api/diagnosis",
            "/api/diagnosis/continue",
            "/api/diagnosis/cancel",
            "/api/diagnosis/to-coach",
            "/api/coach",
            "/api/coach/continue",
            "/api/coach/resume",
            "/api/coach/cancel",
            "/api/tree/note",
            "/api/tree/node",
            "/api/wrongbook/note",
            "/api/wrongbook/node",
            "/api/wrongbook/question",
        }:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        try:
            if parsed.path == "/api/ocr/extract":
                fields, files = self.read_multipart_form_body()
                uploads = [
                    file_payload
                    for key, file_payload in files.items()
                    if key == "file" or key.startswith("file_")
                ]
                if not uploads:
                    upload = files.get("file")
                    if upload is not None:
                        uploads = [upload]
                if not uploads:
                    raise ValueError("file is required")
                response = build_ocr_extract_response(
                    target=str(fields.get("target") or "").strip() or "wrongbook",
                    field_mode=str(fields.get("field_mode") or "").strip() or "auto",
                    uploads=uploads,
                )
            else:
                payload = self.read_json_body()
                if parsed.path == "/api/action":
                    action = str(payload.get("action") or "").strip()
                    target_type = str(payload.get("target_type") or "").strip()
                    target_id = str(payload.get("target_id") or "").strip()
                    result = payload.get("result")
                    mode = payload.get("mode")
                    if not action or not target_type or not target_id:
                        raise ValueError("action, target_type, target_id are required")
                    response = state.apply_action(
                        action=action,
                        target_type=target_type,
                        target_id=target_id,
                        result=result,
                        mode=mode,
                    )
                elif parsed.path == "/api/student/switch":
                    response = state.switch_student(
                        str(payload.get("student_id") or "").strip()
                    )
                elif parsed.path == "/api/import/polish-answer":
                    response = state.polish_answer_and_solution(
                        question_text=str(payload.get("question_text") or "").strip(),
                        answer_text=str(payload.get("answer_text") or "").strip(),
                        solution_text=str(payload.get("solution_text") or "").strip(),
                    )
                elif parsed.path == "/api/diagnosis":
                    response = state.run_diagnosis(
                        problem_text=str(payload.get("problem_text") or "").strip(),
                        reference_answer=str(payload.get("reference_answer") or "").strip(),
                        student_answer=str(payload.get("student_answer") or "").strip(),
                        student_profile=str(payload.get("student_profile") or "").strip(),
                        max_turns=max(int(payload.get("max_turns") or 8), 1),
                    )
                elif parsed.path == "/api/diagnosis/continue":
                    response = state.continue_diagnosis(
                        student_reply=str(payload.get("student_reply") or "").strip(),
                    )
                elif parsed.path == "/api/diagnosis/cancel":
                    response = state.cancel_diagnosis_flow()
                elif parsed.path == "/api/diagnosis/to-coach":
                    response = state.start_coach_from_diagnosis()
                elif parsed.path == "/api/tree/note":
                    response = state.save_question_note(
                        question_id=str(payload.get("question_id") or "").strip(),
                        note=str(payload.get("note") or ""),
                    )
                elif parsed.path == "/api/tree/node":
                    response = state.create_custom_node(
                        parent_node_id=str(payload.get("parent_node_id") or "").strip(),
                        title=str(payload.get("title") or "").strip(),
                        description=str(payload.get("description") or "").strip(),
                    )
                elif parsed.path == "/api/wrongbook/note":
                    response = state.save_wrongbook_note(
                        question_id=str(payload.get("question_id") or "").strip(),
                        note=str(payload.get("note") or ""),
                    )
                elif parsed.path == "/api/wrongbook/node":
                    response = state.create_wrongbook_node(
                        parent_node_id=str(payload.get("parent_node_id") or "").strip(),
                        title=str(payload.get("title") or "").strip(),
                        description=str(payload.get("description") or "").strip(),
                    )
                elif parsed.path == "/api/wrongbook/question":
                    raw_secondary = payload.get("secondary_node_ids") or []
                    if isinstance(raw_secondary, str):
                        raw_secondary = [
                            item.strip()
                            for item in raw_secondary.replace("，", ",").split(",")
                            if item.strip()
                        ]
                    response = state.add_wrongbook_question(
                        primary_node_id=str(payload.get("primary_node_id") or "").strip(),
                        secondary_node_ids=[
                            str(item).strip()
                            for item in raw_secondary
                            if str(item).strip()
                        ],
                        question_id=str(payload.get("question_id") or "").strip(),
                        question_type=str(payload.get("question_type") or "").strip(),
                        stem=str(payload.get("stem") or "").strip(),
                        student_answer=str(payload.get("student_answer") or "").strip(),
                        correct_answer=str(payload.get("correct_answer") or "").strip(),
                        solution_text=str(payload.get("solution_text") or "").strip(),
                        source_name=str(payload.get("source_name") or "").strip(),
                        source_type=str(payload.get("source_type") or "").strip(),
                        source_chapter=str(payload.get("source_chapter") or "").strip(),
                        priority_note=str(payload.get("priority_note") or "").strip(),
                        note=str(payload.get("note") or "").strip(),
                    )
                elif parsed.path == "/api/coach":
                    response = state.start_coach(
                        problem_text=str(payload.get("problem_text") or "").strip(),
                        error_type=str(payload.get("error_type") or "concept_gap").strip(),
                        student_reply=str(payload.get("student_reply") or "").strip(),
                        student_profile=str(payload.get("student_profile") or "").strip(),
                        max_turns=max(int(payload.get("max_turns") or 8), 1),
                    )
                elif parsed.path == "/api/coach/continue":
                    response = state.continue_coach(
                        student_reply=str(payload.get("student_reply") or "").strip(),
                    )
                elif parsed.path == "/api/coach/resume":
                    response = state.resume_coach()
                elif parsed.path == "/api/coach/cancel":
                    response = state.cancel_coach()
                else:
                    raise ValueError(f"Unsupported endpoint: {parsed.path}")
        except Exception as exc:
            self.respond_json(
                {
                    "error": str(exc),
                },
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        self.respond_json(response)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(content)

    def respond_json(self, payload: dict[str, Any], *, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def read_multipart_form_body(self) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Expected multipart/form-data upload.")
        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
        }
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ=environ,
            keep_blank_values=True,
        )
        fields: dict[str, str] = {}
        files: dict[str, dict[str, Any]] = {}
        for item in form.list or []:
            if item.filename:
                file_content = item.file.read() if item.file is not None else b""
                files[item.name] = {
                    "filename": Path(item.filename).name,
                    "content": file_content,
                    "content_type": item.type,
                }
            else:
                fields[item.name] = item.value
        return fields, files


def first_query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


def env_flag(name: str) -> bool | None:
    load_teachagent_env()
    raw_value = str(os.getenv(name) or "").strip().lower()
    if not raw_value:
        return None
    if raw_value in TRUTHY_TEXT:
        return True
    if raw_value in FALSY_TEXT:
        return False
    raise ValueError(f"Invalid boolean environment value for {name}: {raw_value}")


def should_use_default_credential() -> bool:
    explicit = env_flag("TEACHAGENT_USE_DEFAULT_CREDENTIAL")
    if explicit is not None:
        return explicit
    if all(
        str(os.getenv(key) or "").strip()
        for key in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID")
    ) and any(
        str(os.getenv(key) or "").strip()
        for key in ("AZURE_CLIENT_SECRET", "AZURE_FEDERATED_TOKEN_FILE", "IDENTITY_ENDPOINT")
    ):
        return True
    return any(
        str(os.getenv(key) or "").strip()
        for key in (
            "WEBSITE_HOSTNAME",
            "RENDER",
            "RENDER_SERVICE_ID",
            "RAILWAY_PROJECT_ID",
            "K_SERVICE",
        )
    )


def resolve_server_host() -> str:
    load_teachagent_env()
    raw_host = (
        str(os.getenv("TEACHAGENT_HOST") or "").strip()
        or str(os.getenv("HOST") or "").strip()
    )
    if raw_host:
        return raw_host
    raw_port = (
        str(os.getenv("TEACHAGENT_PORT") or "").strip()
        or str(os.getenv("PORT") or "").strip()
    )
    if raw_port:
        return DEFAULT_DEPLOY_HOST
    return DEFAULT_SERVER_HOST


def resolve_server_port() -> int:
    load_teachagent_env()
    raw_port = (
        str(os.getenv("TEACHAGENT_PORT") or "").strip()
        or str(os.getenv("PORT") or "").strip()
    )
    if not raw_port:
        return DEFAULT_SERVER_PORT
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError(f"Invalid port value: {raw_port}") from exc
    if port < 0 or port > 65535:
        raise ValueError(f"Port out of range: {port}")
    return port


def normalize_server_config(*, host: str | None, port: int | None) -> tuple[str, int]:
    resolved_host = str(host or "").strip() or resolve_server_host()
    resolved_port = resolve_server_port() if port is None else int(port)
    if resolved_port < 0 or resolved_port > 65535:
        raise ValueError(f"Port out of range: {resolved_port}")
    return resolved_host, resolved_port


def display_url_for_host(host: str, port: int) -> str:
    visible_host = "127.0.0.1" if host == DEFAULT_DEPLOY_HOST else host
    return f"http://{visible_host}:{port}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the TeachAgent web server.")
    parser.add_argument("--host", help="Bind host. Defaults to env or local/cloud sensible defaults.")
    parser.add_argument("--port", type=int, help="Bind port. Defaults to TEACHAGENT_PORT / PORT / 8765.")
    return parser


def create_server(
    *,
    host: str = DEFAULT_SERVER_HOST,
    port: int = DEFAULT_SERVER_PORT,
) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), TeachAgentAppHandler)


def main() -> None:
    load_teachagent_env()
    args = build_parser().parse_args()
    host, port = normalize_server_config(host=args.host, port=args.port)
    server = create_server(host=host, port=port)
    bound_port = int(server.server_address[1])
    print(
        f"TeachAgent app running at {display_url_for_host(host, bound_port)} "
        f"(bind {host}:{bound_port})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nTeachAgent app stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

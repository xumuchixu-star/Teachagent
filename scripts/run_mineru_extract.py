from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "scratch" / "mineru_runs"
DEFAULT_VENV_MINERU = PROJECT_ROOT / ".venv_mineru" / "bin" / "mineru"
PREFERRED_JSON_KEYS = {
    "text",
    "content",
    "latex",
    "caption",
    "title",
    "html",
    "value",
}


def slugify(value: str) -> str:
    normalized = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", value.strip(), flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "mineru_run"


def resolve_mineru_binary() -> Path:
    if DEFAULT_VENV_MINERU.exists():
        return DEFAULT_VENV_MINERU
    system_path = shutil.which("mineru")
    if system_path:
        return Path(system_path)
    raise FileNotFoundError(
        "MinerU executable not found. Expected it at "
        f"{DEFAULT_VENV_MINERU} or in PATH."
    )


def markdown_to_text(markdown: str) -> str:
    text = markdown
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"^[#>*\-\s]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def flatten_json_strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(flatten_json_strings(item))
        return parts
    if isinstance(value, dict):
        parts: list[str] = []
        for key, nested in value.items():
            if key in PREFERRED_JSON_KEYS:
                parts.extend(flatten_json_strings(nested))
            elif isinstance(nested, (dict, list)):
                parts.extend(flatten_json_strings(nested))
        return parts
    return []


def choose_primary_markdown(paths: list[Path]) -> Path | None:
    markdown_paths = [path for path in paths if path.suffix.lower() == ".md"]
    if not markdown_paths:
        return None
    markdown_paths.sort(key=lambda path: (len(path.parts), len(path.name), str(path)))
    return markdown_paths[0]


def choose_primary_json(paths: list[Path]) -> Path | None:
    json_paths = [path for path in paths if path.suffix.lower() == ".json"]
    if not json_paths:
        return None

    def sort_key(path: Path) -> tuple[int, int, str]:
        score = 0
        lower_name = path.name.lower()
        if "content" in lower_name:
            score -= 3
        if "middle" in lower_name:
            score -= 2
        if "model" in lower_name:
            score += 2
        return (score, len(path.parts), str(path))

    json_paths.sort(key=sort_key)
    return json_paths[0]


def build_preview_text(output_files: list[Path]) -> tuple[str, str | None]:
    primary_markdown = choose_primary_markdown(output_files)
    if primary_markdown is not None:
        markdown = primary_markdown.read_text(encoding="utf-8", errors="ignore")
        return markdown_to_text(markdown), str(primary_markdown)

    primary_json = choose_primary_json(output_files)
    if primary_json is not None:
        raw = json.loads(primary_json.read_text(encoding="utf-8", errors="ignore"))
        text = "\n".join(flatten_json_strings(raw)).strip()
        return text, str(primary_json)

    plain_text_files = [path for path in output_files if path.suffix.lower() == ".txt"]
    if plain_text_files:
        plain_text_files.sort(key=lambda path: (len(path.parts), len(path.name), str(path)))
        text = plain_text_files[0].read_text(encoding="utf-8", errors="ignore").strip()
        return text, str(plain_text_files[0])

    return "", None


def collect_output_files(output_dir: Path) -> list[Path]:
    return sorted(
        [path for path in output_dir.rglob("*") if path.is_file()],
        key=lambda path: str(path),
    )


def build_run_dir(output_root: Path, input_path: Path, run_name: str | None) -> Path:
    if run_name:
        name = slugify(run_name)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = f"{timestamp}_{slugify(input_path.stem)}"
    return output_root / name


def run_mineru(
    *,
    mineru_binary: Path,
    input_path: Path,
    output_dir: Path,
    backend: str,
    lang: str,
    method: str | None,
    api_url: str | None,
    formula: bool,
    table: bool,
) -> subprocess.CompletedProcess[str]:
    cmd = [
        str(mineru_binary),
        "-p",
        str(input_path),
        "-o",
        str(output_dir),
        "-b",
        backend,
        "-l",
        lang,
    ]
    if method:
        cmd.extend(["-m", method])
    if api_url:
        cmd.extend(["--api-url", api_url])
    cmd.extend(["-f", "true" if formula else "false"])
    cmd.extend(["-t", "true" if table else "false"])

    env = os.environ.copy()
    env.setdefault("MINERU_MODEL_SOURCE", "modelscope")
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def write_run_summary(
    *,
    output_dir: Path,
    input_path: Path,
    mineru_binary: Path,
    backend: str,
    lang: str,
    method: str | None,
    formula: bool,
    table: bool,
    stdout_text: str,
    stderr_text: str,
    output_files: list[Path],
    preview_text: str,
    preview_source_path: str | None,
) -> dict[str, Any]:
    summary = {
        "input_path": str(input_path),
        "run_dir": str(output_dir),
        "mineru_binary": str(mineru_binary),
        "backend": backend,
        "lang": lang,
        "method": method or "auto",
        "formula": formula,
        "table": table,
        "generated_file_count": len(output_files),
        "generated_files": [str(path) for path in output_files],
        "preview_source_path": preview_source_path,
        "preview_text_path": str(output_dir / "ocr_preview.txt"),
        "stdout_path": str(output_dir / "mineru_stdout.log"),
        "stderr_path": str(output_dir / "mineru_stderr.log"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    (output_dir / "mineru_stdout.log").write_text(stdout_text, encoding="utf-8")
    (output_dir / "mineru_stderr.log").write_text(stderr_text, encoding="utf-8")
    (output_dir / "ocr_preview.txt").write_text(preview_text + "\n", encoding="utf-8")
    (output_dir / "ocr_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run MinerU on a local PDF/image and save OCR artifacts to scratch."
    )
    parser.add_argument("--input", required=True, help="Input PDF/image/docx path.")
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Root directory for MinerU run outputs.",
    )
    parser.add_argument("--run-name", help="Optional custom run directory name.")
    parser.add_argument(
        "--backend",
        default="pipeline",
        choices=[
            "pipeline",
            "vlm-engine",
            "hybrid-engine",
            "vlm-http-client",
            "hybrid-http-client",
        ],
        help="MinerU backend.",
    )
    parser.add_argument(
        "--lang",
        default="ch",
        help="Document language for OCR. For math Chinese notes, default is ch.",
    )
    parser.add_argument(
        "--method",
        choices=["auto", "txt", "ocr"],
        help="Optional MinerU parse method override.",
    )
    parser.add_argument(
        "--formula",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Whether to enable formula parsing. Default: true.",
    )
    parser.add_argument(
        "--table",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Whether to enable table parsing. Default: false for math question OCR.",
    )
    parser.add_argument(
        "--api-url",
        help="Optional MinerU FastAPI base URL. Leave empty to use local service.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing run directory.",
    )
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    output_root = Path(args.output_root).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = build_run_dir(output_root, input_path, args.run_name)
    if run_dir.exists():
        if not args.force:
            raise FileExistsError(
                f"Run directory already exists: {run_dir}. Pass --force or change --run-name."
            )
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    mineru_binary = resolve_mineru_binary()
    completed = run_mineru(
        mineru_binary=mineru_binary,
        input_path=input_path,
        output_dir=run_dir,
        backend=args.backend,
        lang=args.lang,
        method=args.method if args.method != "auto" else None,
        api_url=args.api_url,
        formula=args.formula,
        table=args.table,
    )

    output_files = collect_output_files(run_dir)
    preview_text, preview_source_path = build_preview_text(output_files)
    summary = write_run_summary(
        output_dir=run_dir,
        input_path=input_path,
        mineru_binary=mineru_binary,
        backend=args.backend,
        lang=args.lang,
        method=args.method,
        formula=args.formula,
        table=args.table,
        stdout_text=completed.stdout,
        stderr_text=completed.stderr,
        output_files=output_files,
        preview_text=preview_text,
        preview_source_path=preview_source_path,
    )
    summary["returncode"] = completed.returncode
    (run_dir / "ocr_run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "MinerU extraction failed. Check "
            f"{run_dir / 'mineru_stderr.log'} and {run_dir / 'mineru_stdout.log'}."
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

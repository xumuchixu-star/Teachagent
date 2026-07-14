from __future__ import annotations

import argparse
import cgi
import json
import os
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import sys
import traceback
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4


def resolve_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parents[1]


ROOT = resolve_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_mineru_extract import (
    DEFAULT_OUTPUT_ROOT,
    build_preview_text,
    build_run_dir,
    collect_output_files,
    resolve_mineru_binary,
    run_mineru,
    slugify,
    write_run_summary,
)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".heic", ".heif"}
UPLOAD_DIR = ROOT / "scratch" / "ocr_service_uploads"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8890


def now_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def env_bool(name: str, default: bool) -> bool:
    raw_value = str(os.getenv(name) or "").strip().lower()
    if not raw_value:
        return default
    if raw_value in {"1", "true", "yes", "y", "on"}:
        return True
    if raw_value in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"Invalid boolean environment value for {name}: {raw_value}")


def save_uploaded_file(*, filename: str, content: bytes) -> Path:
    suffix = Path(filename).suffix
    safe_stem = slugify(Path(filename).stem)
    target_dir = UPLOAD_DIR / now_slug()
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{safe_stem}_{uuid4().hex[:8]}{suffix}"
    target_path.write_bytes(content)
    return target_path


def build_health_payload() -> dict[str, Any]:
    try:
        mineru_binary = resolve_mineru_binary()
    except Exception as exc:
        return {
            "status": "ok",
            "provider": "MinerU",
            "available": False,
            "message": str(exc),
        }
    return {
        "status": "ok",
        "provider": "MinerU",
        "available": True,
        "message": "独立 OCR 服务已就绪。",
        "mineru_binary": str(mineru_binary),
    }


def perform_ocr(upload_path: Path, *, target: str) -> tuple[dict[str, Any], str]:
    output_root = Path(
        str(os.getenv("OCR_SERVICE_OUTPUT_ROOT") or DEFAULT_OUTPUT_ROOT)
    ).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    run_name = f"service_{target}_{now_slug()}_{slugify(upload_path.stem)}"
    run_dir = build_run_dir(output_root, upload_path, run_name)
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    method = "ocr" if upload_path.suffix.lower() in IMAGE_SUFFIXES else None
    backend = str(os.getenv("OCR_SERVICE_MINERU_BACKEND") or "pipeline").strip() or "pipeline"
    lang = str(os.getenv("OCR_SERVICE_MINERU_LANG") or "ch").strip() or "ch"
    api_url = str(os.getenv("OCR_SERVICE_MINERU_API_URL") or "").strip() or None
    formula = env_bool("OCR_SERVICE_ENABLE_FORMULA", True)
    table = env_bool("OCR_SERVICE_ENABLE_TABLE", False)

    mineru_binary = resolve_mineru_binary()
    completed = run_mineru(
        mineru_binary=mineru_binary,
        input_path=upload_path,
        output_dir=run_dir,
        backend=backend,
        lang=lang,
        method=method,
        api_url=api_url,
        formula=formula,
        table=table,
    )

    output_files = collect_output_files(run_dir)
    preview_text, preview_source_path = build_preview_text(output_files)
    summary = write_run_summary(
        output_dir=run_dir,
        input_path=upload_path,
        mineru_binary=mineru_binary,
        backend=backend,
        lang=lang,
        method=method,
        formula=formula,
        table=table,
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
            "MinerU extraction failed. "
            f"Check {run_dir / 'mineru_stderr.log'} and {run_dir / 'mineru_stdout.log'}."
        )
    return summary, preview_text


class OcrServiceHandler(BaseHTTPRequestHandler):
    server_version = "TeachAgentOCRService/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self.respond_json(build_health_payload())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/extract":
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        try:
            fields, files = self.read_multipart_form_body()
            file_payload = files.get("file")
            if file_payload is None:
                raise ValueError("file is required")
            filename = str(file_payload.get("filename") or "").strip()
            content = file_payload.get("content") or b""
            if not filename:
                raise ValueError("uploaded filename is empty")
            if not content:
                raise ValueError("uploaded file is empty")
            upload_path = save_uploaded_file(filename=filename, content=content)
            summary, preview_text = perform_ocr(
                upload_path,
                target=str(fields.get("target") or "wrongbook").strip() or "wrongbook",
            )
        except Exception as exc:
            print("[TeachAgent OCR Service] request failed")
            print(traceback.format_exc())
            self.respond_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self.respond_json(
            {
                "filename": filename,
                "summary": summary,
                "preview_text": preview_text,
            }
        )

    def log_message(self, format: str, *args: Any) -> None:
        return

    def respond_json(self, payload: dict[str, Any], *, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
                files[item.name] = {
                    "filename": Path(item.filename).name,
                    "content": item.file.read() if item.file is not None else b"",
                    "content_type": item.type,
                }
            else:
                fields[item.name] = item.value
        return fields, files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Standalone OCR service for TeachAgent, backed by MinerU."
    )
    parser.add_argument("--host", default=os.getenv("OCR_SERVICE_HOST") or DEFAULT_HOST)
    parser.add_argument(
        "--port",
        type=int,
        default=int(str(os.getenv("OCR_SERVICE_PORT") or DEFAULT_PORT)),
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), OcrServiceHandler)
    print(
        f"[TeachAgent OCR Service] listening on http://{args.host}:{args.port}",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()

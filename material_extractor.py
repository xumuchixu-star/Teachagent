from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from pydantic import BaseModel, Field, ValidationError
except ImportError:
    BaseModel = Field = ValidationError = None

from coach_agent import (
    MODEL_DEPLOYMENT,
    PROJECT_ENDPOINT,
    ensure_azure_cli_on_path,
    supports_structured_outputs,
)


DEFAULT_EXTRACTION_SOURCE = "material_extractor"
DEFAULT_EXTRACTION_MAX_TOKENS = 2400
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 6.0
LIST_FIELDS = {
    "aliases",
    "keywords",
    "global_keywords",
    "source_quality_notes",
    "unresolved_points",
}
TEXT_FIELDS = {
    "item_id",
    "title",
    "kind_guess",
    "summary",
    "source_excerpt",
    "confidence_note",
}
ALLOWED_KIND_GUESSES = {
    "concept",
    "formula",
    "method",
    "application",
    "mixed",
}


if BaseModel is not None:

    class ExtractedItemSchema(BaseModel):
        item_id: str | None = None
        title: str | None = None
        kind_guess: str | None = None
        summary: str | None = None
        keywords: list[str] = Field(default_factory=list)
        aliases: list[str] = Field(default_factory=list)
        source_excerpt: str | None = None
        confidence_note: str | None = None


    class ExtractedMaterialPayloadSchema(BaseModel):
        document_title: str | None = None
        document_summary: str | None = None
        global_keywords: list[str] = Field(default_factory=list)
        source_quality_notes: list[str] = Field(default_factory=list)
        unresolved_points: list[str] = Field(default_factory=list)
        items: list[ExtractedItemSchema]

else:
    ExtractedItemSchema = None
    ExtractedMaterialPayloadSchema = None


@dataclass(frozen=True)
class MaterialExtractionResult:
    rough_payload: dict[str, Any]
    normalized_payload: dict[str, Any]
    items: list[dict[str, Any]]
    raw_model_output: str
    response_source: str


class MaterialExtractionParseError(ValueError):
    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output


def material_extraction_environment() -> dict[str, str]:
    ensure_azure_cli_on_path()
    return {
        "project_endpoint": PROJECT_ENDPOINT,
        "model_deployment": MODEL_DEPLOYMENT,
        "structured_outputs_supported": str(
            supports_structured_outputs(MODEL_DEPLOYMENT)
        ),
    }


def split_text_list(raw: str) -> list[str]:
    text = raw.strip()
    if not text:
        return []
    parts = [part.strip() for part in text.split(" | ")]
    if len(parts) == 1:
        parts = [part.strip() for part in text.split(";")]
    if len(parts) == 1:
        parts = [part.strip() for part in text.split("，")]
    if len(parts) == 1:
        parts = [part.strip() for part in text.split("\n")]
    return [part for part in parts if part]


def normalize_str_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return split_text_list(value)
    if isinstance(value, list):
        normalized: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                normalized.append(text)
        return normalized
    text = str(value).strip()
    return [text] if text else []


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def extract_json_object(raw_text: str) -> str | None:
    text = raw_text.strip()
    if not text:
        return None
    if text.startswith("{") and text.endswith("}"):
        return text
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]


def load_material_text(
    *,
    material_text: str,
    material_files: list[Path],
) -> str:
    blocks: list[str] = []
    if material_text.strip():
        blocks.append(material_text.strip())
    for path in material_files:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            blocks.append(f"[FILE] {path.name}\n{text}")
    return "\n\n".join(blocks)


def normalize_kind_guess(value: Any) -> str:
    text = (normalize_text(value) or "").strip().lower()
    mapping = {
        "concept": "concept",
        "concept_card": "concept",
        "概念": "concept",
        "formula": "formula",
        "formula_card": "formula",
        "公式": "formula",
        "method": "method",
        "method_card": "method",
        "方法": "method",
        "application": "application",
        "应用": "application",
        "mixed": "mixed",
        "混合": "mixed",
    }
    if text in mapping:
        return mapping[text]
    return "mixed"


def get_payload_schema_text() -> str:
    if ExtractedMaterialPayloadSchema is None:
        return json.dumps(
            {
                "type": "object",
                "properties": {
                    "document_title": {"type": "string"},
                    "document_summary": {"type": "string"},
                    "global_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "source_quality_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "unresolved_points": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_id": {"type": "string"},
                                "title": {"type": "string"},
                                "kind_guess": {"type": "string"},
                                "summary": {"type": "string"},
                                "keywords": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "aliases": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "source_excerpt": {"type": "string"},
                                "confidence_note": {"type": "string"},
                            },
                            "required": ["title", "keywords"],
                        },
                    },
                },
                "required": ["items"],
                "additionalProperties": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(
        ExtractedMaterialPayloadSchema.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )


def build_material_extraction_prompt(
    *,
    material_text: str,
    extra_rule: str,
) -> str:
    reference_block = material_text.strip() or "无材料。"
    return f"""
你是 TeachAgent 的素材抽取助手。你的任务是把一段原始材料拆成“后续可路由到知识树叶子节点”的细粒度条目。

输出要求：
1. 只能输出一个 JSON 对象，不要输出 Markdown，不要输出解释。
2. 顶层尽量补全文档级字段：document_title、document_summary、global_keywords、source_quality_notes、unresolved_points。
3. 顶层必须有 items 数组。
4. items 中每一项表示一个可独立讨论、可独立绑定叶子的知识单元。
5. 不要输出 node_id、parent_id、matched_node_id，这一步只做素材抽取，不做知识树匹配。
6. 如果一段材料列出多个方法、公式或概念，必须拆成多条 item，不要混成一条。
7. kind_guess 只能在 concept、formula、method、application、mixed 中选择最贴近的一项。
8. keywords、aliases 必须输出为 JSON 数组，不要输出成整段字符串。
9. source_excerpt 保留很短的原文依据，便于人工检查，不要大段复制。
10. 标题尽量短，避免“第一种方法”“第二种方法”这种没有语义的信息标题；应直接写方法名、公式名或概念名。
11. 若原文表达模糊，可以概括成标准高中数学表述，但不要擅自绑定知识树。

JSON Schema：
{get_payload_schema_text()}

原始材料：
{reference_block}

额外要求：
{extra_rule.strip() or "无额外要求。"}
""".strip()


def build_material_extraction_minimal_prompt(material_text: str) -> str:
    reference_block = material_text.strip() or "无材料。"
    return f"""
你是 TeachAgent 的素材抽取助手。

只输出一个最小合法 JSON 对象，格式必须是：
{{"items":[...]}}

硬性要求：
1. 只能输出 JSON，不要解释，不要 Markdown。
2. 每条 item 代表一个可独立路由的知识单元。
3. 不要输出 node_id 或 parent_id。
4. kind_guess 只能写 concept、formula、method、application、mixed。
5. keywords、aliases 必须是 JSON 数组。

原始材料：
{reference_block}
""".strip()


def parse_extraction_payload(raw_text: str) -> dict[str, Any] | None:
    json_text = extract_json_object(raw_text)
    if json_text is None:
        return None

    if ExtractedMaterialPayloadSchema is not None:
        try:
            parsed = ExtractedMaterialPayloadSchema.model_validate_json(json_text)
            return parsed.model_dump()
        except ValidationError:
            pass

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    items = data.get("items")
    if not isinstance(items, list):
        return None
    return data


def normalize_item_id(raw_value: Any, index: int) -> str:
    item_id = normalize_text(raw_value)
    if item_id is None:
        return f"item_{index + 1:02d}"
    return item_id


def normalize_extracted_item(raw_item: dict[str, Any], index: int) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in TEXT_FIELDS:
        if key in raw_item:
            text = normalize_text(raw_item[key])
            if text is not None:
                normalized[key] = text
    for key in {"aliases", "keywords"}:
        if key in raw_item:
            values = normalize_str_list(raw_item[key])
            if values:
                normalized[key] = values

    normalized["item_id"] = normalize_item_id(raw_item.get("item_id"), index)
    normalized["kind_guess"] = normalize_kind_guess(raw_item.get("kind_guess"))

    if "title" not in normalized:
        fallback_title = (
            normalize_text(raw_item.get("source_excerpt"))
            or normalize_text(raw_item.get("summary"))
            or normalized["item_id"]
        )
        normalized["title"] = fallback_title[:60]
    normalized.setdefault("summary", normalized["title"])
    normalized.setdefault("keywords", [])
    normalized.setdefault("aliases", [])
    return normalized


def validate_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            raise ValueError("Each extracted item must be a JSON object.")
        item = normalize_extracted_item(raw_item, index)
        item_id = item["item_id"]
        if item_id in seen_ids:
            item["item_id"] = f"{item_id}_{index + 1}"
        seen_ids.add(item["item_id"])
        normalized_items.append(item)
    if not normalized_items:
        raise ValueError("Extraction produced zero items.")
    return normalized_items


def normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    items = validate_items(payload.get("items", []))
    normalized = {
        "document_title": normalize_text(payload.get("document_title")),
        "document_summary": normalize_text(payload.get("document_summary")),
        "global_keywords": normalize_str_list(payload.get("global_keywords")),
        "source_quality_notes": normalize_str_list(
            payload.get("source_quality_notes")
        ),
        "unresolved_points": normalize_str_list(payload.get("unresolved_points")),
        "items": items,
    }
    return normalized


def summarize_result(result: MaterialExtractionResult) -> dict[str, Any]:
    payload = result.normalized_payload
    return {
        "response_source": result.response_source,
        "document_title": payload.get("document_title"),
        "document_summary": payload.get("document_summary"),
        "global_keywords": payload.get("global_keywords", []),
        "source_quality_notes": payload.get("source_quality_notes", []),
        "unresolved_points": payload.get("unresolved_points", []),
        "item_count": len(result.items),
        "item_titles": [item["title"] for item in result.items],
    }


class FoundryMaterialExtractor:
    def __init__(
        self,
        project_endpoint: str = PROJECT_ENDPOINT,
        model_deployment: str = MODEL_DEPLOYMENT,
        *,
        use_default_credential: bool = False,
        max_tokens: int = DEFAULT_EXTRACTION_MAX_TOKENS,
        temperature: float = 0.1,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        ensure_azure_cli_on_path()
        try:
            from azure.ai.projects import AIProjectClient
            from azure.identity import AzureCliCredential, DefaultAzureCredential
        except ImportError as exc:
            raise ImportError(
                "Missing Azure SDK packages. In Jupyter run: "
                "%pip install -U azure-ai-projects azure-identity openai nest_asyncio pydantic"
            ) from exc

        credential = (
            DefaultAzureCredential()
            if use_default_credential
            else AzureCliCredential()
        )
        project = AIProjectClient(endpoint=project_endpoint, credential=credential)
        self.client = project.get_openai_client()
        self.model_deployment = model_deployment
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)

    def generate(
        self,
        *,
        material_text: str,
        extra_rule: str = "",
        max_tokens: int | None = None,
    ) -> MaterialExtractionResult:
        if not material_text.strip():
            raise ValueError("material_text cannot be empty.")

        prompt = build_material_extraction_prompt(
            material_text=material_text,
            extra_rule=extra_rule,
        )
        payload, raw_output, response_source = self._generate_payload(
            prompt=prompt,
            material_text=material_text,
            max_tokens=max_tokens,
        )
        normalized_payload = normalize_payload(payload)
        return MaterialExtractionResult(
            rough_payload=payload,
            normalized_payload=normalized_payload,
            items=normalized_payload["items"],
            raw_model_output=raw_output,
            response_source=response_source,
        )

    def write_output(
        self,
        *,
        result: MaterialExtractionResult,
        out_json: Path,
    ) -> None:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(
            json.dumps(result.normalized_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _generate_payload(
        self,
        *,
        prompt: str,
        material_text: str,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], str, str]:
        if supports_structured_outputs(self.model_deployment):
            structured = self._complete_structured(prompt, max_tokens=max_tokens)
            if structured is not None:
                payload, raw_output = structured
                return payload, raw_output, "ai_tool_pydantic_parse"

        json_mode = self._complete_json_mode(prompt, max_tokens=max_tokens)
        if json_mode is not None:
            payload, raw_output = json_mode
            return payload, raw_output, "ai_tool_json_mode"

        raw_output = self._complete_text(prompt, max_tokens=max_tokens)
        payload = parse_extraction_payload(raw_output)
        if payload is not None:
            return payload, raw_output, "ai_tool_text_json_validated"

        repaired = self._repair_payload(prompt, raw_output, max_tokens=max_tokens)
        if repaired is not None:
            payload, repaired_raw = repaired
            return payload, repaired_raw, "ai_tool_text_json_repaired"

        minimal_prompt = build_material_extraction_minimal_prompt(material_text)
        minimal_raw_output = self._complete_text(
            minimal_prompt,
            max_tokens=max_tokens,
        )
        minimal_payload = parse_extraction_payload(minimal_raw_output)
        if minimal_payload is not None:
            return minimal_payload, minimal_raw_output, "ai_tool_minimal_text_json"

        minimal_repaired = self._repair_payload(
            minimal_prompt,
            minimal_raw_output,
            max_tokens=max_tokens,
        )
        if minimal_repaired is not None:
            payload, repaired_raw = minimal_repaired
            return payload, repaired_raw, "ai_tool_minimal_text_json_repaired"

        preview = (
            minimal_raw_output[:1200]
            if minimal_raw_output
            else raw_output[:1200]
            if raw_output
            else ""
        )
        raise MaterialExtractionParseError(
            (
                "Model output could not be parsed into a valid extraction payload. "
                "Check raw_output for the model's actual response. "
                f"Preview: {preview}"
            ),
            raw_output=(
                "===== PRIMARY RAW OUTPUT =====\n"
                + (raw_output or "")
                + "\n\n===== MINIMAL RAW OUTPUT =====\n"
                + (minimal_raw_output or "")
            ),
        )

    def _complete_structured(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], str] | None:
        if ExtractedMaterialPayloadSchema is None:
            return None

        beta_chat = getattr(getattr(self.client, "beta", None), "chat", None)
        completions = getattr(beta_chat, "completions", None)
        parse_fn = getattr(completions, "parse", None)
        if parse_fn is None:
            return None

        response = self._with_retries(
            parse_fn,
            model=self.model_deployment,
            messages=[
                {
                    "role": "system",
                    "content": "你必须严格输出与 response_format 完全匹配的对象，不能输出额外文本。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
            response_format=ExtractedMaterialPayloadSchema,
        )
        message = response.choices[0].message
        parsed = getattr(message, "parsed", None)
        if parsed is None:
            return None
        payload = parsed.model_dump()
        return payload, json.dumps(payload, ensure_ascii=False)

    def _complete_json_mode(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], str] | None:
        response = self._with_retries(
            self.client.chat.completions.create,
            model=self.model_deployment,
            messages=[
                {
                    "role": "system",
                    "content": "你必须只输出一个合法 JSON 对象，不能输出解释、前缀或 Markdown。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
            response_format={"type": "json_object"},
        )
        raw_output = (response.choices[0].message.content or "").strip()
        payload = parse_extraction_payload(raw_output)
        if payload is None:
            return None
        return payload, raw_output

    def _complete_text(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
    ) -> str:
        response = self._with_retries(
            self.client.chat.completions.create,
            model=self.model_deployment,
            messages=[
                {
                    "role": "system",
                    "content": "你必须只输出目标 JSON，不能输出解释。",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens or self.max_tokens,
            temperature=self.temperature,
        )
        return (response.choices[0].message.content or "").strip()

    def _repair_payload(
        self,
        original_prompt: str,
        raw_output: str,
        *,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], str] | None:
        repair_prompt = f"""
把下面的坏输出修复成一个严格 JSON。
只保留一个对象，顶层至少包含 items 数组。
不要补充解释，不要输出 Markdown。
原始任务：
{original_prompt}

错误输出：
{raw_output or "无输出"}
""".strip()
        repaired_raw = self._complete_text(
            repair_prompt,
            max_tokens=min(max_tokens or self.max_tokens, 1200),
        )
        payload = parse_extraction_payload(repaired_raw)
        if payload is None:
            return None
        return payload, repaired_raw

    def _with_retries(self, fn: Any, /, **kwargs: Any) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                return fn(**kwargs)
            except Exception as exc:
                last_exc = exc
                if not self._is_rate_limit_error(exc) or attempt >= self.max_retries:
                    raise
                time.sleep(self.retry_backoff_seconds * (2**attempt))
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Unexpected retry state.")

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc)
        return "RateLimit" in text or "429" in text or "RateLimitReached" in text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--material-file",
        action="append",
        default=[],
        help="Repeatable UTF-8 source material file",
    )
    parser.add_argument(
        "--material-text",
        default="",
        help="Optional inline source material",
    )
    parser.add_argument(
        "--extra-rule",
        default="",
        help="Extra prompt rule for this extraction batch",
    )
    parser.add_argument(
        "--out-json",
        required=True,
        help="Path to output normalized extraction JSON",
    )
    parser.add_argument(
        "--out-rough-json",
        help="Optional path to save the raw validated extraction JSON",
    )
    parser.add_argument(
        "--out-raw-output",
        help="Optional path to save the raw model output text",
    )
    parser.add_argument(
        "--use-default-credential",
        action="store_true",
        help="Use DefaultAzureCredential instead of AzureCliCredential",
    )
    args = parser.parse_args()

    material_files = [Path(path) for path in args.material_file]
    material_text = load_material_text(
        material_text=args.material_text,
        material_files=material_files,
    )
    agent = FoundryMaterialExtractor(
        use_default_credential=args.use_default_credential,
    )
    result = agent.generate(
        material_text=material_text,
        extra_rule=args.extra_rule,
    )
    out_json = Path(args.out_json)
    agent.write_output(result=result, out_json=out_json)

    if args.out_rough_json:
        rough_path = Path(args.out_rough_json)
        rough_path.parent.mkdir(parents=True, exist_ok=True)
        rough_path.write_text(
            json.dumps(result.rough_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    if args.out_raw_output:
        raw_path = Path(args.out_raw_output)
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(result.raw_model_output, encoding="utf-8")

    print(f"response_source: {result.response_source}")
    print(f"wrote extraction json: {out_json}")
    if args.out_rough_json:
        print(f"wrote rough json: {args.out_rough_json}")
    if args.out_raw_output:
        print(f"wrote raw output: {args.out_raw_output}")
    print(f"generated items: {len(result.items)}")


if __name__ == "__main__":
    main()

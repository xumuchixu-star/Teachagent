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
from scripts.convert_leaf_draft_to_cards import (
    convert_entry,
    infer_card_type,
    load_inventory,
    required_fields_for,
    write_jsonl,
)


DEFAULT_DRAFT_SOURCE = "leaf_card_agent"
DEFAULT_DRAFT_MAX_TOKENS = 2600
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 6.0
LIST_FIELDS = {
    "aliases",
    "keywords",
    "tags",
    "example_refs",
    "recognition_signals",
    "common_errors",
    "applicable_conditions",
    "special_cases",
    "trigger_signals",
    "steps",
    "failure_modes",
    "applicable_problem_types",
}
TEXT_FIELDS = {
    "card_type",
    "title",
    "definition",
    "boundary",
    "core_idea",
    "formula",
    "variable_notes",
    "derivation_hint",
    "method_goal",
    "review_cue",
}
ROUGH_ONLY_TEXT_FIELDS = {
    "source_excerpt",
    "fit_reason",
    "confidence_note",
}
ALLOWED_CARD_TYPES = {
    "concept_card",
    "formula_card",
    "method_card",
}
FIELD_ORDER_BY_CARD_TYPE = {
    "concept_card": [
        "card_type",
        "title",
        "keywords",
        "aliases",
        "definition",
        "recognition_signals",
        "core_idea",
        "boundary",
        "common_errors",
        "review_cue",
        "tags",
        "example_refs",
    ],
    "formula_card": [
        "card_type",
        "title",
        "keywords",
        "aliases",
        "formula",
        "applicable_conditions",
        "special_cases",
        "variable_notes",
        "derivation_hint",
        "common_errors",
        "review_cue",
        "tags",
        "example_refs",
    ],
    "method_card": [
        "card_type",
        "title",
        "keywords",
        "aliases",
        "method_goal",
        "trigger_signals",
        "applicable_problem_types",
        "steps",
        "failure_modes",
        "review_cue",
        "tags",
        "example_refs",
    ],
}


if BaseModel is not None:

    class DraftCardSchema(BaseModel):
        node_id: str
        card_type: str | None = None
        title: str | None = None
        aliases: list[str] = Field(default_factory=list)
        keywords: list[str] = Field(default_factory=list)
        tags: list[str] = Field(default_factory=list)
        example_refs: list[str] = Field(default_factory=list)
        definition: str | None = None
        recognition_signals: list[str] = Field(default_factory=list)
        common_errors: list[str] = Field(default_factory=list)
        review_cue: str | None = None
        boundary: str | None = None
        core_idea: str | None = None
        formula: str | None = None
        applicable_conditions: list[str] = Field(default_factory=list)
        special_cases: list[str] = Field(default_factory=list)
        variable_notes: str | None = None
        derivation_hint: str | None = None
        method_goal: str | None = None
        trigger_signals: list[str] = Field(default_factory=list)
        steps: list[str] = Field(default_factory=list)
        failure_modes: list[str] = Field(default_factory=list)
        applicable_problem_types: list[str] = Field(default_factory=list)
        source_excerpt: str | None = None
        fit_reason: str | None = None
        confidence_note: str | None = None


    class DraftPayloadSchema(BaseModel):
        document_title: str | None = None
        document_summary: str | None = None
        global_keywords: list[str] = Field(default_factory=list)
        source_quality_notes: list[str] = Field(default_factory=list)
        unresolved_points: list[str] = Field(default_factory=list)
        cards: list[DraftCardSchema]

else:
    DraftCardSchema = None
    DraftPayloadSchema = None


@dataclass(frozen=True)
class DraftGenerationResult:
    rough_payload: dict[str, Any]
    entries: list[dict[str, Any]]
    validated_cards: list[dict[str, Any]]
    draft_markdown: str
    raw_model_output: str
    response_source: str


def leaf_card_environment() -> dict[str, str]:
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


def get_payload_schema_text() -> str:
    if DraftPayloadSchema is None:
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
                    "cards": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "node_id": {"type": "string"},
                                "card_type": {"type": "string"},
                                "title": {"type": "string"},
                                "keywords": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "source_excerpt": {"type": "string"},
                                "fit_reason": {"type": "string"},
                                "confidence_note": {"type": "string"},
                            },
                            "required": ["node_id", "keywords"],
                        },
                    }
                },
                "required": ["cards"],
                "additionalProperties": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(
        DraftPayloadSchema.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )


def expected_optional_fields(card_type: str) -> list[str]:
    if card_type == "formula_card":
        return [
            "aliases",
            "title",
            "variable_notes",
            "derivation_hint",
            "tags",
            "example_refs",
        ]
    if card_type == "method_card":
        return [
            "aliases",
            "title",
            "applicable_problem_types",
            "tags",
            "example_refs",
        ]
    return [
        "aliases",
        "title",
        "boundary",
        "core_idea",
        "tags",
        "example_refs",
    ]


def build_node_briefs(
    node_ids: list[str],
    inventory: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    briefs: list[dict[str, Any]] = []
    for node_id in node_ids:
        if node_id not in inventory:
            raise KeyError(f"Unknown node_id: {node_id}")
        node = inventory[node_id]
        card_type = infer_card_type(node["node_kind"])
        briefs.append(
            {
                "node_id": node_id,
                "name": node["name"],
                "node_kind": node["node_kind"],
                "expected_card_type": card_type,
                "path_text": node["path_text"],
                "prerequisite_node_ids": node.get("prerequisites", []),
                "required_fields": ["keywords"] + required_fields_for(card_type),
                "optional_fields": expected_optional_fields(card_type),
            }
        )
    return briefs


def build_leaf_card_prompt(
    *,
    node_briefs: list[dict[str, Any]],
    reference_text: str,
    extra_rule: str,
) -> str:
    reference_block = reference_text.strip() or "无额外参考材料。可基于标准高中数学知识补全。"
    return f"""
你是 TeachAgent 的叶子卡片起草助手。你的任务是为指定知识点生成“可被本地程序校验”的结构化草稿。

输出要求：
1. 只能输出一个 JSON 对象，格式必须是 {{"cards":[...]}}。
2. 必须且只能覆盖下面给出的目标 node_id，每个 node_id 恰好一条 card。
3. node_id 必须原样保留，不要改写，不要新增，不要漏掉。
4. card_type 必须与 expected_card_type 一致。当前 application 节点也按 concept_card 规则填写。
5. 顶层除了 cards 外，还应尽量补全文档级字段：document_title、document_summary、global_keywords、source_quality_notes、unresolved_points。
6. 每张 card 除标准字段外，尽量补充 rough 阶段字段：source_excerpt、fit_reason、confidence_note，方便后续人工筛查和 OCR 质检。
7. keywords、recognition_signals、common_errors、applicable_conditions、special_cases、trigger_signals、steps、failure_modes、applicable_problem_types 这些字段必须输出为 JSON 数组，不要输出成整段字符串。
8. 内容用简洁中文，面向高中复习卡片。避免空话，避免“本题中”“我们知道”这类赘述。
9. 若参考材料不足，可以依据标准高中数学知识补全，但必须紧扣节点标题和路径，不能偏题。
10. 不要输出 Markdown，不要输出解释，不要输出代码块。

JSON Schema：
{get_payload_schema_text()}

目标节点：
{json.dumps(node_briefs, ensure_ascii=False, indent=2)}

参考材料：
{reference_block}

额外要求：
{extra_rule.strip() or "无额外要求。"}
""".strip()


def build_leaf_card_minimal_prompt(
    *,
    node_briefs: list[dict[str, Any]],
    reference_text: str,
) -> str:
    reference_block = reference_text.strip() or "无额外参考材料。可基于标准高中数学知识补全。"
    simplified_briefs = [
        {
            "node_id": brief["node_id"],
            "name": brief["name"],
            "expected_card_type": brief["expected_card_type"],
            "required_fields": brief["required_fields"],
        }
        for brief in node_briefs
    ]
    return f"""
你是 TeachAgent 的叶子卡片起草助手。

这次不要补全文档级字段，不要补 source_excerpt、fit_reason、confidence_note。
你只需要输出一个最小合法 JSON 对象，格式必须是：
{{"cards":[...]}}

硬性要求：
1. 只能输出 JSON，不要解释，不要 Markdown。
2. 顶层必须只有 cards 字段，cards 必须是数组。
3. 每个 node_id 恰好生成一张 card，不能新增，不能漏掉。
4. card_type 必须与 expected_card_type 一致。
5. 列表字段必须用 JSON 数组，不要输出成字符串。
6. 如果信息不足，可以用标准高中数学知识补全，但必须围绕节点标题，不要展开到其他专题。

目标节点：
{json.dumps(simplified_briefs, ensure_ascii=False, indent=2)}

参考材料：
{reference_block}
""".strip()


def parse_draft_payload(raw_text: str) -> dict[str, Any] | None:
    json_text = extract_json_object(raw_text)
    if json_text is None:
        return None

    if DraftPayloadSchema is not None:
        try:
            parsed = DraftPayloadSchema.model_validate_json(json_text)
            return parsed.model_dump()
        except ValidationError:
            pass

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    cards = data.get("cards")
    if not isinstance(cards, list):
        return None
    normalized_cards: list[dict[str, Any]] = []
    for raw_card in cards:
        if not isinstance(raw_card, dict):
            return None
        normalized_cards.append(raw_card)
    return {"cards": normalized_cards}


def normalize_model_card(raw_card: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in {"node_id"} | TEXT_FIELDS:
        if key in raw_card:
            text = normalize_text(raw_card[key])
            if text is not None:
                normalized[key] = text
    for key in LIST_FIELDS:
        if key in raw_card:
            values = normalize_str_list(raw_card[key])
            if values:
                normalized[key] = values
    return normalized


def validate_target_coverage(
    cards: list[dict[str, Any]],
    target_node_ids: list[str],
) -> None:
    target_set = set(target_node_ids)
    seen_ids = [card.get("node_id") for card in cards if card.get("node_id")]
    seen_set = set(seen_ids)
    if len(seen_ids) != len(seen_set):
        raise ValueError("Model output contains duplicate node_id entries.")
    missing = [node_id for node_id in target_node_ids if node_id not in seen_set]
    extras = [node_id for node_id in seen_ids if node_id not in target_set]
    if missing or extras:
        raise ValueError(
            f"Model output node coverage mismatch. missing={missing}, extras={extras}"
        )


def validate_model_cards(
    *,
    cards: list[dict[str, Any]],
    target_node_ids: list[str],
    inventory: dict[str, dict[str, Any]],
    source: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    validate_target_coverage(cards, target_node_ids)
    by_id = {card["node_id"]: normalize_model_card(card) for card in cards}

    normalized_entries: list[dict[str, Any]] = []
    validated_cards: list[dict[str, Any]] = []
    for node_id in target_node_ids:
        if node_id not in inventory:
            raise KeyError(f"Unknown node_id: {node_id}")
        node = inventory[node_id]
        entry = dict(by_id[node_id])
        expected_card_type = infer_card_type(node["node_kind"])
        supplied_card_type = entry.get("card_type")
        if supplied_card_type is None:
            entry["card_type"] = expected_card_type
        elif supplied_card_type != expected_card_type:
            raise ValueError(
                f"{node_id} card_type mismatch: expected {expected_card_type}, got {supplied_card_type}"
            )
        if "title" not in entry:
            entry["title"] = node["name"]
        validated_card = convert_entry(
            entry=entry,
            inventory=inventory,
            source=source,
        )
        normalized_entries.append(entry)
        validated_cards.append(validated_card)
    return normalized_entries, validated_cards


def render_field_value(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(value)
    return str(value)


def render_draft_markdown(entries: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for entry in entries:
        card_type = entry["card_type"]
        order = FIELD_ORDER_BY_CARD_TYPE[card_type]
        lines = [f"### {entry['node_id']}"]
        for key in order:
            if key not in entry or entry[key] in ("", [], None):
                continue
            lines.append(f"- {key}: {render_field_value(entry[key])}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def load_reference_text(
    *,
    reference_text: str,
    reference_files: list[Path],
) -> str:
    blocks: list[str] = []
    if reference_text.strip():
        blocks.append(reference_text.strip())
    for path in reference_files:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            blocks.append(f"[FILE] {path.name}\n{text}")
    return "\n\n".join(blocks)


def summarize_result(result: DraftGenerationResult) -> dict[str, Any]:
    payload = result.rough_payload
    return {
        "response_source": result.response_source,
        "document_title": payload.get("document_title"),
        "document_summary": payload.get("document_summary"),
        "global_keywords": payload.get("global_keywords", []),
        "source_quality_notes": payload.get("source_quality_notes", []),
        "unresolved_points": payload.get("unresolved_points", []),
        "card_count": len(result.entries),
        "node_ids": [entry["node_id"] for entry in result.entries],
    }


class DraftPayloadParseError(ValueError):
    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output


def load_node_ids(
    *,
    node_ids: list[str],
    node_id_file: Path | None,
) -> list[str]:
    collected = [node_id.strip() for node_id in node_ids if node_id.strip()]
    if node_id_file is not None:
        for raw_line in node_id_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            collected.append(line)
    deduped: list[str] = []
    seen: set[str] = set()
    for node_id in collected:
        if node_id not in seen:
            deduped.append(node_id)
            seen.add(node_id)
    return deduped


def expand_node_prefixes(
    *,
    node_prefixes: list[str],
    inventory: dict[str, dict[str, Any]],
) -> list[str]:
    prefixes = [prefix.strip() for prefix in node_prefixes if prefix.strip()]
    if not prefixes:
        return []
    matched: list[str] = []
    for node_id, node in inventory.items():
        if not node.get("is_leaf"):
            continue
        if any(node_id.startswith(prefix) for prefix in prefixes):
            matched.append(node_id)
    return sorted(matched, key=lambda node_id: inventory[node_id]["path_text"])


class FoundryLeafCardDraftAgent:
    def __init__(
        self,
        project_endpoint: str = PROJECT_ENDPOINT,
        model_deployment: str = MODEL_DEPLOYMENT,
        *,
        use_default_credential: bool = False,
        max_tokens: int = DEFAULT_DRAFT_MAX_TOKENS,
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
        self.inventory = load_inventory()

    def generate(
        self,
        *,
        node_ids: list[str],
        reference_text: str = "",
        extra_rule: str = "",
        source: str = DEFAULT_DRAFT_SOURCE,
        max_tokens: int | None = None,
    ) -> DraftGenerationResult:
        if not node_ids:
            raise ValueError("At least one node_id is required.")

        node_briefs = build_node_briefs(node_ids, self.inventory)
        prompt = build_leaf_card_prompt(
            node_briefs=node_briefs,
            reference_text=reference_text,
            extra_rule=extra_rule,
        )
        try:
            payload, raw_output, response_source = self._generate_payload(
                prompt,
                node_briefs=node_briefs,
                reference_text=reference_text,
                max_tokens=max_tokens,
            )
            normalized_entries, validated_cards = validate_model_cards(
                cards=payload["cards"],
                target_node_ids=node_ids,
                inventory=self.inventory,
                source=source,
            )
            draft_markdown = render_draft_markdown(normalized_entries)
            return DraftGenerationResult(
                rough_payload=payload,
                entries=normalized_entries,
                validated_cards=validated_cards,
                draft_markdown=draft_markdown,
                raw_model_output=raw_output,
                response_source=response_source,
            )
        except DraftPayloadParseError as exc:
            if len(node_ids) <= 1:
                raise
            return self._generate_per_node_fallback(
                node_ids=node_ids,
                reference_text=reference_text,
                extra_rule=extra_rule,
                source=source,
                max_tokens=max_tokens,
                initial_error=exc,
            )

    def write_outputs(
        self,
        *,
        result: DraftGenerationResult,
        out_draft: Path,
        out_cards: Path | None = None,
    ) -> None:
        out_draft.parent.mkdir(parents=True, exist_ok=True)
        out_draft.write_text(result.draft_markdown, encoding="utf-8")
        if out_cards is not None:
            write_jsonl(result.validated_cards, out_cards)

    def _generate_per_node_fallback(
        self,
        *,
        node_ids: list[str],
        reference_text: str,
        extra_rule: str,
        source: str,
        max_tokens: int | None,
        initial_error: DraftPayloadParseError,
    ) -> DraftGenerationResult:
        rough_cards: list[dict[str, Any]] = []
        normalized_entries: list[dict[str, Any]] = []
        validated_cards: list[dict[str, Any]] = []
        raw_outputs: list[str] = [initial_error.raw_output]

        for node_id in node_ids:
            single_result = self.generate(
                node_ids=[node_id],
                reference_text=reference_text,
                extra_rule=extra_rule,
                source=source,
                max_tokens=max_tokens,
            )
            rough_cards.extend(single_result.rough_payload.get("cards", []))
            normalized_entries.extend(single_result.entries)
            validated_cards.extend(single_result.validated_cards)
            raw_outputs.append(single_result.raw_model_output)

        draft_markdown = render_draft_markdown(normalized_entries)
        rough_payload = {
            "document_title": None,
            "document_summary": None,
            "global_keywords": [],
            "source_quality_notes": [
                "batch_parse_failed_then_per_node_fallback_succeeded"
            ],
            "unresolved_points": [],
            "cards": rough_cards,
        }
        return DraftGenerationResult(
            rough_payload=rough_payload,
            entries=normalized_entries,
            validated_cards=validated_cards,
            draft_markdown=draft_markdown,
            raw_model_output="\n\n".join(raw_outputs),
            response_source="per_node_fallback",
        )

    def _generate_payload(
        self,
        prompt: str,
        *,
        node_briefs: list[dict[str, Any]],
        reference_text: str,
        max_tokens: int | None = None,
    ) -> tuple[dict[str, Any], str, str]:
        if supports_structured_outputs(self.model_deployment):
            structured = self._complete_structured(
                prompt,
                max_tokens=max_tokens,
            )
            if structured is not None:
                payload, raw_output = structured
                return payload, raw_output, "ai_tool_pydantic_parse"

        json_mode = self._complete_json_mode(
            prompt,
            max_tokens=max_tokens,
        )
        if json_mode is not None:
            payload, raw_output = json_mode
            return payload, raw_output, "ai_tool_json_mode"

        raw_output = self._complete_text(
            prompt,
            max_tokens=max_tokens,
        )
        payload = parse_draft_payload(raw_output)
        if payload is not None:
            return payload, raw_output, "ai_tool_text_json_validated"

        repaired = self._repair_payload(
            prompt,
            raw_output,
            max_tokens=max_tokens,
        )
        if repaired is not None:
            payload, repaired_raw = repaired
            return payload, repaired_raw, "ai_tool_text_json_repaired"

        minimal_prompt = build_leaf_card_minimal_prompt(
            node_briefs=node_briefs,
            reference_text=reference_text,
        )
        minimal_raw_output = self._complete_text(
            minimal_prompt,
            max_tokens=max_tokens,
        )
        minimal_payload = parse_draft_payload(minimal_raw_output)
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
        raise DraftPayloadParseError(
            (
                "Model output could not be parsed into a valid draft payload. "
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
        if DraftPayloadSchema is None:
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
            response_format=DraftPayloadSchema,
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
        payload = parse_draft_payload(raw_output)
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
只保留一个对象，格式必须是 {{"cards":[...]}}。
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
        payload = parse_draft_payload(repaired_raw)
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
        "--node-id",
        action="append",
        default=[],
        help="Repeatable leaf node id to draft",
    )
    parser.add_argument(
        "--node-id-file",
        help="Text file with one node_id per line",
    )
    parser.add_argument(
        "--node-prefix",
        action="append",
        default=[],
        help="Repeatable node_id prefix. Expands to all matching leaf nodes.",
    )
    parser.add_argument(
        "--reference-file",
        action="append",
        default=[],
        help="Optional UTF-8 text file used as reference context",
    )
    parser.add_argument(
        "--material-file",
        action="append",
        default=[],
        help="Alias of --reference-file for raw source material",
    )
    parser.add_argument(
        "--reference-text",
        default="",
        help="Optional inline reference text",
    )
    parser.add_argument(
        "--extra-rule",
        default="",
        help="Extra prompt rule for this generation batch",
    )
    parser.add_argument(
        "--out-draft",
        required=True,
        help="Path to output markdown draft",
    )
    parser.add_argument(
        "--out-cards",
        help="Optional path to output validated JSONL cards",
    )
    parser.add_argument(
        "--out-rough-json",
        help="Optional path to save the model's rough extraction JSON",
    )
    parser.add_argument(
        "--out-normalized-json",
        help="Optional path to save normalized entries before markdown rendering",
    )
    parser.add_argument(
        "--source",
        default=DEFAULT_DRAFT_SOURCE,
        help="Source label written into converted cards",
    )
    parser.add_argument(
        "--use-default-credential",
        action="store_true",
        help="Use DefaultAzureCredential instead of AzureCliCredential",
    )
    args = parser.parse_args()

    node_id_file = Path(args.node_id_file) if args.node_id_file else None
    seed_node_ids = load_node_ids(node_ids=args.node_id, node_id_file=node_id_file)
    inventory = load_inventory()
    prefix_node_ids = expand_node_prefixes(
        node_prefixes=args.node_prefix,
        inventory=inventory,
    )
    node_ids = []
    seen_node_ids: set[str] = set()
    for node_id in seed_node_ids + prefix_node_ids:
        if node_id not in seen_node_ids:
            node_ids.append(node_id)
            seen_node_ids.add(node_id)

    reference_files = [Path(path) for path in args.reference_file + args.material_file]
    reference_text = load_reference_text(
        reference_text=args.reference_text,
        reference_files=reference_files,
    )

    agent = FoundryLeafCardDraftAgent(
        use_default_credential=args.use_default_credential,
    )
    result = agent.generate(
        node_ids=node_ids,
        reference_text=reference_text,
        extra_rule=args.extra_rule,
        source=args.source,
    )
    out_draft = Path(args.out_draft)
    out_cards = Path(args.out_cards) if args.out_cards else None
    agent.write_outputs(
        result=result,
        out_draft=out_draft,
        out_cards=out_cards,
    )
    if args.out_rough_json:
        rough_path = Path(args.out_rough_json)
        rough_path.parent.mkdir(parents=True, exist_ok=True)
        rough_path.write_text(
            json.dumps(result.rough_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.out_normalized_json:
        normalized_path = Path(args.out_normalized_json)
        normalized_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_path.write_text(
            json.dumps(result.entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"response_source: {result.response_source}")
    print(f"wrote draft: {out_draft}")
    if args.out_rough_json:
        print(f"wrote rough json: {args.out_rough_json}")
    if args.out_normalized_json:
        print(f"wrote normalized json: {args.out_normalized_json}")
    if out_cards is not None:
        print(f"wrote cards: {out_cards}")
    print(f"generated entries: {len(result.entries)}")


if __name__ == "__main__":
    main()

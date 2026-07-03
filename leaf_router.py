from __future__ import annotations

import argparse
import json
import math
import re
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
from scripts.convert_leaf_draft_to_cards import load_inventory


DEFAULT_ROUTER_SOURCE = "leaf_router"
DEFAULT_ROUTER_MAX_TOKENS = 2600
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 6.0
DEFAULT_CANDIDATE_LIMIT = 8
DEFAULT_PARENT_LIMIT = 6
TOKEN_RE = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]+")


if BaseModel is not None:

    class RouteDecisionSchema(BaseModel):
        item_id: str
        title: str | None = None
        decision: str | None = None
        matched_node_id: str | None = None
        proposed_name: str | None = None
        proposed_kind: str | None = None
        parent_node_id: str | None = None
        confidence: float | None = None
        reason: str | None = None
        candidate_node_ids: list[str] = Field(default_factory=list)
        candidate_parent_node_ids: list[str] = Field(default_factory=list)


    class LeafRoutingPayloadSchema(BaseModel):
        document_title: str | None = None
        routing_notes: list[str] = Field(default_factory=list)
        routes: list[RouteDecisionSchema]

else:
    RouteDecisionSchema = None
    LeafRoutingPayloadSchema = None


@dataclass(frozen=True)
class LeafRoutingResult:
    rough_payload: dict[str, Any]
    normalized_payload: dict[str, Any]
    routes: list[dict[str, Any]]
    raw_model_output: str
    response_source: str


class LeafRoutingParseError(ValueError):
    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output


def leaf_routing_environment() -> dict[str, str]:
    ensure_azure_cli_on_path()
    return {
        "project_endpoint": PROJECT_ENDPOINT,
        "model_deployment": MODEL_DEPLOYMENT,
        "structured_outputs_supported": str(
            supports_structured_outputs(MODEL_DEPLOYMENT)
        ),
    }


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def tokenize_text(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def character_set(text: str) -> set[str]:
    return {
        char.lower()
        for char in text
        if ("\u4e00" <= char <= "\u9fff") or char.isalnum()
    }


def token_set_for_item(
    item: dict[str, Any],
    document_context: dict[str, Any] | None = None,
) -> set[str]:
    tokens: set[str] = set()
    for part in [
        item.get("title"),
        item.get("summary"),
        item.get("source_excerpt"),
        *item.get("keywords", []),
        *item.get("aliases", []),
    ]:
        if not part:
            continue
        tokens.update(tokenize_text(str(part)))
    if document_context is not None:
        for part in [
            document_context.get("document_title"),
            document_context.get("document_summary"),
            *document_context.get("global_keywords", []),
        ]:
            if not part:
                continue
            tokens.update(tokenize_text(str(part)))
    return tokens


def token_set_for_node(node: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for part in [
        node.get("name"),
        node.get("path_text"),
        *node.get("aliases", []),
    ]:
        if not part:
            continue
        tokens.update(tokenize_text(str(part)))
    return tokens


def char_set_for_item(
    item: dict[str, Any],
    document_context: dict[str, Any] | None = None,
) -> set[str]:
    chars: set[str] = set()
    for part in [
        item.get("title"),
        item.get("summary"),
        item.get("source_excerpt"),
        *item.get("keywords", []),
        *item.get("aliases", []),
    ]:
        if not part:
            continue
        chars.update(character_set(str(part)))
    if document_context is not None:
        for part in [
            document_context.get("document_title"),
            document_context.get("document_summary"),
            *document_context.get("global_keywords", []),
        ]:
            if not part:
                continue
            chars.update(character_set(str(part)))
    return chars


def char_set_for_node(node: dict[str, Any]) -> set[str]:
    chars: set[str] = set()
    for part in [
        node.get("name"),
        node.get("path_text"),
        *node.get("aliases", []),
    ]:
        if not part:
            continue
        chars.update(character_set(str(part)))
    return chars


def jaccard_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    if overlap == 0:
        return 0.0
    return overlap / len(left | right)


def overlap_bonus(item: dict[str, Any], node: dict[str, Any]) -> float:
    bonus = 0.0
    title = (item.get("title") or "").lower()
    node_name = (node.get("name") or "").lower()
    if title and node_name and (title in node_name or node_name in title):
        bonus += 0.35
    item_keywords = {keyword.lower() for keyword in item.get("keywords", [])}
    path_tokens = {token.lower() for token in tokenize_text(node.get("path_text", ""))}
    if item_keywords and path_tokens:
        bonus += min(0.25, 0.06 * len(item_keywords & path_tokens))
    return bonus


def infer_kind_from_item(item: dict[str, Any]) -> str | None:
    kind = normalize_text(item.get("kind_guess"))
    if kind is None:
        return None
    kind = kind.lower()
    if kind in {"concept", "formula", "method", "application"}:
        return kind
    return None


def compute_leaf_candidates(
    item: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
    *,
    candidate_limit: int,
    document_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    item_tokens = token_set_for_item(item, document_context=document_context)
    item_chars = char_set_for_item(item, document_context=document_context)
    kind = infer_kind_from_item(item)
    scored: list[tuple[float, dict[str, Any]]] = []
    for node in inventory.values():
        if not node.get("is_leaf"):
            continue
        if kind is not None and node.get("node_kind") not in {kind, "application"}:
            if not (kind == "application" and node.get("node_kind") == "concept"):
                continue
        node_tokens = token_set_for_node(node)
        node_chars = char_set_for_node(node)
        score = (
            jaccard_score(item_tokens, node_tokens)
            + 0.35 * jaccard_score(item_chars, node_chars)
            + overlap_bonus(item, node)
        )
        if score <= 0:
            continue
        scored.append((score, node))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["path_text"]))
    top = scored[:candidate_limit]
    return [
        {
            "node_id": node["node_id"],
            "name": node["name"],
            "node_kind": node["node_kind"],
            "path_text": node["path_text"],
            "score_hint": round(score, 4),
        }
        for score, node in top
    ]


def build_parent_index(
) -> dict[str, dict[str, Any]]:
    nodes_path = (
        Path("/Users/xumuchi/Desktop/TeachAgent")
        / "docs"
        / "rag_inventory"
        / "knowledge_tree_typed_full.json"
    )
    payload = json.loads(nodes_path.read_text(encoding="utf-8"))
    node_rows = payload["nodes"]
    return {row["node_id"]: row for row in node_rows}


def collect_leaf_counts_by_parent(
    inventory: dict[str, dict[str, Any]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for node in inventory.values():
        parent_id = node.get("parent_id")
        if not parent_id:
            continue
        counts[parent_id] = counts.get(parent_id, 0) + 1
    return counts


def compute_parent_candidates(
    item: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
    parent_index: dict[str, dict[str, Any]],
    leaf_counts_by_parent: dict[str, int],
    *,
    parent_limit: int,
    document_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    item_tokens = token_set_for_item(item, document_context=document_context)
    item_chars = char_set_for_item(item, document_context=document_context)
    scored: list[tuple[float, dict[str, Any]]] = []
    for parent_id, parent in parent_index.items():
        if parent.get("is_leaf"):
            continue
        parent_tokens = token_set_for_node(parent)
        parent_chars = char_set_for_node(parent)
        score = jaccard_score(item_tokens, parent_tokens) + 0.35 * jaccard_score(
            item_chars, parent_chars
        )
        if item.get("title") and parent.get("name"):
            title = item["title"].lower()
            parent_name = parent["name"].lower()
            if title in parent_name or parent_name in title:
                score += 0.15
        if score <= 0:
            continue
        scored.append((score, parent))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["path_text"]))
    top = scored[:parent_limit]
    return [
        {
            "parent_node_id": parent["node_id"],
            "name": parent["name"],
            "path_text": parent["path_text"],
            "child_leaf_count": leaf_counts_by_parent.get(parent["node_id"], 0),
            "score_hint": round(score, 4),
        }
        for score, parent in top
    ]


def build_route_input_items(
    *,
    extracted_items: list[dict[str, Any]],
    inventory: dict[str, dict[str, Any]],
    parent_index: dict[str, dict[str, Any]],
    leaf_counts_by_parent: dict[str, int],
    candidate_limit: int,
    parent_limit: int,
    document_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    route_items: list[dict[str, Any]] = []
    for item in extracted_items:
        candidate_leaves = compute_leaf_candidates(
            item,
            inventory,
            candidate_limit=candidate_limit,
            document_context=document_context,
        )
        candidate_parents = compute_parent_candidates(
            item,
            inventory,
            parent_index,
            leaf_counts_by_parent,
            parent_limit=parent_limit,
            document_context=document_context,
        )
        if not candidate_parents and candidate_leaves:
            seen_parent_ids: set[str] = set()
            fallback_parents: list[dict[str, Any]] = []
            for candidate in candidate_leaves:
                leaf_node = inventory.get(candidate["node_id"])
                if leaf_node is None:
                    continue
                parent_id = leaf_node.get("parent_id")
                if not parent_id or parent_id in seen_parent_ids:
                    continue
                parent = parent_index.get(parent_id)
                if parent is None:
                    continue
                fallback_parents.append(
                    {
                        "parent_node_id": parent["node_id"],
                        "name": parent["name"],
                        "path_text": parent["path_text"],
                        "child_leaf_count": leaf_counts_by_parent.get(
                            parent["node_id"], 0
                        ),
                        "score_hint": candidate["score_hint"],
                    }
                )
                seen_parent_ids.add(parent_id)
                if len(fallback_parents) >= parent_limit:
                    break
            candidate_parents = fallback_parents
        route_items.append(
            {
                "item_id": item["item_id"],
                "title": item["title"],
                "kind_guess": item.get("kind_guess"),
                "summary": item.get("summary"),
                "keywords": item.get("keywords", []),
                "aliases": item.get("aliases", []),
                "source_excerpt": item.get("source_excerpt"),
                "confidence_note": item.get("confidence_note"),
                "candidate_leaves": candidate_leaves,
                "candidate_parents": candidate_parents,
            }
        )
    return route_items


def get_payload_schema_text() -> str:
    if LeafRoutingPayloadSchema is None:
        return json.dumps(
            {
                "type": "object",
                "properties": {
                    "document_title": {"type": "string"},
                    "routing_notes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "routes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_id": {"type": "string"},
                                "title": {"type": "string"},
                                "decision": {"type": "string"},
                                "matched_node_id": {"type": "string"},
                                "proposed_name": {"type": "string"},
                                "proposed_kind": {"type": "string"},
                                "parent_node_id": {"type": "string"},
                                "confidence": {"type": "number"},
                                "reason": {"type": "string"},
                                "candidate_node_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                                "candidate_parent_node_ids": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["item_id", "decision", "reason"],
                        },
                    },
                },
                "required": ["routes"],
                "additionalProperties": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    return json.dumps(
        LeafRoutingPayloadSchema.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )


def build_leaf_routing_prompt(
    *,
    document_title: str | None,
    route_items: list[dict[str, Any]],
    extra_rule: str,
) -> str:
    return f"""
你是 TeachAgent 的叶子路由助手。你的任务是把抽取出的知识条目路由到现有知识树叶子，或者在现有叶子不合适时提出“新叶子建议”。

输出要求：
1. 只能输出一个 JSON 对象，不要输出 Markdown，不要输出解释。
2. 顶层必须有 routes 数组，每个 item_id 恰好输出一条 route。
3. decision 只能是 match_existing、create_new_leaf、uncertain 三者之一。
4. 如果 decision=match_existing：
   - 必须填写 matched_node_id
   - matched_node_id 必须从该条目的 candidate_leaves 里选择
5. 如果 decision=create_new_leaf：
   - 必须填写 proposed_name、proposed_kind、parent_node_id
   - parent_node_id 必须从该条目的 candidate_parents 里选择
   - proposed_kind 只能是 concept、formula、method、application
6. 如果 decision=uncertain：
   - 不要强行匹配，也不要乱建；说明不确定原因即可。
7. confidence 用 0 到 1 之间的小数。
8. reason 要简洁说明“为什么匹配这个叶子”或“为什么建议在这个父节点下新建”。
9. candidate_node_ids 和 candidate_parent_node_ids 尽量保留，便于人工复核。
10. 不要发明不在候选列表中的 matched_node_id 或 parent_node_id。

JSON Schema：
{get_payload_schema_text()}

文档标题：
{document_title or "未知文档"}

待路由条目与候选：
{json.dumps(route_items, ensure_ascii=False, indent=2)}

额外要求：
{extra_rule.strip() or "优先选择最贴近的已有叶子；确实没有时再提新叶子。"}
""".strip()


def build_leaf_routing_minimal_prompt(route_items: list[dict[str, Any]]) -> str:
    simplified = []
    for item in route_items:
        simplified.append(
            {
                "item_id": item["item_id"],
                "title": item["title"],
                "kind_guess": item.get("kind_guess"),
                "candidate_leaves": item["candidate_leaves"],
                "candidate_parents": item["candidate_parents"],
            }
        )
    return f"""
你是 TeachAgent 的叶子路由助手。

只输出一个最小合法 JSON 对象，格式必须是：
{{"routes":[...]}}

硬性要求：
1. 每个 item_id 恰好输出一条 route。
2. decision 只能是 match_existing、create_new_leaf、uncertain。
3. matched_node_id 只能从 candidate_leaves 里选。
4. parent_node_id 只能从 candidate_parents 里选。
5. 只能输出 JSON，不要解释，不要 Markdown。

条目：
{json.dumps(simplified, ensure_ascii=False, indent=2)}
""".strip()


def parse_routing_payload(raw_text: str) -> dict[str, Any] | None:
    json_text = extract_json_object(raw_text)
    if json_text is None:
        return None

    if LeafRoutingPayloadSchema is not None:
        try:
            parsed = LeafRoutingPayloadSchema.model_validate_json(json_text)
            return parsed.model_dump()
        except ValidationError:
            pass

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    routes = data.get("routes")
    if not isinstance(routes, list):
        return None
    return data


def route_lookup_by_item(route_items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {item["item_id"]: item for item in route_items}


def clamp_confidence(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(parsed):
        return None
    return max(0.0, min(1.0, parsed))


def normalize_route(
    raw_route: dict[str, Any],
    *,
    route_item: dict[str, Any],
) -> dict[str, Any]:
    normalized = {
        "item_id": route_item["item_id"],
        "title": normalize_text(raw_route.get("title")) or route_item["title"],
        "decision": normalize_text(raw_route.get("decision")) or "uncertain",
        "matched_node_id": normalize_text(raw_route.get("matched_node_id")),
        "proposed_name": normalize_text(raw_route.get("proposed_name")),
        "proposed_kind": normalize_text(raw_route.get("proposed_kind")),
        "parent_node_id": normalize_text(raw_route.get("parent_node_id")),
        "confidence": clamp_confidence(raw_route.get("confidence")),
        "reason": normalize_text(raw_route.get("reason")) or "模型未提供原因。",
        "candidate_node_ids": normalize_str_list(raw_route.get("candidate_node_ids")),
        "candidate_parent_node_ids": normalize_str_list(
            raw_route.get("candidate_parent_node_ids")
        ),
    }
    return normalized


def validate_decision_shape(
    route: dict[str, Any],
    route_item: dict[str, Any],
) -> None:
    decision = route["decision"]
    allowed_decisions = {"match_existing", "create_new_leaf", "uncertain"}
    if decision not in allowed_decisions:
        raise ValueError(f"Unsupported decision: {decision}")

    candidate_leaf_ids = {
        candidate["node_id"] for candidate in route_item.get("candidate_leaves", [])
    }
    candidate_parent_ids = {
        candidate["parent_node_id"]
        for candidate in route_item.get("candidate_parents", [])
    }

    if decision == "match_existing":
        matched_node_id = route.get("matched_node_id")
        if matched_node_id is None:
            raise ValueError(
                f"{route['item_id']} decision=match_existing but matched_node_id missing"
            )
        if not candidate_leaf_ids:
            raise ValueError(
                f"{route['item_id']} decision=match_existing but candidate_leaves is empty"
            )
        if matched_node_id not in candidate_leaf_ids:
            raise ValueError(
                f"{route['item_id']} matched_node_id must come from candidate_leaves"
            )
    elif decision == "create_new_leaf":
        if not route.get("proposed_name"):
            raise ValueError(
                f"{route['item_id']} decision=create_new_leaf but proposed_name missing"
            )
        proposed_kind = route.get("proposed_kind")
        if proposed_kind not in {"concept", "formula", "method", "application"}:
            raise ValueError(
                f"{route['item_id']} proposed_kind invalid: {proposed_kind}"
            )
        parent_node_id = route.get("parent_node_id")
        if parent_node_id is None:
            raise ValueError(
                f"{route['item_id']} decision=create_new_leaf but parent_node_id missing"
            )
        if not candidate_parent_ids:
            raise ValueError(
                f"{route['item_id']} decision=create_new_leaf but candidate_parents is empty"
            )
        if parent_node_id not in candidate_parent_ids:
            raise ValueError(
                f"{route['item_id']} parent_node_id must come from candidate_parents"
            )


def normalize_payload(
    payload: dict[str, Any],
    *,
    route_items: list[dict[str, Any]],
) -> dict[str, Any]:
    routes = payload.get("routes")
    if not isinstance(routes, list):
        raise ValueError("routing payload must contain a routes array")

    by_item = route_lookup_by_item(route_items)
    seen_item_ids: set[str] = set()
    normalized_routes: list[dict[str, Any]] = []
    for raw_route in routes:
        if not isinstance(raw_route, dict):
            raise ValueError("Each route must be a JSON object.")
        item_id = normalize_text(raw_route.get("item_id"))
        if item_id is None:
            raise ValueError("Each route must include item_id.")
        if item_id not in by_item:
            raise ValueError(f"Unknown item_id in route payload: {item_id}")
        if item_id in seen_item_ids:
            raise ValueError(f"Duplicate route for item_id: {item_id}")
        route_item = by_item[item_id]
        normalized_route = normalize_route(raw_route, route_item=route_item)
        if not normalized_route["candidate_node_ids"]:
            normalized_route["candidate_node_ids"] = [
                candidate["node_id"] for candidate in route_item.get("candidate_leaves", [])
            ]
        if not normalized_route["candidate_parent_node_ids"]:
            normalized_route["candidate_parent_node_ids"] = [
                candidate["parent_node_id"]
                for candidate in route_item.get("candidate_parents", [])
            ]
        validate_decision_shape(normalized_route, route_item)
        normalized_routes.append(normalized_route)
        seen_item_ids.add(item_id)

    missing = [item["item_id"] for item in route_items if item["item_id"] not in seen_item_ids]
    if missing:
        raise ValueError(f"Missing routes for item_ids: {missing}")

    return {
        "document_title": normalize_text(payload.get("document_title")),
        "routing_notes": normalize_str_list(payload.get("routing_notes")),
        "routes": normalized_routes,
    }


def summarize_result(result: LeafRoutingResult) -> dict[str, Any]:
    payload = result.normalized_payload
    return {
        "response_source": result.response_source,
        "document_title": payload.get("document_title"),
        "routing_notes": payload.get("routing_notes", []),
        "route_count": len(result.routes),
        "decisions": [
            {
                "item_id": route["item_id"],
                "title": route["title"],
                "decision": route["decision"],
                "matched_node_id": route.get("matched_node_id"),
                "parent_node_id": route.get("parent_node_id"),
                "proposed_name": route.get("proposed_name"),
            }
            for route in result.routes
        ],
    }


class FoundryLeafRouter:
    def __init__(
        self,
        project_endpoint: str = PROJECT_ENDPOINT,
        model_deployment: str = MODEL_DEPLOYMENT,
        *,
        use_default_credential: bool = False,
        max_tokens: int = DEFAULT_ROUTER_MAX_TOKENS,
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
        self.parent_index = build_parent_index()
        self.leaf_counts_by_parent = collect_leaf_counts_by_parent(self.inventory)

    def generate(
        self,
        *,
        extracted_payload: dict[str, Any],
        extra_rule: str = "",
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        parent_limit: int = DEFAULT_PARENT_LIMIT,
        max_tokens: int | None = None,
    ) -> LeafRoutingResult:
        extracted_items = extracted_payload.get("items")
        if not isinstance(extracted_items, list) or not extracted_items:
            raise ValueError("extracted_payload must contain a non-empty items array.")

        route_items = build_route_input_items(
            extracted_items=extracted_items,
            inventory=self.inventory,
            parent_index=self.parent_index,
            leaf_counts_by_parent=self.leaf_counts_by_parent,
            candidate_limit=max(1, candidate_limit),
            parent_limit=max(1, parent_limit),
            document_context={
                "document_title": extracted_payload.get("document_title"),
                "document_summary": extracted_payload.get("document_summary"),
                "global_keywords": extracted_payload.get("global_keywords", []),
            },
        )
        prompt = build_leaf_routing_prompt(
            document_title=normalize_text(extracted_payload.get("document_title")),
            route_items=route_items,
            extra_rule=extra_rule,
        )
        payload, raw_output, response_source = self._generate_payload(
            prompt=prompt,
            route_items=route_items,
            max_tokens=max_tokens,
        )
        normalized_payload = normalize_payload(payload, route_items=route_items)
        return LeafRoutingResult(
            rough_payload=payload,
            normalized_payload=normalized_payload,
            routes=normalized_payload["routes"],
            raw_model_output=raw_output,
            response_source=response_source,
        )

    def write_output(
        self,
        *,
        result: LeafRoutingResult,
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
        route_items: list[dict[str, Any]],
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
        payload = parse_routing_payload(raw_output)
        if payload is not None:
            return payload, raw_output, "ai_tool_text_json_validated"

        repaired = self._repair_payload(prompt, raw_output, max_tokens=max_tokens)
        if repaired is not None:
            payload, repaired_raw = repaired
            return payload, repaired_raw, "ai_tool_text_json_repaired"

        minimal_prompt = build_leaf_routing_minimal_prompt(route_items)
        minimal_raw_output = self._complete_text(
            minimal_prompt,
            max_tokens=max_tokens,
        )
        minimal_payload = parse_routing_payload(minimal_raw_output)
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
        raise LeafRoutingParseError(
            (
                "Model output could not be parsed into a valid routing payload. "
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
        if LeafRoutingPayloadSchema is None:
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
            response_format=LeafRoutingPayloadSchema,
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
        payload = parse_routing_payload(raw_output)
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
只保留一个对象，顶层至少包含 routes 数组。
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
        payload = parse_routing_payload(repaired_raw)
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
        "--extracted-json",
        required=True,
        help="Path to normalized extraction JSON produced by material_extractor.py",
    )
    parser.add_argument(
        "--extra-rule",
        default="",
        help="Extra prompt rule for this routing batch",
    )
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=DEFAULT_CANDIDATE_LIMIT,
        help="How many candidate leaves to surface per item before model routing",
    )
    parser.add_argument(
        "--parent-limit",
        type=int,
        default=DEFAULT_PARENT_LIMIT,
        help="How many candidate parent nodes to surface for new-leaf proposals",
    )
    parser.add_argument(
        "--out-json",
        required=True,
        help="Path to output normalized routing JSON",
    )
    parser.add_argument(
        "--out-rough-json",
        help="Optional path to save the raw validated routing JSON",
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

    extracted_path = Path(args.extracted_json)
    extracted_payload = json.loads(extracted_path.read_text(encoding="utf-8"))
    agent = FoundryLeafRouter(
        use_default_credential=args.use_default_credential,
    )
    result = agent.generate(
        extracted_payload=extracted_payload,
        extra_rule=args.extra_rule,
        candidate_limit=args.candidate_limit,
        parent_limit=args.parent_limit,
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
    print(f"wrote routing json: {out_json}")
    if args.out_rough_json:
        print(f"wrote rough json: {args.out_rough_json}")
    if args.out_raw_output:
        print(f"wrote raw output: {args.out_raw_output}")
    print(f"generated routes: {len(result.routes)}")


if __name__ == "__main__":
    main()

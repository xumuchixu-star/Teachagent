from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
INVENTORY_PATH = ROOT / "docs" / "rag_inventory" / "leaf_nodes_full.jsonl"

ENTRY_RE = re.compile(r"^###\s+(.+?)\s*$")
FIELD_RE = re.compile(r"^- ([a-z_]+):\s*(.*)$")

CONCEPT_REQUIRED = [
    "definition",
    "recognition_signals",
    "common_errors",
    "review_cue",
]

FORMULA_REQUIRED = [
    "formula",
    "applicable_conditions",
    "special_cases",
    "common_errors",
    "review_cue",
]

METHOD_REQUIRED = [
    "method_goal",
    "trigger_signals",
    "steps",
    "failure_modes",
    "review_cue",
]

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

OPTIONAL_FIELDS = {
    "aliases",
    "keywords",
    "tags",
    "example_refs",
    "boundary",
    "core_idea",
    "variable_notes",
    "derivation_hint",
    "applicable_problem_types",
}


def load_inventory() -> dict[str, dict[str, Any]]:
    inventory: dict[str, dict[str, Any]] = {}
    with INVENTORY_PATH.open(encoding="utf-8") as fp:
        for line in fp:
            row = json.loads(line)
            inventory[row["node_id"]] = row
    return inventory


def parse_list_value(raw: str) -> list[str]:
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text:
        return []
    parts = [part.strip() for part in text.split(" | ")]
    if len(parts) == 1:
        parts = [part.strip() for part in text.split(";")]
    if len(parts) == 1:
        parts = [part.strip() for part in text.split("，")]
    return [part for part in parts if part]


def parse_draft(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        entry_match = ENTRY_RE.match(line)
        if entry_match:
            if current:
                entries.append(current)
            current = {"node_id": entry_match.group(1).strip()}
            continue

        if current is None:
            continue

        field_match = FIELD_RE.match(line)
        if not field_match:
            raise ValueError(f"Invalid line in draft: {line}")

        key = field_match.group(1).strip()
        value = field_match.group(2).strip()
        if key in LIST_FIELDS:
            current[key] = parse_list_value(value)
        else:
            current[key] = value

    if current:
        entries.append(current)
    return entries


def infer_card_type(node_kind: str) -> str:
    if node_kind == "formula":
        return "formula_card"
    if node_kind == "method":
        return "method_card"
    return "concept_card"


def required_fields_for(card_type: str) -> list[str]:
    if card_type == "formula_card":
        return FORMULA_REQUIRED
    if card_type == "method_card":
        return METHOD_REQUIRED
    return CONCEPT_REQUIRED


SENTENCE_ENDINGS = ("。", "！", "？", ".", "!", "?")


def ensure_sentence(text: str) -> str:
    value = text.strip()
    if not value:
        return value
    if value.endswith(SENTENCE_ENDINGS):
        return value
    return value + "。"


def labeled_sentence(label: str, value: str) -> str:
    return ensure_sentence(f"{label}{value}")


def labeled_list_sentence(label: str, values: list[str]) -> str:
    return labeled_sentence(label, "；".join(values))


def build_text(card: dict[str, Any]) -> str:
    path_text = " > ".join(card["path"])
    parts: list[str] = []
    title_label = "方法" if card["card_type"] == "method_card" else "知识点"
    parts.append(labeled_sentence(f"{title_label}：", card["title"]))
    parts.append(labeled_sentence("路径：", path_text))

    if card.get("aliases"):
        parts.append(labeled_list_sentence("别名：", card["aliases"]))
    if card.get("keywords"):
        parts.append(labeled_list_sentence("关键词：", card["keywords"]))

    if card["card_type"] == "concept_card":
        parts.append(labeled_sentence("定义：", card["definition"]))
        if card.get("recognition_signals"):
            parts.append(
                labeled_list_sentence("识别信号：", card["recognition_signals"])
            )
        if card.get("core_idea"):
            parts.append(labeled_sentence("核心理解：", card["core_idea"]))
        if card.get("boundary"):
            parts.append(labeled_sentence("边界：", card["boundary"]))
        parts.append(labeled_list_sentence("常见错误：", card["common_errors"]))
        parts.append(labeled_sentence("复习提示：", card["review_cue"]))
    elif card["card_type"] == "formula_card":
        parts.append(labeled_sentence("公式：", card["formula"]))
        parts.append(
            labeled_list_sentence("适用条件：", card["applicable_conditions"])
        )
        parts.append(labeled_list_sentence("特殊情况：", card["special_cases"]))
        if card.get("variable_notes"):
            parts.append(labeled_sentence("变量说明：", card["variable_notes"]))
        if card.get("derivation_hint"):
            parts.append(labeled_sentence("推导提示：", card["derivation_hint"]))
        parts.append(labeled_list_sentence("常见错误：", card["common_errors"]))
        parts.append(labeled_sentence("复习提示：", card["review_cue"]))
    else:
        parts.append(labeled_sentence("目标：", card["method_goal"]))
        parts.append(labeled_list_sentence("触发信号：", card["trigger_signals"]))
        if card.get("applicable_problem_types"):
            parts.append(
                labeled_list_sentence(
                    "适用题型：", card["applicable_problem_types"]
                )
            )
        parts.append(labeled_list_sentence("步骤：", card["steps"]))
        parts.append(labeled_list_sentence("常见失败：", card["failure_modes"]))
        parts.append(labeled_sentence("复习提示：", card["review_cue"]))
    return "".join(parts)


def convert_entry(
    entry: dict[str, Any],
    inventory: dict[str, dict[str, Any]],
    source: str,
) -> dict[str, Any]:
    node_id = entry["node_id"]
    if node_id not in inventory:
        raise KeyError(f"Unknown node_id: {node_id}")

    node = inventory[node_id]
    card_type = entry.get("card_type") or infer_card_type(node["node_kind"])
    required_fields = required_fields_for(card_type)
    for key in required_fields:
        if key not in entry or entry[key] in ("", []):
            raise ValueError(f"{node_id} missing required field: {key}")

    if "keywords" not in entry or not entry["keywords"]:
        raise ValueError(f"{node_id} missing required field: keywords")

    card: dict[str, Any] = {
        "chunk_id": f"chunk.{node_id}.{card_type}.v1",
        "node_id": node_id,
        "node_kind": node["node_kind"],
        "review_role": node["review_role"],
        "binding_role": node["binding_role"],
        "card_type": card_type,
        "title": entry.get("title") or node["name"],
        "path": node["path"],
        "aliases": entry.get("aliases", []),
        "is_primary": True,
        "prerequisite_node_ids": node.get("prerequisites", []),
        "keywords": entry["keywords"],
        "source": source,
    }

    if "tags" in entry:
        card["tags"] = entry["tags"]
    if "example_refs" in entry:
        card["example_refs"] = entry["example_refs"]

    for key in required_fields:
        card[key] = entry[key]
    for key in OPTIONAL_FIELDS:
        if key in entry and entry[key] not in ("", []):
            card[key] = entry[key]

    card["text"] = build_text(card)
    return card


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for record in records:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--draft", required=True, help="Path to markdown draft")
    parser.add_argument("--out", required=True, help="Path to output jsonl")
    parser.add_argument(
        "--source",
        default="draft_converter",
        help="Source label to write into generated cards",
    )
    args = parser.parse_args()

    inventory = load_inventory()
    draft_path = Path(args.draft)
    out_path = Path(args.out)

    entries = parse_draft(draft_path)
    cards = [
        convert_entry(entry=entry, inventory=inventory, source=args.source)
        for entry in entries
    ]
    write_jsonl(cards, out_path)
    print(f"wrote {len(cards)} cards to {out_path}")


if __name__ == "__main__":
    main()

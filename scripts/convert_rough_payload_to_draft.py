from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from scripts.convert_leaf_draft_to_cards import (
    convert_entry,
    load_inventory,
    write_jsonl,
)


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


def render_field_value(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(str(item) for item in value)
    return str(value)


def normalize_entry(raw_card: dict[str, Any], inventory: dict[str, dict[str, Any]]) -> dict[str, Any]:
    node_id = raw_card["node_id"]
    if node_id not in inventory:
        raise KeyError(f"Unknown node_id: {node_id}")

    node = inventory[node_id]
    entry: dict[str, Any] = {"node_id": node_id}
    card_type = raw_card.get("card_type") or (
        "formula_card"
        if node["node_kind"] == "formula"
        else "method_card"
        if node["node_kind"] == "method"
        else "concept_card"
    )
    entry["card_type"] = card_type
    entry["title"] = raw_card.get("title") or node["name"]

    for key, value in raw_card.items():
        if key in {"node_id", "title"}:
            continue
        if value in (None, "", []):
            continue
        entry[key] = value
    return entry


def render_draft(entries: list[dict[str, Any]]) -> str:
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rough", required=True, help="Path to rough payload JSON")
    parser.add_argument("--out-draft", required=True, help="Output markdown draft path")
    parser.add_argument("--out-cards", help="Optional output cards jsonl path")
    parser.add_argument(
        "--source",
        default="rough_payload_bridge",
        help="Source label for generated cards",
    )
    args = parser.parse_args()

    rough_path = Path(args.rough)
    payload = json.loads(rough_path.read_text(encoding="utf-8"))
    cards = payload.get("cards")
    if not isinstance(cards, list):
        raise ValueError("rough payload must contain a top-level cards array")

    inventory = load_inventory()
    entries = [normalize_entry(card, inventory) for card in cards]
    draft_markdown = render_draft(entries)

    out_draft = Path(args.out_draft)
    out_draft.parent.mkdir(parents=True, exist_ok=True)
    out_draft.write_text(draft_markdown, encoding="utf-8")
    print(f"wrote draft: {out_draft}")

    if args.out_cards:
        out_cards = Path(args.out_cards)
        records = [
            convert_entry(entry=entry, inventory=inventory, source=args.source)
            for entry in entries
        ]
        write_jsonl(records, out_cards)
        print(f"wrote {len(records)} cards: {out_cards}")


if __name__ == "__main__":
    main()

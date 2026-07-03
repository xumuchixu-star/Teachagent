# TeachAgent Knowledge Inventory

This directory stores generated structured artifacts derived from `docs/math_knowledge_tree.md`.

## Files

- `knowledge_tree_typed_full.json`
  - Full node inventory, including parent nodes and leaves.
- `leaf_nodes_full.jsonl`
  - Leaf-only inventory for downstream card generation.

## Notes

- `node_id` currently uses a path-based Unicode slug for speed and stability while the tree is still evolving.
- `node_kind` is an initial heuristic classification:
  - `concept`
  - `formula`
  - `method`
  - `application`
- `review_role` and `binding_role` are also derived heuristically from `node_kind`.
- This inventory is the current working base for building leaf cards, not the final polished teaching ontology.

## Regeneration

Run:

```bash
python3 /Users/xumuchi/Desktop/TeachAgent/scripts/generate_knowledge_inventory.py
```

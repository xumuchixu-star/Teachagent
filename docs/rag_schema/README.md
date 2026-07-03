# TeachAgent RAG Layering

TeachAgent's review RAG should use three layers instead of forcing every concern into one markdown tree.

## 1. Knowledge Tree

- Owns hierarchy only.
- Decides parent/child structure, leaf boundaries, and stable `node_id`.
- Each leaf should expose:
  - `node_kind`: `concept`, `formula`, `method`, or `application`
  - `review_role`: `core` or `supporting`
  - `binding_role`: `primary_allowed` or `secondary_only`

Recommended rule:

- `concept` and `formula` leaves are usually `core`.
- `method` leaves are often `supporting`.
- A wrong question should usually bind `1` core leaf, plus at most `1` supporting leaf.

## 2. Leaf Cards

- These are the actual RAG chunks.
- One leaf node can emit one or more cards.
- The first card should be the leaf's primary card and should be directly embeddable.

Current minimal card types:

- `concept_card`
- `formula_card`
- `method_card`

Every card keeps a flattened `text` field for embedding and structured fields for downstream logic.

## 3. Relations

- Relations are not tree edges.
- They model retrieval-time expansion:
  - `prerequisite`
  - `uses_method`
  - `confusable_with`

This keeps the tree clean while still letting RAG expand to the right supporting cards.

## Retrieval Flow

1. Route a wrong question to candidate leaf nodes.
2. Retrieve the primary card of the chosen core leaf.
3. Expand one or two related cards through `relations` when needed.
4. Compose review context from the primary card plus supporting cards.

Preferred expansion order:

1. `prerequisite`
2. `uses_method`
3. `confusable_with`

## Files

- `typed_leaf_card_schema.json`
- `relation_schema.json`
- `wrong_question_binding_schema.json`
- `wrong_question_tree_annotation_schema.json`
- `review_state_schema.json`
- `student_memory_event_schema.json`
- `student_memory_profile_schema.json`
- `../rag_samples/knowledge_tree_typed_minimal.json`
- `../rag_samples/typed_leaf_cards_minimal.jsonl`
- `../rag_samples/knowledge_relations_minimal.jsonl`

## Wrong Question Annotation

- `wrong_question_binding_schema.json`
  - For machine-generated wrong-question to leaf binding outputs.
- `wrong_question_tree_annotation_schema.json`
  - For student-confirmed wrong-question annotation along the knowledge tree.
  - The system may recommend candidates, but the student makes the final selection.
  - It also leaves room for proposing missing nodes.

## Review State

- `review_state_schema.json`
  - For the actual review layer after leaves and question bindings are ready.
  - It tracks both knowledge-point review state and example-question review state.
  - It works for seeded example problems first, and later can absorb real wrong questions without changing the basic structure.

## Student Memory

- `student_memory_event_schema.json`
  - For the raw event layer behind long-term student memory.
  - Defines diagnosis / coach / review / binding / student-choice events.
  - This is the recommended upstream event contract before aggregation.

- `student_memory_profile_schema.json`
  - For the aggregated long-term student memory summary consumed by downstream agents.
  - This is the runtime-friendly compressed output that `coach_agent` and `review_scheduler` can read.

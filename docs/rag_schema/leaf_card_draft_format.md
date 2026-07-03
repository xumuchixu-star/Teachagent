# Leaf Card Draft Format

Use this format when asking a model to draft leaf cards before conversion into JSONL.

The converter does **not** accept arbitrary prose. It expects one block per `node_id`.

## Rules

- Start each card with `### <node_id>`.
- Each following line must be `- field_name: value`.
- List fields should use ` | ` as the separator.
- `node_id` must already exist in `docs/rag_inventory/leaf_nodes_full.jsonl`.
- `card_type` is optional. If omitted, the converter infers it from the inventory `node_kind`.

## Supported Card Types

- `concept_card`
- `formula_card`
- `method_card`

## Required Fields

### concept_card

- `keywords`
- `definition`
- `recognition_signals`
- `common_errors`
- `review_cue`

Optional:

- `aliases`
- `boundary`
- `core_idea`
- `example_refs`

### formula_card

- `keywords`
- `formula`
- `applicable_conditions`
- `special_cases`
- `common_errors`
- `review_cue`

Optional:

- `aliases`
- `variable_notes`
- `derivation_hint`
- `example_refs`

### method_card

- `keywords`
- `method_goal`
- `trigger_signals`
- `steps`
- `failure_modes`
- `review_cue`

Optional:

- `aliases`
- `applicable_problem_types`
- `example_refs`

## Example

```md
### math.统计与概率.概率.概率基本性质.互斥事件概念
- keywords: 互斥事件 | 不能同时发生 | 概率
- aliases: 互不相容事件
- definition: 如果事件 A 与事件 B 不能同时发生，则称 A 与 B 互斥。
- recognition_signals: 题目强调不能同时发生 | 需要判断事件是否有交集
- boundary: 互斥不等于相互独立。
- common_errors: 把互斥事件误当成独立事件 | 只看表面词语就判断互斥
- review_cue: 先问自己这两个事件能不能在一次试验里同时发生。

### math.数列与不等式.数列.等差_等比数列.等比数列求和公式
- keywords: 等比数列 | 求和公式 | 前n项和 | q=1
- formula: S_n = a_1(1-q^n)/(1-q) when q != 1; S_n = n a_1 when q = 1
- applicable_conditions: 目标是求等比数列前 n 项和 | 已知首项、公比、项数或足够信息
- special_cases: 必须分类讨论 q=1 和 q!=1
- common_errors: 漏分 q=1 和 q!=1 | 把 q^n 写错 | 项数和末项位置混淆
- review_cue: 做等比求和先别代公式，先判 q 是否等于 1。
```

## Conversion

```bash
python3 /Users/xumuchi/Desktop/TeachAgent/scripts/convert_leaf_draft_to_cards.py \
  --draft /path/to/draft.md \
  --out /path/to/cards.jsonl \
  --source model_draft
```

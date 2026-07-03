# TeachAgent Project Structure

这份文档只做一件事：把当前 `TeachAgent` 目录按职责整理清楚。

目标不是“完美重构”，而是先让你知道：

- 哪些是主干代码
- 哪些是知识树 / 卡片 / 复习的数据层
- 哪些是 notebook 实验
- 哪些只是 scratch 临时产物

---

## 1. 现在最重要的主线

目前项目其实有两条线：

- 教学对话线
  - 题目诊断、追问、讲解
- 知识树与复习线
  - 知识树
  - 叶子卡片
  - 错题 / 例题绑定
  - 复习状态

如果按你现在真正要推进的事情看，重点已经明显偏向第二条：

- 知识树叶子
- 叶子卡片
- 例题 / 错题绑定知识点
- 复习系统

所以现在看项目时，可以把“教学对话线”视为旧主线，把“知识树与复习线”视为当前主线。

---

## 2. 根目录文件

### 2.1 当前仍然重要

- `leaf_card_agent.py`
  - 已确认 `node_id` 后，生成 leaf card draft / cards
- `material_extractor.py`
  - 从原始文本、OCR 文本、笔记中抽取 topic / item
- `leaf_router.py`
  - 把抽取出的 item 路由到已有叶子，或建议新叶子
- `leaf_embedding_index.py`
  - 给叶子卡片构建 embedding 索引
- `wrong_question_binder.py`
  - 把题目绑定到知识树叶子，输出主知识点 / 次知识点 / top-k
- `review_scheduler.py`
  - 纯规则版复习调度器
  - 输入知识点状态和题目状态
  - 可选接入 `student_memory_profile` 做轻量优先级偏置
  - 输出知识点复习 / 错题复习 / 混合 bundle 推荐
- `student_memory_manager.py`
  - 学生个人定制记忆层 MVP
  - 汇总长期错因、反复卡住的叶子、教学偏好、练习偏好
  - 现在可直接承接 `diagnosis_agent.py` 与 `coach_agent.py` 的结构化输出
  - 输出 AI 可读记忆文本和轻量图谱
- `student_memory_events.py`
  - 学生记忆事件层
  - 统一构造 diagnosis / coach / review / binding / student_choice 事件
- `student_memory_store.py`
  - 学生记忆本地存储层 MVP
  - 当前先用 `JSONL` 事件库保存长期学习事件
  - 可按学生 / 题目 / 知识点过滤读取，并可从事件库重建 `student_memory_profile`
- `README.md`
  - 当前总入口说明

### 2.2 旧的教学线

- `coach_agent.py`
  - 教学对话 agent
  - 现在可选接入 `student_memory_profile` 做长期偏好辅助
- `diagnosis_agent.py`
  - 单轮错因诊断
- `diagnosis_orchestrator.py`
  - 诊断 + 教学编排

对应的两个独立演示脚本已经从根目录移到：

- `examples/coach_agent_demo.py`
  - 教学对话最小示例
- `examples/diagnosis_orchestrator_demo.py`
  - 诊断编排最小示例

这些文件不是没用，但不是你当前最优先的主线。

### 2.3 旧 notebook

这些文件已经下沉到：

- `notebooks/legacy/`

当前包括：

- `diagnosis_coach_full_demo.ipynb`
- `orchestrator_e2e_demo.ipynb`
- `sequence_4turn_demo.ipynb`
- `Untitled.ipynb`

这批文件偏旧教学线 / 临时试验，建议只做历史参考。

---

## 3. docs 目录

`docs/` 现在已经是项目里最重要的数据和说明层。

### 3.1 知识树源文件

- `docs/math_knowledge_tree.md`
  - 当前知识树 markdown 源
  - 后续如果继续维护知识树，最上游还是它

### 3.2 PRD / 思路记录

- `docs/prd/teachagent-prd.md`
  - 项目产品思路
- `docs/prd/wrong_question_leaf_binding_scheme.txt`
  - 错题绑定思路草稿

### 3.3 rag_inventory

这是“正式知识树库存层”。

- `docs/rag_inventory/knowledge_tree_typed_full.json`
  - 完整 typed 知识树
- `docs/rag_inventory/leaf_nodes_full.jsonl`
  - 全部叶子节点清单
- `docs/rag_inventory/node_overrides.json`
  - 对叶子类型、review role、binding role 的人工覆盖
- `docs/rag_inventory/README.md`
  - inventory 说明

你以后只要问“这个知识点在不在树里”，先看这里。

### 3.4 rag_schema

这是“结构定义层”，相当于项目的数据契约。

当前最重要的是：

- `typed_leaf_card_schema.json`
  - 叶子卡片结构
- `wrong_question_binding_schema.json`
  - 系统自动绑定结构
- `wrong_question_tree_annotation_schema.json`
  - 学生沿知识树确认绑定结构
- `review_state_schema.json`
  - 复习系统状态结构
- `leaf_card_draft_format.md`
  - draft markdown 的写法
- `wrong_question_batch_input_template.md`
  - 批量题目录入模板
- `README.md`
  - schema 总说明

如果你以后问“这条数据该长什么样”，先看这里。

### 3.5 rag_samples

这是“样例数据 + 产物层”，数量最多，也最容易显得乱。

它里面现在混着 4 类东西：

- 最小样例
  - `knowledge_tree_minimal.json`
  - `knowledge_tree_typed_minimal.json`
  - `typed_leaf_cards_minimal.jsonl`
  - `knowledge_chunks_minimal.jsonl`
  - `knowledge_relations_minimal.jsonl`

- 各章节叶子卡片 draft
  - 例如 `sequence_leaf_card_draft.md`
  - 例如 `plane_vector_triangle_batch_04_leaf_card_draft.md`

- 各章节叶子卡片正式 JSONL
  - 例如 `sequence_leaf_cards.jsonl`
  - 例如 `complex_number_batch_08_leaf_cards.jsonl`

- 例题 / 复习样例
  - `taizhou_simulated_exam_examples_batch_01.md`
  - `taizhou_simulated_exam_review_seed_batch_01.json`

简单说：

- `*_draft.md` 是“卡片草稿”
- `*_cards.jsonl` 是“正式卡片”
- `taizhou_*` 是“题目和复习样例”

---

## 4. scripts 目录

这里是“辅助转换脚本”，都比较实用。

- `generate_knowledge_inventory.py`
  - 从 `math_knowledge_tree.md` 生成 typed knowledge inventory
- `convert_leaf_draft_to_cards.py`
  - 把 draft markdown 转成正式 cards JSONL
- `convert_rough_payload_to_draft.py`
  - 把模型输出的 rough JSON 先规范成 draft markdown，再可继续转 cards

这 3 个脚本都建议保留。

---

## 5. notebooks 目录

这是现在比较合理的实验区，而且已经按阶段分组。

- `notebooks/01_leaf_pipeline/`
  - leaf pipeline 相关
- `notebooks/02_binding/`
  - 错题绑定相关
- `notebooks/03_review/`
  - review 调度与 session 相关
- `notebooks/04_memory/`
  - memory / profile / rules 相关
- `notebooks/05_system/`
  - 四部分总联调与用户展示
- `notebooks/legacy/`
  - 旧教学线 demo

建议以后新的 notebook 都只放 `notebooks/` 下对应分组，不再回到根目录。

如果只是想快速看现在系统能做什么，优先看：

- `notebooks/05_system/teachagent_user_walkthrough.ipynb`
- `notebooks/05_system/teachagent_system_overview.ipynb`

---

## 6. scratch 目录

这是临时产物区，只用于测试和排查。

总说明见：

- `scratch/README.md`

### 6.1 `scratch/leaf_agent_playground`

保存 leaf pipeline 的中间产物：

- `pipeline_extracted.json`
- `pipeline_routes.json`
- `pipeline_cards.jsonl`
- `offset_methods_*`

### 6.2 `scratch/wrong_question_binder_playground`

保存 binder 的测试输入输出：

- `sequence_geometric_shift_question.json`
- `sequence_geometric_shift_binding.json`
- `..._no_embedding.json`
- `..._with_embedding_check.json`

### 6.3 `scratch/source_ocr`

保存图片 OCR 文本：

- `640.txt`
- `640_1.txt`
- `640_2.txt`

### 6.4 根下 smoke 文件

- `scratch/wrong_question_binder_playground/smoke/binder_smoke_question.json`
- `scratch/wrong_question_binder_playground/smoke/binder_smoke_output.json`
- `scratch/wrong_question_binder_playground/smoke/binder_smoke_output_embedding.json`

这些都是临时调试文件，不属于正式资产。

---

## 7. 当前最清晰的理解方式

如果只从你当前主线出发，这个项目可以这样理解：

### A. 知识树层

- `docs/math_knowledge_tree.md`
- `docs/rag_inventory/*`

### B. 卡片生产层

- `material_extractor.py`
- `leaf_router.py`
- `leaf_card_agent.py`
- `scripts/convert_*`
- `docs/rag_samples/*leaf_card*`

### C. 检索 / 绑定层

- `leaf_embedding_index.py`
- `wrong_question_binder.py`
- `review_scheduler.py`
- `docs/rag_schema/wrong_question_binding_schema.json`
- `docs/rag_schema/wrong_question_tree_annotation_schema.json`

### D. 复习层

- `docs/rag_schema/review_state_schema.json`
- `docs/rag_samples/taizhou_simulated_exam_examples_batch_01.md`
- `docs/rag_samples/taizhou_simulated_exam_review_seed_batch_01.json`

### E. 实验层

- `notebooks/*`
- `scratch/*`
- `examples/*`

### F. 旧教学对话层

- `coach_agent.py`
- `diagnosis_agent.py`
- `diagnosis_orchestrator.py`

---

## 8. 你现在最该盯住的文件

如果你后面只想推进“知识树 -> 题目绑定 -> 复习系统”，优先盯这批：

- `docs/math_knowledge_tree.md`
- `docs/rag_inventory/leaf_nodes_full.jsonl`
- `docs/rag_schema/typed_leaf_card_schema.json`
- `docs/rag_schema/wrong_question_binding_schema.json`
- `docs/rag_schema/wrong_question_tree_annotation_schema.json`
- `docs/rag_schema/review_state_schema.json`
- `docs/rag_samples/taizhou_simulated_exam_examples_batch_01.md`
- `docs/rag_samples/taizhou_simulated_exam_review_seed_batch_01.json`
- `leaf_card_agent.py`
- `leaf_embedding_index.py`
- `wrong_question_binder.py`

---

## 9. 我对当前“乱”的判断

真正让你感觉乱的，不是代码太多，而是 3 类东西混在一起：

- 正式结构
- 样例产物
- 实验临时文件

目前最乱的地方主要有两个：

- 根目录里的主干 Python 模块仍然是平铺的
- `docs/rag_samples` 里同时混着：
  - 最小样例
  - 正式 cards
  - draft
  - 例题样例

但现在还没必要立刻大搬家。

更实际的做法是：

1. 先用这份文档稳定认知
2. 后面如果你愿意，我再帮你做一次“轻重构”

---

## 10. 如果后面要轻重构

我建议的目标结构会是：

- `agents/`
  - `leaf_card_agent.py`
  - `material_extractor.py`
  - `leaf_router.py`
  - `wrong_question_binder.py`
  - `coach_agent.py`
  - `diagnosis_agent.py`
  - `diagnosis_orchestrator.py`

- `docs/`
  - `rag_inventory/`
  - `rag_schema/`
  - `prd/`
  - `project_structure.md`

- `data/`
  - `leaf_cards/`
  - `example_questions/`
  - `review_states/`

- `notebooks/`

- `scratch/`

- `scripts/`

但这一步我建议等你下一阶段再做，不要现在为了“整洁”打断主线。

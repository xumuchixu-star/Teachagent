# TeachAgent 数据来源与四部分打通总表

这份文档回答四个问题：

- `TeachAgent` 现在有哪些主数据源？
- 这些数据分别被谁读取？
- 错题现在有哪些入口，它们会落到哪里？
- 你现在说的“四部分打通”到底通到了什么程度？

---

## 1. 先看四部分主链路

当前系统可以按下面这条主链路理解：

1. `知识树 + 叶子卡片`
   - 提供知识结构、叶子节点、卡片内容
2. `错题 / 题目绑定`
   - 题目可以绑定到一个或多个知识点
3. `复习系统`
   - 按知识点和题目状态安排复习
4. `长期画像`
   - 用历史事件生成学生长期偏置，再轻量影响 `diagnosis / coach / review`

再加一个输入层：

5. `OCR / 外部导入`
   - 把图片、PDF、拍照内容先转成可编辑题目草稿，再分发到上面几部分

---

## 2. 当前 App 真正在读的核心数据

`app/server.py` 是现在整个 App 的主入口。

它启动时真正读取的核心数据如下。

### 2.1 知识树主数据

- 路径：`docs/rag_inventory/knowledge_tree_typed_full.json`
- 变量：`TREE_DATA_PATH`
- 作用：
  - 作为知识点目录主库存
  - 支撑 `Wrongbook` 页面知识树
  - 支撑知识点路径、父子结构、挂题显示

### 2.2 默认复习状态

- 路径：`scratch/student_annotation_merged/student_annotation_merged_review_state.json`
- 变量：`DEFAULT_STATE_PATH`
- 作用：
  - 作为 App 默认 `review_state`
  - 支撑 `Review` 页面
  - 供 `review_scheduler.py` 和 `review_bundle_builder.py` 使用

### 2.3 默认长期画像

- 路径：`scratch/teachagent_system_overview/student_memory_profile_demo.json`
- 变量：`DEFAULT_MEMORY_PROFILE_PATH`
- 作用：
  - 作为当前 App 默认 `student_memory_profile`
  - 支撑 `diagnosis / coach / review` 的轻量个性化偏置

注意：

- 当前 App 直接读取这个现成的 `profile JSON`
- 不是每次都从事件流实时重建

### 2.4 App 运行时会话文件

这些文件属于“本地运行态增量数据”。

- `app/data/review_state.session.json`
  - 当前会话里的复习状态
- `app/data/tree_notes.session.json`
  - 题目笔记 / 知识点笔记
- `app/data/tree_custom_nodes.session.json`
  - 学生新建的知识点
- `app/data/wrongbook_custom_questions.session.json`
  - 学生新增的错题

它们的作用是：

- 把用户在 App 里的新增内容落在本地
- 不改动原始知识库主文件

---

## 3. 知识树与叶子卡片的数据来源

这一层属于“内容资产层”。

### 3.1 知识树上游源

- `docs/math_knowledge_tree.md`

作用：

- 最上游知识树文本源
- 后续会被转成结构化 inventory

### 3.2 结构化知识树库存

- `docs/rag_inventory/knowledge_tree_typed_full.json`
- `docs/rag_inventory/leaf_nodes_full.jsonl`
- `docs/rag_inventory/node_overrides.json`

生成脚本：

- `scripts/generate_knowledge_inventory.py`

作用：

- 形成 typed 知识树
- 形成所有叶子节点清单
- 作为知识树展示、路由、绑定的底层数据

### 3.3 叶子卡片正式数据

主要路径：

- `docs/rag_samples/*leaf_cards.jsonl`

例如：

- `docs/rag_samples/sequence_leaf_cards.jsonl`
- `docs/rag_samples/derivative_integral_leaf_cards.jsonl`
- `docs/rag_samples/plane_vector_triangle_batch_04_leaf_cards.jsonl`

读取方：

- `review_bundle_builder.py`
- `leaf_embedding_index.py`

作用：

- 作为叶子卡片主库
- 支撑复习系统里的知识点卡片展示
- 支撑后续向量化检索

### 3.4 叶子卡片草稿

主要路径：

- `docs/rag_samples/*leaf_card_draft.md`

转换脚本：

- `scripts/convert_leaf_draft_to_cards.py`

作用：

- 先由模型或人工写 draft
- 再规范化成正式 `leaf_cards.jsonl`

### 3.5 叶子 embedding 索引

路径：

- `docs/rag_index/leaf_embedding_index/leaf_embeddings.jsonl`
- `docs/rag_index/leaf_embedding_index/manifest.json`

生成方式：

- `python3 leaf_embedding_index.py build`

作用：

- 给叶子树做向量索引
- 主要服务于 `leaf_router.py`、`wrong_question_binder.py` 等检索需求

---

## 4. 题目、错题与复习种子的来源

### 4.1 例题主文件

- `docs/rag_samples/taizhou_simulated_exam_examples_batch_01.md`

代码入口：

- `review_bundle_builder.py` 里的 `DEFAULT_EXAMPLE_MD_PATH`

作用：

- 这是当前复习系统展示例题时最重要的样例题库
- 会被解析出：
  - 题目
  - 题型
  - 标准答案
  - 参考解析

### 4.2 复习状态种子

- `docs/rag_samples/taizhou_simulated_exam_review_seed_batch_01.json`

作用：

- 提供早期 review state seed
- 被 `review_scheduler.py` / `review_state_manager.py` 参考

### 4.3 绑定后的复习状态主文件

- `scratch/student_annotation_merged/student_annotation_merged_review_state.json`
- `scratch/student_annotation_merged/student_annotation_merged_review_state_v2.json`

桥接脚本：

- `annotation_to_review_state.py`

作用：

- 把“题目 + 绑定的知识点”转成复习系统可直接读取的 `review_state`
- 当前 App 默认使用第一份

---

## 5. Wrong Binder / 题目绑定层

这一层的目标是：

- 给一道题推荐知识点
- 或者至少给出 top-k 候选，供学生确认

当前相关代码：

- `wrong_question_binder.py`
- `leaf_router.py`

当前相关实验文件：

- `scratch/wrong_question_binder_playground/`
- `harness/fixtures/wrong_binder/`
- `harness/fixtures/wrong_binder_eval_v1/`

当前定位：

- 它已经能做“系统推荐”
- 但你现在的产品策略是：
  - 推荐可以保留
  - 最终还是允许学生沿知识树自己确认
  - 如果都不合适，允许学生新建知识点

---

## 6. OCR / 外部导入层

这一层现在由 `Import` 页面承接。

### 6.1 上传原始文件

路径：

- `scratch/ocr_uploads/<timestamp>/...`

作用：

- 存原始 PDF / 图片 / 拍照件

### 6.2 MinerU 解析产物

路径：

- `scratch/mineru_runs/...`

典型产物：

- `ocr_run_summary.json`
- `ocr_preview.txt`
- `*.md`
- `*_content_list.json`
- `*_model.json`

调用脚本：

- `scripts/run_mineru_extract.py`

App 接口：

- `POST /api/ocr/extract`

作用：

- 先 OCR
- 再把 OCR 文本拆成：
  - 题干
  - 答案
  - 解析
- 再在 Import 页生成“可编辑草稿”

---

## 7. 错题现在有哪些入口

你刚才说的三类入口，现在可以这样理解。

### 7.1 OCR 直接进错题本

路径：

1. 用户在 `Import` 页上传图片 / PDF
2. `MinerU` 识别后回到可编辑草稿
3. 用户点击 `前往错题本`
4. 内容被填入 `Wrongbook` 表单
5. 用户选择知识点后保存

当前保存位置：

- `app/data/wrongbook_custom_questions.session.json`
- 同时会合并进当前会话 `review_state.session.json`

当前来源标记：

- `source_type = ocr_direct`

这类题的特点是：

- 默认只有题目 / 答案 / 解析
- 不一定有错因
- 后续可以手动补错因或笔记

### 7.2 通过 Diagnosis 进入错题本

路径：

1. 用户把题目送进 `Diagnosis`
2. 诊断得到主错因、理由、证据
3. 用户点击 `转入错题本`
4. App 把题目、学生回答、诊断错因、诊断证据预填到 `Wrongbook`
5. 用户再确认知识点后保存

当前来源标记：

- `source_type = diagnosis_transfer`

这类题的特点是：

- 有题目
- 有学生回答
- 有诊断出来的主错因
- 更适合后面进入长期画像

### 7.3 学生手动加入错题本

路径：

1. 学生直接进入 `Wrongbook`
2. 手动选知识点
3. 手动填题目 / 答案 / 解析 / 备注
4. 保存

当前来源标记：

- `source_type = manual_entry`

这类题的特点是：

- 最灵活
- 也最依赖学生自己整理

### 7.4 通过 Coach 转入错题本

这条也是现在已经有的入口。

路径：

1. 题目进入 `Coach`
2. 多轮引导后，用户点击 `转入错题本`
3. 当前题目与学生最近一轮回复被预填入 `Wrongbook`

当前来源标记：

- `source_type = coach_transfer`

这类题的特点是：

- 更像“边讲边收集”
- 当前不会自动保存，仍然让学生最后确认一次

---

## 8. 错题保存后会进入哪里

当前错题保存后会进入两层。

### 8.1 Wrongbook 展示层

直接落在：

- `app/data/wrongbook_custom_questions.session.json`

用于：

- `Wrongbook` 页面按知识树展示错题
- 节点下显示本点直挂题 / 子树继承题

### 8.2 Review 复习层

保存错题时，后端会同时把这道题追加进：

- `current_review_state["example_question_states"]`

并落盘到：

- `app/data/review_state.session.json`

这意味着：

- 新加错题不只是“放在错题本里”
- 也已经进入复习系统可读取的题目池

所以从数据通路上说：

- `Wrongbook -> Review`
  已经是通的

---

## 9. 长期画像与记忆层

这里要区分两层：

- 聚合后的长期画像
- 原始事件流

### 9.1 当前 App 正在读的长期画像

- `scratch/teachagent_system_overview/student_memory_profile_demo.json`

作用：

- 给 `coach_agent.py`
- 给 `review_scheduler.py`
- 给 `diagnosis` 和首页摘要

### 9.2 事件流存储层

代码：

- `student_memory_events.py`
- `student_memory_store.py`
- `student_memory_manager.py`
- `student_memory_rules.py`

默认事件库路径：

- `data/student_memory/student_memory_events.jsonl`

支持的事件类型：

- `diagnosis`
- `coach`
- `review`
- `binding`
- `student_choice`

作用：

- 记录学习行为
- 后续可根据事件流重建 `student_memory_profile`

### 9.3 当前状态

现在这层是：

- 代码和 schema 已经搭好
- notebook / demo 已验证可行
- 但 App 运行时主要还是直接读取一个现成的 profile JSON
- 还没有把所有 App 用户动作自动持续写回正式事件库

也就是说：

- `长期画像可用`
- `自动持续长大` 这件事还没完全接到 App 主流程里

---

## 10. 四部分现在到底通到了什么程度

如果按你最关心的“打通”来讲，可以直接这样说。

### 10.1 已经打通的部分

- `Import -> Wrongbook`
  - 已通
- `Import -> Diagnosis`
  - 已通
- `Diagnosis -> Coach`
  - 已通
- `Diagnosis -> Wrongbook`
  - 已通
- `Coach -> Wrongbook`
  - 已通
- `Wrongbook -> Review`
  - 已通
- `知识树新增节点 -> Wrongbook 挂题`
  - 已通

### 10.2 半打通的部分

- `Wrong Binder -> 学生确认 -> Wrongbook`
  - 逻辑上通
  - App 页面里还没有做成一个完整独立入口
- `App 用户行为 -> student_memory_events.jsonl -> 重建 profile -> 回流到 diagnosis/coach/review`
  - 代码链路有
  - App 端还没有完全自动化

### 10.3 目前仍是本地优先

当前整体仍然是：

- 知识点主库：本地 JSON
- 新知识点：本地 session JSON
- 错题本：本地 session JSON
- 长期画像：本地 JSON / JSONL

这很符合你现在的策略：

- 先把四部分打通
- 再决定以后是否迁移到 SQLite / 云端

---

## 11. 最关键的几个代码入口

如果你以后只看最重要的主文件，可以先看这些：

- `app/server.py`
  - 当前 App 后端总入口
- `app/static/index.html`
  - 页面结构
- `app/static/app.js`
  - 页面交互、前后端串联
- `review_bundle_builder.py`
  - 复习内容组装
- `review_scheduler.py`
  - 复习排序
- `review_state_manager.py`
  - 复习动作写回
- `diagnosis_agent.py`
  - 诊断
- `coach_agent.py`
  - 引导
- `diagnosis_orchestrator.py`
  - `diagnosis -> coach` 串联
- `student_memory_store.py`
  - 事件存储

---

## 12. 一句话总结

现在的 `TeachAgent` 可以概括成：

- 知识点主树和叶子卡片来自 `docs/rag_inventory + docs/rag_samples`
- 默认复习状态和长期画像来自 `scratch/student_annotation_merged + scratch/teachagent_system_overview`
- App 里的新增错题、笔记、新知识点都先写到 `app/data/*.session.json`
- OCR、诊断、引导、错题本、复习系统已经基本串起来
- 长期画像已经能读，但事件自动沉淀和自动重建还属于下一步增强

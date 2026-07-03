# TeachAgent

TeachAgent 当前是一套围绕高中数学知识树搭建的本地工作区，重点不是前端，而是先把后端主链路和数据结构跑通。

现在这套系统已经不再只是 `CoachAgent + Leaf Pipeline`，而是可以按 4 个部分理解：

1. 知识树与叶子卡片
2. 错题 / 例题绑定与学生确认
3. 遗忘复习系统
4. 学生长期记忆层

如果你刚接手这个仓库，先看：

- `docs/project_structure.md`
- `docs/rag_schema/README.md`

如果你现在的目标是把这个项目对外发布，而不是继续本地开发，先看：

- `docs/deploy_web.md`
- `docs/github_render_launch_checklist.md`
- `render.yaml`
- `Dockerfile`

## 一、当前四个部分

### 1. 知识树与叶子卡片

目标：

- 维护稳定的知识树叶子
- 把材料加工成可检索的 leaf cards
- 为后续 RAG 和知识点复习提供统一 chunk

核心文件：

- `docs/math_knowledge_tree.md`
- `scripts/generate_knowledge_inventory.py`
- `docs/rag_inventory/knowledge_tree_typed_full.json`
- `docs/rag_inventory/leaf_nodes_full.jsonl`
- `material_extractor.py`
- `leaf_router.py`
- `leaf_card_agent.py`
- `scripts/convert_rough_payload_to_draft.py`
- `scripts/convert_leaf_draft_to_cards.py`
- `scripts/run_mineru_extract.py`
- `leaf_embedding_index.py`

这一部分当前的推荐链路是：

1. `math_knowledge_tree.md` 维护知识树
2. `generate_knowledge_inventory.py` 生成 typed inventory
3. `material_extractor.py` 从原始文本 / OCR / 笔记中抽条目
4. `scripts/run_mineru_extract.py` 先把 PDF / 图片转成 markdown/json/txt OCR 产物
5. `leaf_router.py` 给条目做知识点路由
6. `leaf_card_agent.py` 为确认后的叶子生成卡片
7. `convert_*` 脚本把 rough / draft 规范成正式 JSONL
8. `leaf_embedding_index.py` 为叶子建立 embedding 索引

### 2. 错题 / 例题绑定与学生确认

目标：

- 系统先给出知识点推荐
- 学生再沿知识树确认或补充知识点
- 绑定结果可继续流入复习系统

核心文件：

- `wrong_question_binder.py`
- `annotation_to_review_state.py`
- `docs/rag_schema/wrong_question_binding_schema.json`
- `docs/rag_schema/wrong_question_tree_annotation_schema.json`

这一部分分两层：

- 系统自动推荐
  - `wrong_question_binder.py`
  - 输出 `primary_node_id`、`secondary_node_ids`、`top_k_node_ids`、`coarse_subtrees`
- 学生最终确认
  - `wrong_question_tree_annotation_schema.json`
  - 支持学生沿知识树选择，也支持补充缺失知识点

确认后的题目记录可以通过 `annotation_to_review_state.py` 转进复习状态。

### 3. 遗忘复习系统

目标：

- 同时调度知识点复习和题目复习
- 支持学生按钮反馈
- 支持题目优先 / 知识点优先 / 混合复习

核心文件：

- `review_state_manager.py`
- `review_scheduler.py`
- `review_bundle_builder.py`
- `annotation_to_review_state.py`
- `docs/rag_schema/review_state_schema.json`

这一部分的职责拆分是：

- `annotation_to_review_state.py`
  - 把题目绑定 / 学生确认结果导成初始 `review_state`
- `review_state_manager.py`
  - 接收学生操作，更新知识点和题目的状态
- `review_scheduler.py`
  - 根据遗忘、到期、掌握度、session boost、memory bias 计算优先级
- `review_bundle_builder.py`
  - 把优先级结果组装成适合前端展示的 bundle
  - 支持知识点卡片先出、题目答案默认隐藏、按钮动作显式返回

### 4. 学生长期记忆层

目标：

- 把诊断、引导、复习、绑定、学生选择沉淀成长期事件
- 从事件重建 `student_memory_profile`
- 再把 profile 翻译成下游规则，轻量影响 coach 和 review

核心文件：

- `student_memory_events.py`
- `student_memory_store.py`
- `student_memory_manager.py`
- `student_memory_rules.py`
- `diagnosis_agent.py`
- `coach_agent.py`
- `diagnosis_orchestrator.py`
- `docs/rag_schema/student_memory_event_schema.json`
- `docs/rag_schema/student_memory_profile_schema.json`

当前主链路是：

1. 各模块先产出结构化结果
2. `student_memory_events.py` 把结果统一转成事件
3. `student_memory_store.py` 追加写入本地 JSONL 事件库
4. `student_memory_manager.py` 按时间回放事件，生成 `student_memory_profile`
5. `student_memory_rules.py` 把 profile 翻译成 coach / review 可消费的规则

这层现在先走本地规则，不依赖图数据库或 Cognee 运行时。

## 二、主数据流

如果只看当前主线，TeachAgent 可以按下面这条链理解：

1. 知识树源文件
   - `docs/math_knowledge_tree.md`
2. 结构化知识库存
   - `scripts/generate_knowledge_inventory.py`
   - `docs/rag_inventory/*`
3. 叶子卡片生成
   - `material_extractor.py -> leaf_router.py -> leaf_card_agent.py`
   - `scripts/convert_* -> docs/rag_samples/*leaf_cards.jsonl`
4. 叶子 embedding 索引
   - `leaf_embedding_index.py`
   - `docs/rag_index/leaf_embedding_index/*`
5. 题目绑定与学生确认
   - `wrong_question_binder.py`
   - `wrong_question_tree_annotation_schema.json`
6. 复习状态与复习包
   - `annotation_to_review_state.py`
   - `review_state_manager.py`
   - `review_scheduler.py`
   - `review_bundle_builder.py`
7. 长期记忆沉淀与回流
   - `student_memory_events.py`
   - `student_memory_store.py`
   - `student_memory_manager.py`
   - `student_memory_rules.py`
   - 最终回流到 `coach_agent.py` 和 `review_scheduler.py`

## 三、目录怎么读

- 根目录 `*.py`
  - 现在主要保留主干模块
  - 也就是 leaf / binder / review / memory 这条主线的核心代码
- `docs/rag_inventory/`
  - 正式知识树库存层
- `docs/rag_schema/`
  - 数据契约层，定义各种 JSON 结构
- `docs/rag_samples/`
  - 叶子卡片样例、题目样例、review seed
- `docs/rag_index/`
  - embedding 索引产物
- `docs/prd/`
  - 方案文档、harness 说明、memory 说明
- `notebooks/`
  - 主要实验与 demo 入口
  - 现在已按阶段分组，建议先看 `notebooks/README.md`
- `examples/`
  - 两个独立演示脚本
  - 主要服务旧教学对话线的快速 smoke demo
- `app/`
  - 本地最小复习前端 MVP
  - 直接连 `review_bundle_builder.py` 和 `review_state_manager.py`
- `harness/`
  - 自动评测入口
- `scratch/`
  - 临时产物区，不是正式数据层
  - 建议先看 `scratch/README.md`

## 四、建议先看的 notebook

按四个部分分别看，最顺手的是这几本：

- Part 1
  - `notebooks/01_leaf_pipeline/leaf_pipeline_playground.ipynb`
  - `notebooks/01_leaf_pipeline/leaf_card_agent_ocr_playground.ipynb`
  - `notebooks/01_leaf_pipeline/mineru_ocr_playground.ipynb`
- Part 2
  - `notebooks/02_binding/wrong_question_binder_playground.ipynb`
- Part 3
  - `notebooks/03_review/review_scheduler_playground.ipynb`
  - `notebooks/03_review/review_bundle_playground.ipynb`
  - `notebooks/03_review/review_session_demo.ipynb`
- Part 4
  - `notebooks/04_memory/student_memory_store_profile_demo.ipynb`
  - `notebooks/04_memory/diagnosis_coach_memory_profile_demo.ipynb`
  - `notebooks/04_memory/coach_memory_bias_compare_demo.ipynb`
  - `notebooks/04_memory/end_to_end_memory_rule_demo.ipynb`
- 整体联调
  - `notebooks/05_system/teachagent_system_overview.ipynb`
  - `notebooks/05_system/teachagent_user_walkthrough.ipynb`

## 五、当前 harness 覆盖什么

当前 harness 已经成型，但还不是四部分全覆盖。

入口：

- `harness/run_wrong_binder_harness.py`
- `harness/run_review_harness.py`
- `harness/run_all_harness.py`

当前主要覆盖：

- `wrong_binder`
  - 看 top-k 召回、主知识点、粗路由方向
- `review_flow`
  - 看知识点 / 题目在按钮反馈后的排序和回炉是否符合预期

运行方式：

```bash
python3 harness/run_all_harness.py
```

报告输出目录：

## 六、PDF / 图片 OCR 入口

现在已经接好一个独立的 `MinerU` 入口，专门先做：

- 题目 PDF / 图片
- 解析截图
- 学生笔记图片

统一落到 `scratch/mineru_runs/`，不直接写进错题库。

命令行入口：

```bash
python3 scripts/run_mineru_extract.py \
  --input /绝对路径/题目图片.png \
  --run-name demo_math_page \
  --backend pipeline \
  --lang ch \
  --method ocr \
  --formula \
  --no-table
```

默认产物：

- `ocr_preview.txt`
  - 方便你快速看 OCR 文本，后续也最适合继续做人审或切题
- `ocr_run_summary.json`
  - 记录本次输入、输出目录、主 markdown 路径
- `640.md / *_content_list.json / *_middle.json / *_model.json`
  - MinerU 原始结构化产物

推荐 notebook：

- `notebooks/01_leaf_pipeline/mineru_ocr_playground.ipynb`

当前经验：

- 数学题图建议先用 `--formula --no-table`
- 第一次运行会下载较大的公式 / 版面 / OCR 模型
- 同类文件第二次开始会明显快很多

- `harness/reports/`

说明：

- 这套 harness 目前更偏 Part 2 + Part 3
- Part 1 和 Part 4 现在主要还是靠 notebook demo 和人工检查

## 六、快速命令

在仓库根目录下，最常用的几个命令是：

```bash
python3 scripts/generate_knowledge_inventory.py
python3 leaf_embedding_index.py build
python3 harness/run_all_harness.py
```

如果需要模型调用，当前代码默认会读这些环境配置：

- `AZURE_AI_PROJECT_ENDPOINT`
- `AZURE_AI_MODEL_DEPLOYMENT`
- `AZURE_AI_EMBEDDING_DEPLOYMENT`
- `AZURE_AI_API_KEY`

有些 notebook 也支持本机 `az login` 后走默认凭证。

如果你要直接试前端 MVP：

```bash
python3 app/server.py
```

然后打开 `http://127.0.0.1:8765`

## 七、当前已知限制

这几条在开始写 app 前最好心里有数：

1. 项目路径现在仍有硬编码
   - 很多文件直接写了 `ROOT = Path("/Users/xumuchi/Desktop/TeachAgent")`
   - 在真正做 app 或迁移机器前，最好统一抽成配置
2. 自动评测还没覆盖全部四部分
   - 现在 harness 重点是 binder 和 review
   - leaf pipeline / memory layer 仍以 notebook 为主
3. `scratch/` 下的东西都是临时产物
   - 可用于 demo、排错、对比
   - 不建议当正式数据源依赖
4. 旧教学线 notebook 已经下沉到 `notebooks/legacy/`
   - 例如 `diagnosis_coach_full_demo.ipynb`
   - 现在更建议优先看 `notebooks/05_system/` 和对应阶段分组
5. 根目录 Python 模块仍然是平铺的
   - 现在只是先把 notebook 和 demo 收口
   - 真正的 `agents/` / `review/` / `memory/` 分包还没做

## 八、开始写 app 前的建议

我赞成先做一次“四部分总测”，再开始写 app。

原因很简单：

- 现在每个局部都能跑，不代表整体串起来就稳定
- app 一旦开始写，最怕接口半路改 schema
- 先有一个总 notebook，后面你每改一层都能回归验证

我建议下一个新增物是一个总 notebook，例如：

- `notebooks/05_system/teachagent_system_overview.ipynb`

建议内容按 4 段来：

1. 从知识树 inventory 抽一个叶子，看 leaf card 长什么样
2. 输入一道题，跑 `wrong_question_binder.py`，再模拟学生手动确认
3. 把确认结果转成 `review_state`，生成 bundle，再模拟点几个按钮
4. 把 diagnosis / coach / review 事件写入 memory store，重建 profile，观察它如何轻量影响 coach 和 review

这样你在写 app 时，就有一个很稳定的“总集成冒烟本”。

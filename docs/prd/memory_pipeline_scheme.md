# TeachAgent 学生长期记忆 Pipeline Scheme

这份文档只解决一个问题：

- 学生长期画像应该怎么积累、更新、读取

你前面已经确定两件事：

1. `coach_agent` 可以轻度读取 `student_memory_profile`
2. `review_scheduler` 可以轻度读取 `student_memory_profile`

所以现在关键不是“要不要做记忆”，而是：

- 原始学生数据如何沉淀
- 长期画像何时生成
- 运行时到底读什么

这份 scheme 的结论先写在最前面：

- 每次学习事件都写入底层记忆库
- 不建议每次诊断都直接读取整份图谱
- 运行时优先读取压缩后的 `student_memory_profile`
- 长期画像采用“定时 + 触发式”更新，而不是每次实时重建

---

## 1. 目标

这一层最终要服务 4 件事：

1. 给 `coach_agent` 提供长期教学偏好辅助
2. 给 `review_scheduler` 提供长期复习优先级辅助
3. 给后续学生总结 / 个性化推荐提供可解释数据
4. 给未来 `Cognee / 图谱 / 向量记忆` 留出统一入口

它不直接替代当前题的诊断，也不直接替代当前题的知识点绑定。

它做的是：

- 把一次次局部观察，沉淀成稳定一些的长期画像

---

## 2. 先区分四层

推荐把学生记忆分成四层，而不是把所有东西都塞给模型现读。

### 2.1 事件层

这是最底层。

每发生一次真实学习行为，都记录成事件。

例如：

- 一次 diagnosis 结果
- 一次 coach 多轮引导
- 一次错题绑定
- 一次复习反馈
- 一次学生手动选择知识点
- 一次学生主动标记“这个知识点我还是不会”

这一层的原则是：

- 尽量保留原始观察
- 少做强结论
- 可回放、可重算

### 2.2 记忆库层

这是底层存储层。

以后可以是：

- 本地 JSON / SQLite
- 图数据库
- `Cognee`
- 向量库 + 关系表

在当前方案里，这一层的职责不是“直接给 agent 每次现读”，而是：

- 保存事件
- 保存事件之间的关系
- 支持后续重建长期画像

### 2.3 长期画像层

这是当前真正给系统消费的摘要层。

也就是现在已经存在的：

- `student_memory_profile`

它是：

- 从多条事件中提炼出来的稳定摘要

不是：

- 原始事件全集

### 2.4 运行时读取层

这是 `diagnosis / coach / review` 真正使用的一层。

当前推荐默认只读：

- `student_memory_profile.personalization_summary`
- `student_memory_profile.node_memories`
- `student_memory_profile.question_memories`

除非是少数高价值场景，不建议直接把整份图谱丢进 prompt。

---

## 3. 为什么不建议“每次诊断都直接读 Cognee”

这是最重要的设计判断。

我的结论是：

- 不推荐每次 diagnosis 都直接读完整 `Cognee`

原因有 5 个。

### 3.1 噪音太大

学生的原始事件会很多，而且质量不一：

- 有些是一次性偶然失误
- 有些是模型误判
- 有些是学生随手点的反馈

如果每次诊断都读整份图谱，模型会读到很多不该在当前轮起决定作用的噪声。

### 3.2 成本和延迟太高

`diagnosis_agent` 和 `coach_agent` 是高频调用链。

如果每次都：

- 查图谱
- 拉一堆历史节点
- 再让模型解释这些历史

那延迟和 token 成本都会明显上升。

### 3.3 早期数据容易过拟合

学生刚开始只有几道题时，图谱里的信息本来就很薄。

如果每次都让模型去读，很容易出现这种问题：

- 只凭 2 到 3 个事件就下很重的长期结论

这和你前面已经定下来的“轻观察 -> 稳定模式”原则是冲突的。

### 3.4 当前系统已经有一个更合适的消费接口

现在 `coach_agent.py` 和 `review_scheduler.py` 都已经接到了：

- `student_memory_profile`

这说明当前项目的运行时消费接口，其实已经自然收敛成：

- 运行时读摘要

没必要再把主链路拉回“每次现读全图谱”。

### 3.5 图谱更适合做“总结”和“重建”

`Cognee` 更适合承担的是：

- 记忆沉淀
- 关系组织
- 阶段性总结
- 局部历史追溯

而不是每次都作为首层 prompt 输入。

---

## 4. 推荐的总体策略

推荐策略可以压缩成一句话：

- 每次都写事件；每次运行只读摘要；定期或触发式重建摘要。

展开后就是：

### 4.1 写入策略

每次有新学习行为，就写入底层记忆库。

### 4.2 读取策略

运行时优先只读 `student_memory_profile`，不直接读完整图谱。

### 4.3 更新策略

长期画像不必每次实时完整重建，而是：

- 轻量统计可实时更新
- 模型参与的总结 / 重建采用“定时 + 触发式”

---

## 5. 推荐的数据流

建议用下面这条主线：

### 5.1 写入事件

来源包括：

- `diagnosis_agent.py`
- `coach_agent.py`
- `wrong_question_binder.py`
- 学生手动树选知识点
- `review_scheduler.py` 对应的复习反馈
- `review_state_manager.py` 的状态变更

写入到底层记忆库。

### 5.2 事件入库后做轻量聚合

这一步可以本地完成，不一定每次都调用模型。

例如更新：

- `error_type_counts`
- 某个 node 的 `observed_wrong_count`
- 某道题的 `wrong_count`
- 某个 node 最近 7 天的重复错误次数
- 学生更常点击“需要更多题”还是“已掌握”

### 5.3 到触发点时，重建 `student_memory_profile`

这一步由：

- `student_memory_manager.py`

负责，必要时可以引入模型总结，也可以先规则化完成第一版。

### 5.4 运行时消费

- `coach_agent.py` 读取 `personalization_summary`
- `review_scheduler.py` 读取 `node_memories / question_memories`
- 未来前端读取摘要做学生画像展示

---

## 6. 事件层建议

如果后面接 `Cognee`，建议先把事件层稳定住。

可以分成 5 类事件。

### 6.1 DiagnosisEvent

表示这道题这一次被诊断成什么错因。

建议最少包含：

- `event_id`
- `student_id`
- `timestamp`
- `question_id`
- `primary_node_id`
- `secondary_node_ids`
- `error_type`
- `confidence`
- `reason`
- `evidence`
- `source`

### 6.2 CoachEvent

表示一次引导过程中的一轮或一组观察。

建议最少包含：

- `event_id`
- `student_id`
- `timestamp`
- `question_id`
- `turn_index`
- `reply_quality`
- `understands`
- `completed`
- `strategy_mode`
- `strategy_trap`
- `strategy_prompt`
- `stop_reason`

### 6.3 ReviewEvent

表示一次复习反馈。

建议最少包含：

- `event_id`
- `student_id`
- `timestamp`
- `target_type`
  - `node` / `question`
- `target_id`
- `result`
  - `correct` / `wrong` / `skip_temporarily` / `needs_more_practice` / `mastered_well`
- `linked_node_ids`
- `linked_question_ids`
- `source`

### 6.4 BindingEvent

表示这道错题最终绑到了哪些知识点。

建议最少包含：

- `event_id`
- `student_id`
- `timestamp`
- `question_id`
- `primary_node_id`
- `secondary_node_ids`
- `binding_source`
  - `system_recommendation`
  - `student_confirmed`
  - `student_created_new_node`

### 6.5 StudentChoiceEvent

表示学生自己的主动选择。

这类事件以后价值会很高。

建议最少包含：

- `event_id`
- `student_id`
- `timestamp`
- `action_type`
  - `select_node`
  - `create_node`
  - `mark_important`
  - `request_more_examples`
  - `mark_mastered`
- `target_id`
- `note`

---

## 7. Cognee 在这里最适合扮演什么角色

推荐把 `Cognee` 当成：

- 学生长期学习事件和关系的底层记忆库

不推荐把它当成：

- 每次诊断时直接现读的 prompt 大仓库

更具体地说，`Cognee` 适合存：

### 7.1 实体

- Student
- Question
- KnowledgeNode
- DiagnosisEvent
- CoachEvent
- ReviewEvent
- StudentChoiceEvent

### 7.2 关系

- `student -> attempted -> question`
- `question -> bound_to -> node`
- `student -> repeatedly_struggles_with -> node`
- `review_event -> targets -> node/question`
- `diagnosis_event -> classified_as -> error_type`
- `coach_event -> follows -> diagnosis_event`

### 7.3 图谱用途

- 支持长期回溯
- 支持阶段性总结
- 支持生成 `student_memory_profile`
- 支持以后做学生学习轨迹可视化

---

## 8. `student_memory_profile` 仍然是当前主消费接口

这一点建议不要动。

原因是它已经自然适配了当前系统：

- `coach_agent.py`
- `review_scheduler.py`
- 后续前端画像展示

所以建议保持：

- `Cognee` 是底层沉淀
- `student_memory_profile` 是运行时摘要

也就是说：

- 图谱层负责“记住一切”
- 摘要层负责“给当前系统稳定可控地使用”

---

## 9. 什么时候更新长期画像

推荐采用：

- 定时 + 触发式 混合更新

### 9.1 定时更新

建议至少有一种固定刷新机制。

例如：

- 每天夜里刷新一次
- 每次学生新 session 开始前刷新一次

作用：

- 把最近事件沉淀成较稳定摘要
- 避免长时间只依赖旧画像

### 9.2 触发式更新

满足下面任一条件时，触发一次画像重建：

- 新增错题达到 `3-5` 道
- 新增学习事件达到 `8-10` 条
- 同一知识点在 7 天内重复错 `2` 次以上
- 学生手动创建了新知识点或明显改了绑定
- 学生主动点击“更新我的学习画像”

### 9.3 不建议每次都完整重建

每次事件都完整重建画像的问题是：

- 成本高
- 噪声大
- 早期数据过度波动

所以更合理的是：

- 轻量计数实时更新
- 高层总结延后重建

---

## 10. 什么时候需要直接读图谱

虽然默认不建议每次都读完整图谱，但也有例外。

推荐只在下面几类场景直接查图谱：

### 10.1 阶段性学生总结

例如：

- 这个学生最近一周最常错什么
- 哪些知识点已经稳定改善
- 最近教学策略是否该切换

### 10.2 当前题很模糊时的局部追溯

例如：

- 当前题绑定不确定
- 当前题错因不稳定
- 想临时查“这个学生之前在同类题上是怎么卡住的”

这时可以只检索局部相关事件，而不是整图谱全读。

### 10.3 老师 / 家长查看学习轨迹

图谱层很适合做：

- 可解释历史
- 主题聚类
- 学习轨迹回放

---

## 11. 当前最推荐的落地路径

为了不把工程复杂度一下拉太高，建议按三步走。

### 11.1 第一步：先稳定事件层

现在先不急着真的接 `Cognee`。

先把这几类事件的结构固定下来：

- diagnosis event
- coach event
- review event
- binding event
- student choice event

这样以后换存储层时，不会反复改上游。

### 11.2 第二步：继续用 `student_memory_manager.py` 生成画像

也就是：

- 不管底层以后是 JSON、SQLite 还是 Cognee
- 上层画像生成逻辑继续收敛到 `student_memory_manager.py`

这样你现有的 `coach_agent` 和 `review_scheduler` 不用推倒重来。

### 11.3 第三步：再把事件层接到 Cognee

当事件层稳定后，再做：

- event -> cognee ingestion
- cognee -> profile rebuild

这时图谱接入的收益才会明显。

---

## 12. 推荐的运行时读取策略

### 12.1 Diagnosis

默认读取：

- 不读完整图谱
- 如有需要，只读 `student_memory_profile.personalization_summary`

作用：

- 轻度帮助判断“这次更像概念问题还是策略问题”

但要严格限制：

- 不允许长期画像覆盖当前题证据

### 12.2 Coach

默认读取：

- `personalization_summary`

必要时补充：

- 当前题相关 `node_memories`

作用：

- 轻度调整讲解方式

### 12.3 Review Scheduler

默认读取：

- `node_memories`
- `question_memories`
- `personalization_summary.recommended_review_mode`

作用：

- 给复习排序轻度偏置

### 12.4 阶段性报告

可直接读取：

- `student_memory_profile`
- 局部相关图谱事件

作用：

- 做学生画像总结

---

## 13. 推荐的工程结论

如果只保留一句决策建议，就是这句：

- 不要每次诊断都让模型现读整份 Cognee；应当每次写事件、周期性生成 `student_memory_profile`，运行时主要读取这个摘要。

这是当前最符合你项目状态的方案，因为它同时满足：

- 简洁
- 可落地
- 与现有代码兼容
- 后续能升级到真正图谱记忆

---

## 14. 和当前代码的对应关系

当前已经有的主干可以继续保留：

- `student_memory_manager.py`
  - 负责长期画像生成
- `coach_agent.py`
  - 读取长期画像做轻辅助
- `review_scheduler.py`
  - 读取长期画像做轻排序偏置
- `diagnosis_agent.py`
  - 后续可轻度读取摘要，但不建议直接读完整图谱

未来如果接 `Cognee`，建议新增的职责更像是：

- `student_memory_events.py`
  - 统一事件 schema / event builder
- `student_memory_store.py`
  - 本地存储层或 Cognee 适配层
- `student_memory_rebuilder.py`
  - 从事件层 / 图谱层重建 `student_memory_profile`

这样结构会更清晰。

---

## 15. 当前阶段的建议优先级

如果你明天继续做，我建议顺序是：

1. 先把事件层 schema 整理出来
2. 先用本地 JSON / SQLite 跑通事件沉淀
3. 再考虑接 Cognee
4. 最后再做“局部图谱检索 -> 阶段性学生总结”

因为现在最重要的不是“图谱技术本身”，而是：

- 长期记忆的数据流先闭环

只要这条闭环稳定，后面换底层存储都不难。

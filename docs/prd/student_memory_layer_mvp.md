# TeachAgent 学生记忆层 MVP

这份文档定义现在的第四阶段：

- 学生个人定制记忆
- 错因长期总结
- 个性化教学倾向
- 个性化复习倾向
- 面向未来向量图谱 / Cognee 的导出接口

这版先不追求“真正智能记忆系统”，而是先把最小可用结构落下来。

---

## 1. 目标

这层要解决两个问题：

### 1.1 长期错因总结

系统不能只看“这道题这次错了什么”，还要看：

- 这个学生最近最常见的错因是什么
- 哪些知识点反复卡住
- 他更需要讲概念、讲思路，还是多练题、多检查

例如：

- `missing_strategy` 多
  - 讲题时优先讲路线、讲中间目标
  - 出题时多给“同方法不同外壳”的题

- `concept_gap` 多
  - 讲题时先讲知识点，不急着上题
  - 复习模式更偏 `leaf_first`

- 某个叶子一直反复错
  - 说明不是“偶然不会”，而是长期没懂
  - 要给这个叶子打上 `reteach_concept` 或 `show_strategy_first`

### 1.2 AI 可读的学生记忆

系统后面不只会做调度，还可能做：

- AI 讲题
- AI 出题
- AI 追问
- AI 总结学生学习画像

所以需要一层：

- AI 直接能读的个性化记忆

这层以后可以导到：

- 向量库
- 图谱系统
- Cognee 一类长期记忆系统

---

## 2.1 记忆结论不要一开始就太重

这层现在增加一个很重要的原则：

- 数据少时，先输出“轻观察”
- 数据多时，再升格成“稳定记忆”

也就是说：

- 1 道题、1 次诊断，不应该像已经看透这个学生
- 只有当同类错因、同类叶子、同类复习行为反复出现时，才把它写成更强的长期画像

当前实现里会区分：

- `signal_strength`
  - `tentative`
  - `established`

- `memory_stage`
  - `early_observation`
  - `forming_pattern`

这样后面无论是前端、review 系统还是 AI 教练，都能知道：

- 这只是当前观察
- 还是已经形成比较稳定的个性化记忆

---

## 2. 当前 MVP 包含什么

当前已经实现一个独立 manager：

- `student_memory_manager.py`

它负责 5 件事：

1. 维护学生总体错因分布
2. 维护每个知识点的长期记忆状态
3. 维护每道题的长期记忆状态
4. 生成个性化教学 / 练习建议
5. 导出 AI 可读文本和轻量图谱

---

## 3. 输入来源

这层目前吃两类输入：

### 3.1 诊断事件

来源：

- `diagnosis_agent.py`
- `diagnosis_orchestrator.py`

主要字段：

- `error_type`
- `reason`
- `evidence`
- `question_id`
- `primary_node_id`
- `secondary_node_ids`

作用：

- 告诉记忆层“这道题错在哪”
- 更新全局错因统计
- 更新某个知识点的长期错因结构

现在这层已经支持直接吃接近真实链路的结构：

- `DiagnosisResult.as_dict()`
- 再加上题目 id 与绑定到的叶子上下文

也就是说，不要求你专门再造一套“学生记忆专用诊断格式”。

### 3.2 coach 过程事件

来源：

- `coach_agent.py`

主要字段：

- `reply_quality`
- `reply_analysis`
- `strategy.mode`
- `strategy.trap`
- `strategy.prompt`
- `turn_index`
- `done`
- `stop_reason`

作用：

- 告诉记忆层“学生在引导过程中是完全不会、部分懂了，还是已经补上来了”
- 后面可以把“同一知识点总是要讲到第几轮才懂”也纳入个性化记忆
- 为以后把 diagnosis / coach / review 串成完整学生画像打基础

### 3.3 复习状态 / 复习事件

来源：

- `review_state_manager.py`
- `review_scheduler.py`
- `annotation_to_review_state.py`

主要字段：

- `knowledge_point_states`
- `example_question_states`
- `review_result`
- `node_needs_more_practice`
- `node_mastered_well`
- `skip_temporarily`

作用：

- 告诉记忆层“学生后来练得怎么样”
- 判断某个叶子是不是反复不会
- 判断教学重点要不要从“做题”切回“讲知识点”

---

## 4. 当前输出结构

结构定义在：

- `docs/rag_schema/student_memory_profile_schema.json`

主要对象：

### 4.1 全局学生画像

- `error_type_counts`
- `teaching_preferences`
- `practice_preferences`
- `personalization_summary`

### 4.2 知识点长期记忆

- `node_memories`

每个叶子记录：

- 错因分布
- 复习错题次数
- 连续错误次数
- `mastery_hint`
- `stability_hint`
- `recommended_intervention`

当前 `recommended_intervention` 可能有：

- `reteach_concept`
- `show_strategy_first`
- `drill_with_checklist`
- `read_conditions_first`
- `stabilize_with_examples`

### 4.3 题目长期记忆

- `question_memories`

每道题记录：

- 链接到哪些叶子
- 最近错因
- 错误次数 / 复习次数
- 最近结果

### 4.4 AI 记忆文本

- `agent_memory_text`

这是最重要的 prompt-ready 输出之一。

它会把学生最近的情况压缩成几行：

- 当前主错因
- 推荐讲法
- 推荐复习模式
- 反复卡住的叶子
- 当前教学重点

### 4.5 轻量图谱

- `memory_graph`

当前图谱不是正式图数据库，只是一个导出结构：

- `nodes`
- `edges`

里面会保留：

- 学生节点
- 错因节点
- 反复困难叶子节点
- 高频错题节点

后面如果你要接 Cognee 或向量图谱，可以直接从这里继续做。

---

## 4.1 现在和旧教学链路的关系

这次补完后，第四阶段不再是平行小系统，而是已经能接在你前面的链路后面：

1. `diagnosis_agent.py`
   - 产出主错因、诊断理由、证据、建议 coach 策略
2. `coach_agent.py`
   - 产出每轮引导质量、是否理解、是否完成、使用了什么教学策略
3. `student_memory_manager.py`
   - 汇总长期错因模式
   - 汇总哪些叶子反复卡住
   - 汇总学生更适合哪种讲法、哪种练法

所以现在这层的定位是：

- diagnosis 负责“这一题现在错在哪”
- coach 负责“这一轮怎么讲”
- memory 负责“这个学生长期是怎样的人”

而且现在已经有两个很实际的下游接法：

1. `coach_agent.py`
   - 把学生长期画像作为辅助策略
   - 但不覆盖当前题当前轮的真实诊断

2. `review_scheduler.py`
   - 把学生长期常错的知识点 / 题目轻度前移
   - 但仍然以原本的复习到期、遗忘、掌握度逻辑为主

---

## 5. 个性化逻辑是怎么做的

### 5.1 教学倾向

系统会根据错因分布映射到几种教学 bias：

- `concept_explain_bias`
- `strategy_scaffold_bias`
- `step_by_step_bias`
- `condition_reading_bias`
- `self_check_bias`
- `direct_explain_bias`

例如：

- `concept_gap`
  - 提高概念讲解和直接解释权重

- `missing_strategy`
  - 提高思路脚手架和步骤拆解权重

- `careless`
  - 提高检查清单和自检权重

### 5.2 练习倾向

系统也会映射到练习 bias：

- `leaf_first_bias`
- `question_first_bias`
- `concept_card_bias`
- `method_card_bias`
- `representative_question_bias`
- `retry_recent_wrong_bias`

例如：

- `concept_gap`
  - 更偏 `leaf_first`
  - 先看知识点卡

- `missing_strategy`
  - 更偏方法卡 + 代表题

- `calculation`
  - 更偏 `question_first`
  - 让学生继续练题并检查过程

---

## 6. 为什么这版先不直接做 Cognee

因为你现在最缺的不是“更高级的记忆基础设施”，而是：

- 先确定记什么
- 先确定这些记忆怎么影响讲题和复习

如果底层 schema 还没定，直接接 Cognee 只是把混乱搬进另一个系统。

所以现在更合理的路线是：

1. 先建 `student_memory_profile`
2. 先让它能吃诊断和复习数据
3. 先让它能输出个性化建议
4. 再把 `memory_graph` 或 `agent_memory_text` 接到向量记忆系统

---

## 7. 当前这版的价值

这版已经能支持：

- AI 讲题时根据学生长期错因调整讲法
- 复习系统根据学生偏好调整 `leaf_first / question_first / mixed`
- 对反复卡住的知识点触发“重新讲概念”而不是继续盲刷题
- 给后续 Cognee / 图谱 / 向量库留下稳定接口

它还不能替代：

- 更成熟的长期行为建模
- 更复杂的因果推断
- 真正的多轮学生习惯学习器

但作为第四阶段的 MVP，已经够用了。

---

## 8. 下一步最值得做什么

如果继续推进，这层后面最值得做的不是重写，而是接入：

1. `diagnosis_orchestrator`
   - 每次诊断完自动写入 `diagnosis_event`

2. `review_state_manager`
   - 每次复习动作后自动写入 `review_event`

3. `coach_agent`
   - 讲题前读取 `agent_memory_text`

4. `review_scheduler`
   - 让 `practice_preferences` 参与混排策略

也就是：

> 先把学生记忆层建成“稳定中间层”，再往上下游接。

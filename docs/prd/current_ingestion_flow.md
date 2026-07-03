# TeachAgent 当前主线入库说明

这份文档只回答一个问题：

- 现在 TeachAgent 的主线数据，是怎么一步步入库，并最终长成学生长期画像的

这里不讨论以后怎么接更智能的模型记忆，也不讨论 `question_type`。
只讲当前已经落地、已经能跑通的这一版。

---

## 1. 先说结论

当前这套“入库”分两层：

1. 事件入库
2. 画像生成

具体来说：

- 各模块先产出自己的结构化结果
- 再把这些结果统一转成事件
- 事件写入一个本地 `JSONL` 事件库
- 之后再从这个事件库重建 `student_memory_profile`

所以它不是：

- 每个 agent 各写各的零散 JSON

也不是：

- 直接把所有历史都塞进 prompt 里给模型现读

而是：

- 先把原始学习行为沉淀成事件
- 再从事件长成摘要画像

---

## 2. 当前入库的核心文件

主线一共就三层。

### 2.1 事件构造层

- [student_memory_events.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_events.py)

这个文件的作用是：

- 把不同模块的输出，统一整理成标准事件格式

它现在支持 5 类事件：

- `binding`
- `diagnosis`
- `coach`
- `review`
- `student_choice`

对应的入口函数是：

- `binding_result_to_memory_event(...)`
- `diagnosis_result_to_memory_event(...)`
- `coach_response_to_memory_event(...)`
- `review_state_update_to_memory_event(...)`
- `student_choice_to_memory_event(...)`

这一步的本质是：

- 先把“模块自己的输出格式”变成“统一事件格式”

### 2.2 事件存储层

- [student_memory_store.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_store.py)

这个文件的作用是：

- 把事件追加写入本地事件库
- 按条件读取事件
- 从事件库重建画像

当前默认事件库路径是：

- `data/student_memory/student_memory_events.jsonl`

最关键的写入口是：

- `append_event(...)`  
  位置：[student_memory_store.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_store.py:63)

最关键的读入口是：

- `load_events(...)`

最关键的重建入口是：

- `build_profile_from_store(...)`  
  位置：[student_memory_store.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_store.py:139)

### 2.3 画像聚合层

- [student_memory_manager.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_manager.py)

这个文件的作用是：

- 按时间顺序回放事件
- 把事件累计成 `question_memories`
- 把事件累计成 `node_memories`
- 进一步汇总成 `personalization_summary`

最关键的入口是：

- `build_profile(...)`
- `apply_memory_event(...)`

现在已经是“统一按时间排序回放”，不是旧版那种按事件类别硬顺序回放。

---

## 3. 当前到底是怎么入库的

这一段最重要。

现在主线的真实顺序是：

### 3.1 先有原始业务结果

原始结果可能来自这些模块：

- `wrong_question_binder.py`
- `diagnosis_agent.py`
- `coach_agent.py`
- `review_scheduler.py`
- `review_state_manager.py`
- 学生手动树选知识点

这些模块本身先产出自己的业务结果。

例如：

- 题目绑定到了哪个叶子
- 诊断错因是什么
- coach 第一轮用了什么引导策略
- 复习后学生答对还是答错
- 学生手动选了哪些知识点

### 3.2 把业务结果转成标准事件

这一步由 [student_memory_events.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_events.py) 负责。

例子：

- 错题绑定结果  
  转成 `binding` 事件

- 诊断结果  
  转成 `diagnosis` 事件

- coach 输出  
  转成 `coach` 事件

- 一次复习结果 / 状态更新  
  转成 `review` 事件

- 学生沿知识树手动确认知识点  
  转成 `student_choice` 事件

也就是说，这一层做的是“统一接口”。

### 3.3 调用 `append_event(...)` 写入 JSONL

事件构造完以后，不是直接丢掉，而是显式写入事件库。

当前写法是：

```python
event = diagnosis_result_to_memory_event(...)
append_event(event, path=events_path)
```

这一点很关键：

- 现在不是每个 agent 自动偷偷入库
- 而是你在 orchestrator / notebook / pipeline 里显式调用 `append_event(...)`

所以当前系统的真实状态是：

- 入库机制已经有了
- 但是否入库，取决于你有没有显式接上这一层

这也是为什么现在 notebook 跑得通，但并不代表所有在线链路都已经自动落库。

### 3.4 从事件库重建学生画像

当事件写进去以后，可以调用：

- `build_profile_from_store(student_id=..., path=...)`

这个函数会：

1. 先读取该学生的全部事件
2. 按 `occurred_at` 排序
3. 一条条回放
4. 生成最终 `student_memory_profile`

位置：

- [student_memory_store.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_store.py:139)
- [student_memory_manager.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_manager.py:929)

---

## 4. 这五类事件分别怎么理解

### 4.1 `binding`

表示：

- 这道题绑定到了哪些知识点

常见字段：

- `question_id`
- `primary_node_id`
- `secondary_node_ids`
- `candidate_node_ids`
- `binding_source`

它解决的是：

- 题和叶子的关系先落下来

### 4.2 `diagnosis`

表示：

- 这道题这次被诊断成什么错因

常见字段：

- `question_id`
- `error_type`
- `reason`
- `evidence`
- `primary_node_id`
- `secondary_node_ids`

它解决的是：

- 这次错，不只是“错了”，而是错在什么类型

### 4.3 `coach`

表示：

- 针对这次错因，系统用了什么引导策略，学生反馈如何

常见字段：

- `coach_mode`
- `coach_trap`
- `coach_prompt`
- `reply_quality`
- `understands`
- `completed`

它解决的是：

- 不只是记录“错”，还记录“怎么教比较有效”

### 4.4 `review`

表示：

- 这道题或这个知识点在复习时发生了什么

常见字段：

- `action`
- `target_type`
- `target_id`
- `result`
- `updated_payload`

它解决的是：

- 学生复习以后到底变好了还是没变好

### 4.5 `student_choice`

表示：

- 学生自己沿知识树做了选择或补充

常见字段：

- `selected_node_ids`
- `target_type`
- `target_id`
- `note`

它解决的是：

- 系统推荐之外，学生自己的判断也能入库

---

## 5. 入库后，画像是怎么长出来的

这个过程由 [student_memory_manager.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_manager.py) 完成。

它不是简单拼接，而是做了三层聚合。

### 5.1 题目级记忆

生成：

- `question_memories`

每道题会累计：

- 绑定过哪些知识点
- 被诊断过几次
- 复习过几次
- 错过几次 / 对过几次 / partial 几次
- 最近一次结果是什么
- 最近一次看到它是什么时候

### 5.2 知识点级记忆

生成：

- `node_memories`

每个叶子会累计：

- 关联过哪些题
- 在这些题上出现过多少次错误
- 复习时错过多少次
- 连续错了多少次
- 当前主导错因是什么
- 推荐干预方式是什么

例如：

- `reteach_concept`
- `show_strategy_first`
- `drill_with_checklist`

### 5.3 学生级摘要

最终再生成：

- `personalization_summary`
- `teaching_preferences`
- `practice_preferences`
- `agent_memory_text`

这一层给后续模块用。

也就是说，运行时真正读的不是原始 `JSONL`，而是这个压缩后的摘要。

---

## 6. 当前“入库”是不是已经全自动

不是。

当前更准确的说法是：

- 事件标准已经统一
- 事件库已经能写
- 画像已经能从事件库重建
- 但各条业务链路是否自动入库，还要看你有没有显式接 `append_event(...)`

所以现在是“半自动、主干已通”。

更具体一点：

### 已经具备

- 标准事件格式
- 本地 JSONL 事件库
- 画像重建能力
- notebook 演示链路

### 还没完全做成

- 所有 agent 在真实运行时自动落库
- 一个统一 orchestrator 把所有阶段全自动串起来
- 持久化数据库版本（现在先是 JSONL）

---

## 7. 当前最标准的一条主线

如果你现在问“哪条是最标准的主线”，答案是：

1. 题目先绑定叶子
2. 生成 `binding` 事件并写库
3. 诊断错因
4. 生成 `diagnosis` 事件并写库
5. coach 引导
6. 生成 `coach` 事件并写库
7. 学生后续复习
8. 生成 `review` 事件并写库
9. 定期从事件库重建 `student_memory_profile`

如果学生手动确认知识点，则在第 1 步和第 2 步之间或之后，补一条：

10. 生成 `student_choice` 事件并写库

---

## 8. 现在最适合你怎么用

如果按你当前项目阶段，我建议是：

### 第一阶段

先把这些事件稳定写下来：

- `binding`
- `diagnosis`
- `coach`
- `review`

这是最核心的四类。

### 第二阶段

在学生手动选知识点的 UI 出来后，再稳定接：

- `student_choice`

### 第三阶段

等事件量起来后，再考虑：

- SQLite / Postgres 版本
- 向量检索版本
- Cognee / 图谱版本

现在没必要跳过事件层，直接搞重图谱。

---

## 9. 你现在可以把“入库”理解成什么

一句话版：

- 当前入库，就是把学习过程中的关键行为统一写成事件，存进一个 `JSONL` 事件库，再由这个事件库重建长期画像。

最简主干可以记成：

- 业务结果 -> 标准事件 -> `append_event(...)` -> `student_memory_events.jsonl` -> `build_profile_from_store(...)` -> `student_memory_profile`

---

## 10. 相关文件

- [student_memory_events.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_events.py)
- [student_memory_store.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_store.py)
- [student_memory_manager.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_manager.py)
- [student_memory_event_schema.json](/Users/xumuchi/Desktop/TeachAgent/docs/rag_schema/student_memory_event_schema.json)
- [student_memory_profile_schema.json](/Users/xumuchi/Desktop/TeachAgent/docs/rag_schema/student_memory_profile_schema.json)
- [student_memory_store_profile_demo.ipynb](/Users/xumuchi/Desktop/TeachAgent/notebooks/04_memory/student_memory_store_profile_demo.ipynb)

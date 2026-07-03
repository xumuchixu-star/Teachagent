# TeachAgent `student_memory_profile -> rules` 规则层说明

这份文档只解释一件事：

- 当 `student_memory_profile` 生成以后，系统怎么把它变成下游真正可用的规则

---

## 1. 为什么要单独加这一层

如果没有这层，代码会变成：

- `coach_agent.py` 自己直接读 profile
- `review_scheduler.py` 自己直接读 profile
- 以后别的模块也各自直接读 profile

这样的问题是：

- 规则会散
- 同一个字段会被不同模块各写一套解释
- 后面你想升级长期画像时，要改很多地方

所以现在单独抽了一层：

- [student_memory_rules.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_rules.py)

它的职责不是生成 profile，而是：

- 把 profile 翻译成下游可以消费的规则

---

## 2. 这层在主线中的位置

当前主线现在变成：

1. 学习过程产生事件
2. 事件写入 `student_memory_events.jsonl`
3. 从事件库重建 `student_memory_profile`
4. 从 `student_memory_profile` 提取下游规则
5. `coach_agent` / `review_scheduler` 消费这些规则

也就是：

- 事件层解决“记什么”
- profile 层解决“总结成什么”
- rules 层解决“怎么用”

---

## 3. 当前这层已经负责什么

### 3.1 给 `coach_agent` 提供规则

现在这层会把 profile 提炼成：

- `context_text`
- `strategy_note`

用途分别是：

- `context_text`
  - 给 coach 一个简短长期背景
  - 例如学生长期主错因、长期教学偏好、当前最常卡叶子

- `strategy_note`
  - 直接改写本轮教法倾向
  - 例如优先讲概念，或优先点中间目标

入口函数：

- `build_coach_memory_rule(...)`

### 3.2 给 `review_scheduler` 提供规则

现在这层会把 profile 提炼成：

- 叶子优先级偏置
- 题目优先级偏置
- personalization summary 读取入口

入口函数：

- `build_memory_node_lookup(...)`
- `build_memory_question_lookup(...)`
- `compute_node_memory_priority_boost(...)`
- `compute_question_memory_priority_boost(...)`
- `get_personalization_summary(...)`

这些规则现在做的是“轻偏置”，不是硬覆盖。

也就是说：

- 复习主排序仍然由遗忘 / 到期 / 掌握度决定
- profile 只是轻度前移或后移

---

## 4. 当前模块关系

### 上游

- [student_memory_manager.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_manager.py)
  - 负责生成 `student_memory_profile`

### 中间规则层

- [student_memory_rules.py](/Users/xumuchi/Desktop/TeachAgent/student_memory_rules.py)
  - 负责把 `profile` 翻译成可执行规则

### 下游消费层

- [coach_agent.py](/Users/xumuchi/Desktop/TeachAgent/coach_agent.py)
- [review_scheduler.py](/Users/xumuchi/Desktop/TeachAgent/review_scheduler.py)

---

## 5. 这层的设计原则

当前我按三个原则写的：

### 5.1 不改变现有行为方向

这次抽层主要是收口，不是重写逻辑。

所以现在：

- coach 还是读长期教学偏好
- review 还是读长期复习偏置

只是这些解释规则不再散落在两个文件里。

### 5.2 先做轻规则，不做重模型

当前这层是规则层，不是模型层。

也就是说：

- 先把“长期画像如何影响下游”写清楚
- 以后如果你要把这层再升级成模型解释层，也有明确插口

### 5.3 后面只改这一层

你之后如果要增强长期画像使用方式，优先改：

- `student_memory_rules.py`

而不是直接到：

- `coach_agent.py`
- `review_scheduler.py`

到处打补丁。

---

## 6. 你现在可以怎么理解这层

一句话：

- `student_memory_profile` 是长期摘要，`student_memory_rules.py` 是长期摘要到运行时决策之间的翻译器。

如果再压缩一点：

- profile 负责“学生是什么样”
- rules 负责“系统因此怎么做”

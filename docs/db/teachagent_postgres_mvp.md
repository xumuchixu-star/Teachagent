# TeachAgent PostgreSQL MVP 说明

这份文档只做两件事：

1. 说明当前 `TeachAgent` 的本地 JSON / JSONL 数据如何映射到 PostgreSQL
2. 说明新的数据库访问层怎么用

相关文件：

- [teachagent_postgres_mvp.sql](/Users/xumuchi/Desktop/TeachAgent/docs/db/teachagent_postgres_mvp.sql)
- [teachagent_postgres_store.py](/Users/xumuchi/Desktop/TeachAgent/teachagent_postgres_store.py)

## 1. 设计目标

当前 `TeachAgent` 的学生数据虽然主要是文本，但本质上是关系型数据：

- 学生
- 知识点
- 题目 / 错题
- 题目和知识点的挂载关系
- 复习状态
- 长期画像
- 事件流
- diagnosis / coach 会话

所以这次不再按“每个学生一整个大 JSON”存，而是：

- 核心关系进 SQL 表
- 灵活字段进 `JSONB`
- 运行时仍然可以读回成现在的 Python dict

这意味着：

- `review_scheduler.py` 以后仍然可以吃 `review_state dict`
- `student_memory_rules.py` 以后仍然可以吃 `student_memory_profile dict`
- 只是底层来源从本地文件切成数据库

## 2. 现有本地文件到数据库的映射

### 2.1 `review_state.session.json`

当前来源：

- `app/data/review_state.session.json`
- `scratch/student_annotation_merged/student_annotation_merged_review_state.json`

数据库对应：

- `students`
- `student_review_states`
- `student_node_states`
- `student_questions`
- `student_question_states`
- `student_question_node_links`

映射原则：

- `review_state.record_id` -> `student_review_states.record_uid`
- `review_state.student_id` -> `students.student_uid`
- `knowledge_point_states[*]` -> `student_node_states`
- `example_question_states[*]` -> `student_question_states`
- `question_payload` 主体 -> `student_questions`
- `linked_node_ids / primary_node_ids / secondary_node_ids` -> `student_question_node_links`

### 2.2 `student_memory_profile`

当前来源：

- `scratch/teachagent_system_overview/student_memory_profile_demo.json`
- `app/data/student_memory_profile.session.json`

数据库对应：

- `student_memory_profiles`
- `student_node_memories`
- `student_question_memories`

映射原则：

- 整份 profile 原样保存在 `student_memory_profiles.raw_profile`
- 常用字段额外拆列，方便检索和统计
- `node_memories[*]` 单独存 `student_node_memories`
- `question_memories[*]` 单独存 `student_question_memories`

这样做的原因是：

- 运行时可以直接拿 `raw_profile`
- 数据分析时又可以直接查结构化列

### 2.3 `student_memory_events.jsonl`

当前来源：

- `data/student_memory/student_memory_events.jsonl`

数据库对应：

- `student_memory_events`

映射原则：

- 每条事件保留原始 payload
- 同时拆出 `event_type / question_uid / primary_node_id / error_type / occurred_at`
- 后续 `build_profile_from_store(...)` 可以改成从数据库读事件

### 2.4 `tree_custom_nodes.session.json`

当前来源：

- `app/data/tree_custom_nodes.session.json`

数据库对应：

- `knowledge_nodes`

映射原则：

- 系统知识点：`source_scope = 'system'`
- 学生自建知识点：`source_scope = 'student_custom'`
- 学生自建点通过 `owner_student_id` 归属到具体学生

### 2.5 `tree_notes.session.json`

当前来源：

- `app/data/tree_notes.session.json`

当前实际用途：

- 主要是题目笔记，不是知识点笔记

数据库对应：

- `student_questions.note`

也就是说现在先不单独建 `node_notes` 表。

### 2.6 diagnosis / coach 会话

当前来源：

- app 进程内状态

数据库对应：

- `diagnosis_sessions`
- `diagnosis_messages`
- `coach_sessions`
- `coach_messages`

这部分当前还没接到 `server.py` 主流程里，但访问层已经把保存 / 读取接口留出来了。

## 3. 主要表怎么理解

### 3.1 学生主表

- `students`

一条学生一行，`student_uid` 对应你现在所有 JSON 里的 `student_id`。

### 3.2 知识点

- `knowledge_nodes`

统一承接：

- 系统知识树
- 学生新增知识点

这样后面“错题本按知识点整理”就不需要双套结构。

### 3.3 题目 / 错题

- `student_questions`
- `student_question_node_links`

这里不是只存“错题文本”，而是把题目本体和它挂到哪些知识点分开。

原因很简单：

- 一道题可以挂多个知识点
- 必须支持主知识点和次知识点

### 3.4 复习状态

- `student_review_states`
- `student_node_states`
- `student_question_states`

这部分直接服务 `review_scheduler.py`。

### 3.5 长期画像

- `student_memory_profiles`
- `student_node_memories`
- `student_question_memories`

这部分直接服务：

- `student_memory_rules.py`
- `review_scheduler.py`
- `coach_agent.py`

### 3.6 事件层

- `student_memory_events`

这部分是长期画像的上游原料。

## 4. 新的数据库访问层

文件：

- [teachagent_postgres_store.py](/Users/xumuchi/Desktop/TeachAgent/teachagent_postgres_store.py)

类：

- `PostgresStoreConfig`
- `TeachAgentPostgresStore`

### 4.1 环境变量

当前访问层默认读：

- `TEACHAGENT_DATABASE_URL`
- 或 `DATABASE_URL`

可选：

- `TEACHAGENT_DB_APPLICATION_NAME`
- `TEACHAGENT_DB_CONNECT_TIMEOUT`

### 4.2 当前已经实现的接口

学生：

- `get_student(...)`
- `get_or_create_student(...)`

知识点：

- `upsert_knowledge_nodes(...)`
- `save_custom_node(...)`
- `load_custom_nodes(...)`

题目笔记：

- `save_question_note(...)`
- `load_question_notes(...)`

复习状态：

- `save_review_state(...)`
- `load_review_state(...)`

长期画像：

- `save_memory_profile(...)`
- `load_memory_profile(...)`

事件流：

- `append_memory_event(...)`
- `load_memory_events(...)`

diagnosis：

- `save_diagnosis_flow(...)`
- `load_diagnosis_flow(...)`

coach：

- `save_coach_chat(...)`
- `load_coach_chat(...)`

健康检查：

- `ping()`

## 5. 使用方式

### 5.1 初始化

推荐直接用 CLI：

```bash
python3 teachagent_postgres_cli.py bootstrap --all-students
```

它会一次做三件事：

- 建表
- 把系统知识树写进 `knowledge_nodes`
- 把 `app/data/students/` 下面的本地学生数据导入 PostgreSQL

先建表：

```bash
psql "$TEACHAGENT_DATABASE_URL" -f docs/db/teachagent_postgres_mvp.sql
```

再在 Python 里创建 store：

```python
from teachagent_postgres_store import TeachAgentPostgresStore

store = TeachAgentPostgresStore()
print(store.ping())
```

如果你只想检查数据库是否连通，可以直接执行：

```bash
python3 teachagent_postgres_cli.py ping
```

### 5.2 存一份 review_state

```python
import json
from pathlib import Path

from teachagent_postgres_store import TeachAgentPostgresStore

store = TeachAgentPostgresStore()
review_state = json.loads(
    Path("scratch/student_annotation_merged/student_annotation_merged_review_state.json")
    .read_text(encoding="utf-8")
)
store.save_review_state(review_state)
```

### 5.3 读回一份 review_state

```python
review_state = store.load_review_state("demo_student")
```

读回后的结构仍然是现在 `review_scheduler.py` 能吃的 dict 形状。

### 5.4 存一份 student_memory_profile

```python
import json
from pathlib import Path

from teachagent_postgres_store import TeachAgentPostgresStore

store = TeachAgentPostgresStore()
profile = json.loads(
    Path("scratch/teachagent_system_overview/student_memory_profile_demo.json")
    .read_text(encoding="utf-8")
)
store.save_memory_profile(profile)
```

### 5.5 追加一条 memory event

```python
store.append_memory_event(
    {
        "event_id": "evt_demo_001",
        "event_type": "review",
        "student_id": "demo_student",
        "occurred_at": "2026-07-02T12:00:00+08:00",
        "question_id": "q001",
        "primary_node_id": "math.xxx",
        "result": "wrong",
    }
)
```

### 5.6 导入某个学生或全部学生

只导一个学生：

```bash
python3 teachagent_postgres_cli.py import-local --student-id stu_001
```

导入全部学生：

```bash
python3 teachagent_postgres_cli.py import-local --all-students
```

## 6. 接入 `server.py` 的建议顺序

不要一次性全接。建议按下面顺序做：

1. 先接 `students + review_state`
2. 再接 `memory_profile`
3. 再接 `memory_events`
4. 再接 `question note / custom node`
5. 最后接 `diagnosis / coach`

原因：

- `review_state` 和 `memory_profile` 是当前主消费接口
- 先把这两块接稳，`review_scheduler` 和长期画像就能跑
- diagnosis / coach 会话持久化不是第一阻塞项

## 7. 当前没有做的事

这次还没有做：

- 把 `server.py` 直接改成数据库读写
- 做数据库迁移脚本框架
- 做连接池
- 做行级权限
- 做班级 / 老师 / 多租户模型

这次的目标只是先把：

- 表结构
- 数据映射
- 可用访问层

这三件事定下来。

## 8. 下一步最合理的工作

下一步建议直接改这几个点：

1. `AppState._load_current_review_state()` 改成优先从数据库读
2. `persist_session_state()` 改成写数据库
3. `persist_memory_profile()` 改成写数据库
4. `append_event(...) / build_profile_from_store(...)` 改成数据库版

做完这一步以后，`TeachAgent` 就不再依赖本地 session JSON 作为主存储了。

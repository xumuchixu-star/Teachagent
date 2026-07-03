# TeachAgent Harness / Eval 方案

快速版说明见：

- `docs/prd/harness_one_page_summary.md`

这份文档定义 TeachAgent 的第四部分：

- `harness`
- `eval`
- `regression`

目标不是做传统意义上的完整测试框架，而是做一个**小而硬的回放评估层**。

它要解决的问题很实际：

- 现在第三部分已经能跑，但大约只有 `6/10`
- 后面你还会继续改：
  - `leaf_router.py`
  - `wrong_question_binder.py`
  - 题库
  - 叶子卡
  - 复习调度
- 如果没有 harness，每次改完都很难判断：
  - 到底有没有更准
  - 是真的提升了
  - 还是只是“换了一种错法”

所以第四部分的目标不是“证明系统完美”，而是：

**把当前行为冻结成可回放、可比较、可回归的基线。**

---

## 1. 目标

第四部分主要做三件事：

1. 固定一批样例输入
2. 跑当前核心链路
3. 输出结构化评估报告

用一句话概括：

> 每次改 binder、scheduler、review 流程之后，都能快速回答“这次改动是更好了，还是更坏了”。

---

## 2. 当前优先级

第四部分不追求把所有子系统都测一遍。

当前最值得先做的是：

1. `wrong_binder_harness`
2. `review_harness`
3. `run_all_harness.py`

暂时不把 `leaf_pipeline_harness` 放进第一版核心范围。

原因：

- `leaf_router` / `leaf_card_agent` 更受模型波动影响
- 你当前主线里最容易被后续改坏、也最关键的是：
  - `wrong_question_binder`
  - `review_scheduler`
  - `review_state_manager`
  - `review_bundle_builder`

所以第一版 harness 应该先保核心，不要摊太大。

---

## 3. 设计原则

### 3.1 不是单元测试优先，而是行为回放优先

第四部分更像：

- 回归评估器
- 行为回放器
- 基线比较器

而不是：

- 一堆非常碎的 pytest 单元测试

因为你现在最关心的不是“某个辅助函数有没有返回 0.25”，而是：

- binder 这次是不是还把题绑到合理知识点
- review 点完按钮后是不是还符合直觉

### 3.2 不要求唯一正确答案

尤其是 `wrong_binder`，现在阶段不适合写死成：

- “必须唯一命中这个 node_id”

更合理的是写成：

- 允许主知识点集合
- 必须出现在 top-3 / top-5
- coarse subtree 必须正确

这样能反映你当前系统的真实状态。

### 3.3 输出报告比 pass/fail 更重要

第四部分不能只给一个：

- `passed`
- `failed`

而应该给：

- case id
- 输入摘要
- 关键输出摘要
- 失败原因
- 是否比基线更好
- 失败发生在哪一层
- 下一步应该先查哪一块
- 每个 case / suite 的评分

### 3.4 每个板块都要有明确的报错流

Harness 不是只告诉你“挂了”，而是要告诉你：

- 挂在粗路由、召回还是重排
- 挂在状态更新、重排还是 bundle 组装
- 下一步最应该查哪个字段

这样你后面改系统时，失败报告本身就是一个排障入口。

### 3.5 每个板块都要有明确的评分标准

第一版评分不是为了学术精确，而是为了工程判断：

- 这次有没有退步
- 这次是不是只修了一处、却把别处弄坏了
- 两个版本之间能不能粗粒度比较

因此每个 case 都应该有：

- `score.earned_points`
- `score.total_points`
- `score.score_ratio`
- `score.score_percent`
- `score.rubric_items`

每个 suite 再汇总成 suite 级分数。

---

## 4. 第一版范围

### 4.1 wrong_binder_harness

要覆盖：

- `wrong_question_binder.py`

输入：

- 固定题目样例
- 每题附一份人工认可的预期

检查重点：

- `primary_node_id` 是否在允许集合里
- `top_k_node_ids` 是否包含预期知识点
- `must_hit_within_top_k`
- `coarse_subtrees` 是否大方向正确
- embedding 打开 / 关闭时结果是否在合理范围内

### 4.2 review_harness

要覆盖：

- `annotation_to_review_state.py`
- `review_scheduler.py`
- `review_state_manager.py`
- `review_bundle_builder.py`

输入：

- 固定 `review_state`
- 固定一串动作

检查重点：

- `leaf_first` 第一屏是否能正常生成 bundle
- `question_first` 第一屏是否能正常生成 bundle
- `node_needs_more_practice` 后，该知识点是否继续靠前
- `node_mastered_well` 后，该知识点是否后移
- `question wrong` 后，这道题是否继续靠前
- `question correct` 后，这道题是否下降或退出高优先级

### 4.3 run_all_harness

作用：

- 一次性跑所有 harness
- 汇总成一个统一报告

输出：

- `report.json`
- `report.md`

---

## 5. 目录结构建议

建议新增：

```text
TeachAgent/
  harness/
    fixtures/
      wrong_binder/
      review_flow/
    reports/
    run_wrong_binder_harness.py
    run_review_harness.py
    run_all_harness.py
```

说明：

- `fixtures/`
  - 放固定输入和预期
- `reports/`
  - 放运行结果
- `run_*`
  - 每类 harness 一个 runner

第一版先不要复杂拆模块，能跑通即可。

---

## 6. wrong_binder fixtures 设计

建议每个 case 一个 JSON 文件。

示例：

```json
{
  "case_id": "binder_case_001",
  "description": "递推转等比数列",
  "question_payload": {
    "stem": "已知数列 a_n 满足 a_{n+1}=3a_n+1，且 a_1=1/2，求证：数列 {a_n+1/2} 为等比数列。",
    "question_type": "证明题",
    "correct_answer": "数列 {a_n+1/2} 是以 1 为首项、3 为公比的等比数列。",
    "solution_text": "由 a_{n+1}=3a_n+1，得 a_{n+1}+1/2=3(a_n+1/2)..."
  },
  "expectation": {
    "allowed_primary_node_ids": [
      "math.数列与不等式.数列.递推数列转化方法.标准型递推公式转化",
      "math.数列与不等式.数列.基础概念.数列递推公式解读"
    ],
    "must_hit_node_ids": [
      "math.数列与不等式.数列.递推数列转化方法.标准型递推公式转化"
    ],
    "must_hit_within_top_k": 5,
    "allowed_coarse_subtrees": [
      "math.数列与不等式.数列"
    ]
  }
}
```

### 6.1 binder 的判断方式

第一版 `wrong_binder` 采用 100 分制等价的加权评分：

- 主知识点落在允许集合内：`40%`
- 目标叶子在要求的 top-k 内被召回：`40%`
- 第一 coarse subtree 方向正确：`20%`

对应失败流：

1. 先看 `binder.coarse_routing`
2. 再看 `binder.top_k_recall`
3. 最后看 `binder.primary_selection`

原因很简单：

- 大方向子树错了，后面精排通常救不回来
- 子树对了但目标叶子没进候选池，说明召回不够
- 候选池有了但主知识点还是不对，才是精排问题

失败报告里应包含：

- `failure_code`
- `layer`
- `message`
- `inspect_fields`
- `suggested_next_step`
- `actual`
- `expected`

### 6.2 review 的判断方式

第一版 `review_flow` 采用“每条行为断言 1 分”的方式：

- `first_node_should_remain_within_top_n`
- `first_node_should_drop_out_of_top_n`
- `first_question_should_remain_within_top_n`
- `first_question_should_drop_out_of_top_n`
- `first_bundle_question_count_min`

一个 case 配了几条断言，就按几条断言计总分。

对应失败流：

1. 先看 `review.state_update`
2. 再看 `review.question_requeue`
3. 再看 `review.bundle_ranking`
4. 最后看 `review.bundle_composition`

原因：

- 动作没写回状态，后面所有排序都会假
- 状态写对了但没有重新入队，说明回炉/后移机制有问题
- 入队对了但排序不对，说明优先级混合规则有问题
- 排序对了但 bundle 展示不完整，才是组装层问题

建议第一版就支持这几种断言：

- `allowed_primary_node_ids`
- `must_hit_node_ids`
- `must_hit_within_top_k`
- `allowed_coarse_subtrees`

这样足够覆盖你当前阶段。

### 6.2 binder 输出报告字段

建议至少包含：

- `case_id`
- `passed`
- `primary_node_id`
- `top_k_node_ids`
- `coarse_subtrees`
- `matched_expectations`
- `failed_expectations`

---

## 7. review_flow fixtures 设计

这一类不只测静态输出，而是测一串动作。

示例：

```json
{
  "case_id": "review_case_001",
  "description": "知识点模式下继续练题",
  "review_state_path": "scratch/student_annotation_merged/student_annotation_merged_review_state.json",
  "mode": "leaf_first",
  "steps": [
    {
      "action": "build_bundle"
    },
    {
      "action": "review_action",
      "review_action": "node_needs_more_practice",
      "target_source": "first_bundle_node"
    },
    {
      "action": "build_bundle"
    }
  ],
  "expectation": {
    "first_node_should_remain_within_top_n": 3
  }
}
```

另一种：

```json
{
  "case_id": "review_case_002",
  "description": "题目模式下做错后立即回炉",
  "review_state_path": "scratch/student_annotation_merged/student_annotation_merged_review_state.json",
  "mode": "question_first",
  "steps": [
    {
      "action": "build_bundle"
    },
    {
      "action": "review_action",
      "review_action": "review_result",
      "result": "wrong",
      "target_source": "first_bundle_question"
    },
    {
      "action": "build_bundle"
    }
  ],
  "expectation": {
    "first_question_should_remain_within_top_n": 3
  }
}
```

### 7.1 review 的判断方式

建议第一版只测这些非常关键的行为：

- `first_node_should_remain_within_top_n`
- `first_node_should_drop_out_of_top_n`
- `first_question_should_remain_within_top_n`
- `first_question_should_drop_out_of_top_n`
- `bundle_question_count_min`

这样最小但够用。

### 7.2 review 输出报告字段

建议至少包含：

- `case_id`
- `passed`
- `before_top_nodes`
- `after_top_nodes`
- `before_top_questions`
- `after_top_questions`
- `failed_expectations`

---

## 8. runner 设计

### 8.1 run_wrong_binder_harness.py

职责：

1. 读取 `fixtures/wrong_binder/*.json`
2. 调用 `wrong_question_binder.py`
3. 跑 expectation
4. 产出单项报告

### 8.2 run_review_harness.py

职责：

1. 读取 `fixtures/review_flow/*.json`
2. 按顺序执行：
   - `build_review_bundles`
   - `apply_review_action`
   - 再次 `build_review_bundles`
3. 检查 expectation
4. 产出单项报告

### 8.3 run_all_harness.py

职责：

1. 调 `run_wrong_binder_harness.py`
2. 调 `run_review_harness.py`
3. 汇总结果
4. 写入统一 `reports/latest_report.json`

---

## 9. 输出格式建议

第一版统一输出：

- `report.json`
- `report.md`

总报告建议像这样：

```json
{
  "generated_at": "2026-06-22T12:00:00+08:00",
  "summary": {
    "suite_count": 2,
    "case_count": 12,
    "passed_case_count": 10,
    "failed_case_count": 2
  },
  "suites": [
    {
      "suite_name": "wrong_binder",
      "passed_case_count": 6,
      "failed_case_count": 1,
      "cases": []
    },
    {
      "suite_name": "review_flow",
      "passed_case_count": 4,
      "failed_case_count": 1,
      "cases": []
    }
  ]
}
```

后面如果需要，可以再加：

- `diff_vs_baseline.json`

---

## 10. 基线机制

第四部分真正值钱的地方，不只是“能跑”，而是能和历史版本比较。

所以建议第二步就加上：

- `baseline_report.json`
- `latest_report.json`

这样以后每次改：

- binder prompt
- embedding 权重
- scheduler 规则
- review 行为

都可以直接比较：

- top-k 命中率有没有升
- 回炉逻辑有没有被改坏

第一版可以先不自动做 diff，但结构上要预留。

---

## 11. 不做什么

第一版 harness 先不做：

- `leaf_card_agent` 的完整模型质量评估
- OCR 评估
- 教学对话 `coach_agent` 的复杂对话评估
- 自动统计“语言质量”
- 大规模 benchmark

这些都不是现在最需要的。

---

## 12. 实施顺序

建议按这个顺序做：

1. 建 `harness/fixtures/wrong_binder`
2. 写 `run_wrong_binder_harness.py`
3. 建 `harness/fixtures/review_flow`
4. 写 `run_review_harness.py`
5. 写 `run_all_harness.py`
6. 最后补 `reports/latest_report.json`

这样每一步都能独立落地，不会一开始就太重。

---

## 13. 成功标准

第四部分做到什么程度就算成功：

1. 能一键跑完 `wrong_binder + review`
2. 能稳定输出统一 JSON 报告
3. 你后面每次调 binder / review，都可以用它做回归

只要这三点成立，第四部分就已经有价值了。

---

## 14. 一句话结论

第四部分的 harness 不是为了“补测试面子工程”，而是为了给第三部分建立一个真正可迭代的基线。

它的核心作用是：

> 帮你把“感觉这次好像更准了”变成“我知道这次到底哪里更好了、哪里又坏了”。

# TeachAgent Harness 一页说明

这份文档是给现在这个项目阶段用的，不是讲测试理论，而是讲：

- `harness` 现在到底做了什么
- 为什么要分成两部分
- 平时应该怎么看报告
- 哪些分数值得紧张，哪些不用

---

## 1. Harness 现在的定位

当前 `harness` 不是为了证明系统已经很强，而是为了做两件事：

1. 防止后面改代码时把已有能力改坏
2. 用一小批固定题，持续观察系统有没有真实变好

一句话说：

> `harness` 是 TeachAgent 第四部分的回归层和评估层。

---

## 2. 现在有哪些部分

目前已经成型的只有两块：

1. `wrong_binder_harness`
2. `review_flow_harness`

外加一个总入口：

3. `run_all_harness.py`

目录结构：

```text
TeachAgent/
  harness/
    fixtures/
      wrong_binder/
      wrong_binder_eval_v1/
      review_flow/
    reports/
    common.py
    run_wrong_binder_harness.py
    run_review_harness.py
    run_all_harness.py
```

---

## 3. 第一部分：Wrong Binder Harness

对应文件：

- `harness/run_wrong_binder_harness.py`

它测的不是“系统会不会自动完美选中唯一叶子”，而是：

- 大方向子树是否合理
- `top-k` 候选里是否能出现正确叶子
- 第一名是否大致合理

### 3.1 为什么这样设计

因为当前 `wrong_binder` 在系统里的角色更接近：

- 推荐器
- 导航器
- 学生手动选择前的候选生成器

而不是：

- 最终裁判

所以这个 harness 不能只看 `top-1`。

### 3.2 当前评分口径

当前权重是：

- `primary = 0.15`
- `top-k = 0.65`
- `coarse = 0.20`

也就是说，当前阶段最看重的是：

> 正确叶子有没有进入 `top-k`

这是故意的，因为你现在允许：

- 学生自己选知识点
- 学生新建知识点
- 后续模型二次判断

### 3.3 它现在有两套题集

#### A. 回归集

路径：

- `harness/fixtures/wrong_binder/`

作用：

- 防止你后面改 `wrong_question_binder.py` 时，把已经能处理的题型改坏

特点：

- 题量小
- 题型是你已经确认过的代表题
- 重点是“稳定”

#### B. 新题评估集

路径：

- `harness/fixtures/wrong_binder_eval_v1/`

作用：

- 看系统面对新题时的真实表现

特点：

- 不和回归集混用
- 分数更真实
- 允许不满分

### 3.4 怎么看分数

如果回归集挂了：

- 说明你改代码时把已知能力弄坏了

如果新题评估集分数低：

- 不一定说明程序坏了
- 更可能说明当前推荐能力还不够强

所以这两个分数的意义不同：

- 回归集：看“有没有退步”
- 新题评估集：看“有没有进步”

---

## 4. 第二部分：Review Flow Harness

对应文件：

- `harness/run_review_harness.py`

它测的是复习系统的行为逻辑，不是知识点分类。

重点检查：

- 学生点“还要练题”后，知识点是否继续靠前
- 学生点“掌握很熟练”后，知识点是否后移
- 题目答错后，是否立即回炉
- 题目答对后，是否自然后移
- 暂时跳过后，是否从当前高优先级里移开
- 第一屏 bundle 的题量是否还够

### 4.1 它为什么重要

因为复习系统最怕的不是“算法不够优雅”，而是：

- 点完按钮没反应
- 该回炉的不回炉
- 该后移的不后移
- 第一屏内容不稳定

这个 harness 就是专门盯这些交互逻辑。

### 4.2 它怎么做

它不是随机跑，而是：

1. 读一份固定 `review_state`
2. 执行固定步骤
3. 比较前后排序结果
4. 输出是否符合预期

所以它更像“行为回放器”。

---

## 5. 第三部分：总入口

对应文件：

- `harness/run_all_harness.py`

作用：

1. 一次性跑 `wrong_binder` 回归集
2. 一次性跑 `review_flow`
3. 输出统一报告

当前不会默认跑 `wrong_binder_eval_v1`，因为那批题是阶段评估集，不属于“必须全绿”的主回归链路。

---

## 6. 报告怎么看

主要看两个文件：

- `harness/reports/latest_report.json`
- `harness/reports/latest_report.md`

其中：

- `json` 给程序和后续自动化用
- `md` 给人直接看

### 6.1 平时先看什么

平时先看：

- `latest_report.md`

它会告诉你：

- 哪几个 suite
- 每个 suite 当前多少分
- 哪些 case 通过
- 如果失败，先查哪一层

### 6.2 如果 wrong_binder 出问题

优先按这个顺序看：

1. `binder.coarse_routing`
2. `binder.top_k_recall`
3. `binder.primary_selection`

解释：

- 先看大方向子树对不对
- 再看正确叶子有没有进候选池
- 最后才看第一名是不是排对

### 6.3 如果 review_flow 出问题

优先按这个顺序看：

1. `review.state_update`
2. `review.question_requeue`
3. `review.bundle_ranking`
4. `review.bundle_composition`

解释：

- 先看动作有没有写回状态
- 再看有没有重新排队
- 再看排序
- 最后看展示组装

---

## 7. 平时怎么跑

### 7.1 跑主回归集

```bash
python3 /Users/xumuchi/Desktop/TeachAgent/harness/run_all_harness.py
```

适用场景：

- 你刚改了 binder
- 你刚改了 review 逻辑
- 想确认有没有把现有能力搞坏

### 7.2 单独跑 wrong_binder 新题评估集

```bash
python3 /Users/xumuchi/Desktop/TeachAgent/harness/run_wrong_binder_harness.py \
  --fixture-dir /Users/xumuchi/Desktop/TeachAgent/harness/fixtures/wrong_binder_eval_v1 \
  --out-json /Users/xumuchi/Desktop/TeachAgent/harness/reports/wrong_binder_eval_v1_report.json
```

适用场景：

- 想看 `wrong_binder` 在新题上的真实表现
- 想判断这次修改是不是让推荐器更强了

---

## 8. 当前该怎么理解这套 Harness

现在这套 `harness` 已经够用了，原因不是它覆盖了所有情况，而是：

- 主回归链路已经有了
- 新题评估链路已经有了
- 报告已经有了
- 评分口径已经和当前项目目标对齐了

所以后面重点不是重写 harness，而是：

1. 继续加更真实的题
2. 继续加学生真实使用后的 case
3. 用新题评估集观察 binder 是否真的进步

---

## 9. 最后一句话

当前 `harness` 的作用可以直接记成：

> `wrong_binder` 看推荐准不准，`review_flow` 看按钮点完顺不顺。


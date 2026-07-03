# TeachAgent Harness Report

## Overall
- 生成时间：2026-06-24T08:55:05.008285+00:00
- Suite 数：2
- Case 数：10
- 通过：10
- 失败：0
- 总分：11.0 / 11.0 (100.0%)

## Harness Parts

## wrong_binder
- 作用：检查错题绑定是否还能把题目稳定路由到合理知识点。
- 当前分数：4.0 / 4.0 (100.0%)
- 当前通过：4 / 4
- 主要检查点：
  - 主知识点是否落在允许集合内
  - 目标叶子是否在要求的 top-k 内被召回
  - 粗路由的第一子树是否正确
- 评分口径： primary=0.15 | top-k=0.65 | coarse=0.2
- 评分说明：当前阶段以 top-k 召回为主，primary 只作为次级指标。
- 报错排查顺序：binder.coarse_routing -> binder.top_k_recall -> binder.primary_selection
- 排查说明：先看大方向子树，再看候选召回，再看最终主知识点选择。

### Cases
### binder_case_circle_distance
- 说明：圆上张角存在性转化为圆心到直线距离范围
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)

### binder_case_derivative_monotonicity
- 说明：导数判断单调性的典型讲解题
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)

### binder_case_sequence_shift
- 说明：递推构造等比数列证明题
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)

### binder_case_vector_angle
- 说明：单位向量和为零，借数量积与夹角公式求夹角
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)


## review_flow
- 作用：检查复习系统在学生点击按钮后，题目与知识点的前后顺序是否仍符合直觉。
- 当前分数：7.0 / 7.0 (100.0%)
- 当前通过：6 / 6
- 主要检查点：
  - 知识点点击“还要练题”后是否继续靠前
  - 知识点点击“掌握很熟练”后是否后移
  - 题目答错后是否立即回炉
  - 题目答对后是否自然后移
  - 第一屏 bundle 的配套题数量是否足够
- 报错排查顺序：review.state_update -> review.question_requeue -> review.bundle_ranking -> review.bundle_composition
- 排查说明：先看动作有没有正确写入状态，再看题/知识点是否重新排队，最后看 bundle 组装结果。

### Cases
### review_case_leaf_mastered
- 说明：知识点模式下点击掌握很熟练后，该知识点应从第一位移开
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)

### review_case_leaf_practice
- 说明：知识点模式下点击还要练题后，该知识点应继续保持在顶部
- 结果：PASS
- 分数：2.0 / 2.0 (100.0%)

### review_case_leaf_skip_temporarily
- 说明：知识点模式下暂时跳过后，该知识点应从第一位移开
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)

### review_case_question_correct
- 说明：题目模式下做对后，该题应从第一位移开
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)

### review_case_question_skip_temporarily
- 说明：题目模式下暂时跳过后，该题应从第一位移开
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)

### review_case_question_wrong
- 说明：题目模式下做错后，该题应继续保持在顶部
- 结果：PASS
- 分数：1.0 / 1.0 (100.0%)

### math.统计与概率.概率.概率基本性质.互斥事件概念
- keywords: 互斥事件 | 不能同时发生 | 概率
- aliases: 互不相容事件
- definition: 如果事件 A 与事件 B 不能同时发生，则称 A 与 B 互斥。
- recognition_signals: 题目强调两个结果不能同时出现 | 需要判断两个事件是否有交集 | 后续常与加法公式一起出现
- boundary: 互斥强调不能同时发生，不等于相互独立。
- common_errors: 把互斥事件误当成独立事件 | 只看事件名称相似就判断互斥 | 不会结合一次试验的实际结果判断能否同时发生
- review_cue: 先问自己这两个事件能不能在一次试验里同时发生。
- example_refs: problem.probability.mutually_exclusive.01

### math.统计与概率.概率.概率基本性质.对立事件概念
- keywords: 对立事件 | 必有一个发生 | 概率
- aliases: 补事件
- definition: 若事件 A 与事件 B 互斥，且在每次试验中必有一个发生，则 A 与 B 互为对立事件。
- recognition_signals: 题目出现“正面与反面”“合格与不合格”这类一分为二的结果 | 常与补集思路一起使用 | 后续常转化为 1 减某事件概率
- boundary: 对立事件一定互斥且必有一个发生，比一般互斥关系更强。
- common_errors: 只看到不能同时发生就误判为对立事件 | 忽略“必有一个发生”的条件 | 把对立事件和独立事件混淆
- review_cue: 判断对立事件要同时检查两点：不能同时发生，而且不可能都不发生。
- example_refs: problem.probability.complementary_events.01

### math.统计与概率.概率.概率基本性质.对立事件概率公式
- keywords: 对立事件 | 补集 | 概率公式 | 至少一个
- aliases: P(对立)=1-P(原事件)
- formula: P(not A) = 1 - P(A)
- applicable_conditions: A 与 not A 互为对立事件 | 两事件不能同时发生且必有一个发生
- special_cases: 求“至少一个”时常先转化为“一个也没有”的对立事件 | 求“至多”时也可先换成补集再计算
- variable_notes: not A 表示事件 A 的对立事件，含义是“A 不发生”。
- derivation_hint: 对立事件的概率和恒等于 1。
- common_errors: 把一般互斥事件误套成对立事件公式 | 没先确认两个事件是否构成对立 | 不会把“至少一次”转化成补集问题
- review_cue: 能用这个公式之前，先确认是不是“必有一个发生”的一对事件。
- example_refs: problem.probability.complementary_formula.01

### math.统计与概率.概率.概率基本性质.互斥事件加法公式
- keywords: 互斥事件 | 加法公式 | 概率
- aliases: P(A∪B)=P(A)+P(B)
- formula: 若 A 与 B 互斥，则 P(A ∪ B) = P(A) + P(B)
- applicable_conditions: A 与 B 互斥 | 需要求“事件 A 或事件 B 发生”的概率
- special_cases: 多个事件互斥时，可逐个相加 | 若不互斥，不能直接用这个简化公式
- variable_notes: 这里的“或”是并事件，不是口语里的随便选一个。
- derivation_hint: 因为互斥时交集概率为 0，所以一般加法公式退化为直接相加。
- common_errors: 没判断是否互斥就直接相加 | 把“至少一个发生”简单当成两个互斥事件相加 | 把并事件和交事件混淆
- review_cue: 看到加法公式先别算，先检查这几个事件能不能同时发生。
- example_refs: problem.probability.mutually_exclusive_addition.01

### math.统计与概率.概率.概率模型.古典概型计算
- keywords: 古典概型 | 等可能 | 排列组合 | 概率
- aliases: 古典概率
- formula: P(A) = favorable_outcomes / total_outcomes
- applicable_conditions: 所有基本事件等可能 | 样本空间有限且可枚举 | 分子分母能按统一标准计数
- special_cases: 排列组合题里先统一计数口径再代公式 | 抽取顺序不同会直接影响样本空间大小
- variable_notes: 分子是满足事件 A 的基本事件数，分母是样本空间总基本事件数。
- derivation_hint: 古典概型的关键不是套公式，而是先把样本空间拆成等可能基本事件。
- common_errors: 样本空间并不等可能却硬套古典概型 | 重复计数或漏计 | 分子分母采用了不同计数口径
- review_cue: 先确认每个基本事件是否真的等可能，再开始计数。
- example_refs: problem.probability.classical_model.01

### math.统计与概率.概率.概率模型.几何概型计算
- keywords: 几何概型 | 长度比 | 面积比 | 体积比 | 概率
- aliases: 几何概率
- formula: P(A) = measure(A) / measure(total)
- applicable_conditions: 试验结果可映射到某个几何区域 | 几何区域内结果均匀分布 | 可用长度、面积或体积度量
- special_cases: 一维问题常用长度比 | 二维问题常用面积比 | 三维问题常用体积比
- variable_notes: measure 表示对应维度的几何度量，如长度、面积、体积。
- derivation_hint: 几何概型本质上是“均匀分布下的占比”。
- common_errors: 看见图形就误判成几何概型 | 没确认是否均匀分布 | 用错度量类型，如该用面积却用长度
- review_cue: 先确定随机结果对应的是哪种几何量，再算占比。
- example_refs: problem.probability.geometric_model.01

### math.统计与概率.概率.概率模型.随机模拟法求概率
- keywords: 随机模拟法 | 频率估计概率 | 蒙特卡洛 | 概率方法
- aliases: 模拟法求概率
- method_goal: 通过大量重复随机试验，用频率近似估计事件发生概率。
- trigger_signals: 题目直接要求用模拟法估计概率 | 精确解析计算困难 | 题目给出随机试验流程或计算机模拟背景
- steps: 先明确一次试验的随机规则和成功条件 | 重复进行大量独立试验并记录成功次数 | 计算成功频率 | 用频率近似事件概率并解释误差来源
- applicable_problem_types: 难以直接解析的概率估计问题 | 掷骰子、转盘、随机取点等模拟场景
- failure_modes: 没先定义清楚一次试验的成功标准 | 试验次数太少就轻易下结论 | 把频率和概率的关系理解成恒等而不是近似
- review_cue: 模拟法的核心不是“算一次”，而是“规则固定后大量重复”。
- example_refs: problem.probability.simulation.01

### math.统计与概率.概率.概率模型.条件概率计算
- keywords: 条件概率 | P(B|A) | 样本空间缩小 | 概率
- aliases: P(B|A)
- formula: P(B|A) = P(AB) / P(A), where P(A) > 0
- applicable_conditions: 已知事件 A 已发生 | 需要在缩小后的样本空间 A 内求事件 B 的概率
- special_cases: 表格题中常表现为在某一行或某一列内部重新求比例 | 样本空间变化是条件概率的本质
- variable_notes: 条件事件是 A，目标事件是 B，先缩小到 A 再看 B。
- derivation_hint: 条件概率本质上是样本空间缩小后的重新计数。
- common_errors: 把条件事件和目标事件写反 | 没先缩小样本空间 | 和独立事件乘法公式混用
- review_cue: 先圈出“已知谁发生”，再问样本空间现在只剩下什么。
- example_refs: problem.probability.conditional.01

### math.统计与概率.概率.概率模型.相互独立事件概率
- keywords: 独立事件 | 互不影响 | 概率 | 乘法公式
- aliases: 独立事件
- definition: 如果事件 A 是否发生不影响事件 B 发生的概率，则 A 与 B 相互独立。
- recognition_signals: 题目强调两个事件互不影响 | 常与乘法公式一起使用 | 题目没有给出“已知某事件已发生”的条件限制
- boundary: 独立不等于互斥，也不同于条件概率场景。
- common_errors: 把独立事件误当成互斥事件 | 把“已知 A 发生”误判成独立关系 | 只要看到乘法就直接套独立事件公式
- review_cue: 先区分这是“互不影响”，还是“已知某事件已经发生”。
- example_refs: problem.probability.independent_events.01

### math.统计与概率.概率.重复试验与分布.n_次独立重复试验
- keywords: 独立重复试验 | 成功概率相同 | 概率模型
- aliases: 伯努利重复试验
- definition: 在重复进行 n 次试验时，若每次试验相互独立且成功概率保持不变，则称为 n 次独立重复试验。
- recognition_signals: 题目出现“重复进行 n 次” | 每次只有成功或失败两种结果 | 每次成功概率保持相同
- boundary: 只要某次概率依赖前一次结果，或每次成功概率变化，就不能视为独立重复试验。
- common_errors: 只看到“重复”就忽略独立性 | 忘记检查成功概率是否恒定 | 把多种结果的试验误当成伯努利试验
- review_cue: 先逐条检查三件事：独立、重复、成功概率是否恒定。
- example_refs: problem.probability.repeated_trials.01

### math.统计与概率.概率.重复试验与分布.二项分布概念与计算
- keywords: 二项分布 | 独立重复试验 | X~B(n,p) | 概率
- aliases: X~B(n,p)
- formula: P(X=k) = C(n,k) p^k (1-p)^(n-k)
- applicable_conditions: 进行 n 次独立重复试验 | 每次试验只有两种结果 | 每次成功概率恒为 p | 随机变量 X 表示成功次数
- special_cases: 求“至少一次”时常先转化为“0 次成功”的对立事件 | 求“至多”时常结合分布列逐项求和
- variable_notes: n 是试验次数，k 是成功次数，p 是每次成功概率。
- derivation_hint: 二项分布建立在独立重复试验和“统计成功次数”这两个前提之上。
- common_errors: 题目不满足独立重复试验也硬套二项分布 | 把至少一次和恰好一次混淆 | n、k、p 含义对应错误
- review_cue: 先检查四件事：独立、重复、两结果、同概率。
- example_refs: problem.probability.binomial_distribution.01

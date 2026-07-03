### math.统计与概率.概率.概率基本性质.互斥事件概念
- keywords: 互斥事件 | 不能同时发生 | 概率
- aliases: 互不相容事件
- definition: 如果事件 A 与事件 B 不能同时发生，则称 A 与 B 互斥。
- recognition_signals: 题目强调不能同时发生 | 需要判断两个事件是否有交集 | 后续常与加法公式一起使用
- boundary: 互斥强调不能同时发生，不等于相互独立。
- common_errors: 把互斥事件误当成独立事件 | 只看事件名称相似就判断互斥 | 不会从题意判断两个事件能否同时发生
- review_cue: 先问自己这两个事件能不能在一次试验里同时发生。
- example_refs: problem.demo.mutually_exclusive_events.01

### math.数列与不等式.数列.等差_等比数列.等比数列求和公式
- keywords: 等比数列 | 求和公式 | 前n项和 | q=1
- aliases: 等比前n项和
- formula: S_n = a_1(1-q^n)/(1-q) when q != 1; S_n = n a_1 when q = 1
- applicable_conditions: 目标是求等比数列前 n 项和 | 已知首项、公比、项数或足够信息
- special_cases: 必须分类讨论 q=1 和 q!=1
- variable_notes: S_n 是前 n 项和，q 是公比。
- derivation_hint: 常由 qS_n - S_n 或错位相减思路推出。
- common_errors: 漏分 q=1 和 q!=1 | 把 q^n 写错 | 项数和末项位置混淆
- review_cue: 做等比求和先别代公式，先判 q 是否等于 1。
- example_refs: problem.demo.geometric_series_sum.01

### math.数列与不等式.数列.递推数列转化方法.逐差累加法
- keywords: 逐差累加法 | 递推数列 | 通项 | 数列方法
- aliases: 逐差求和
- method_goal: 把相邻项差的关系累加起来，恢复原数列或求通项。
- trigger_signals: 题目给出 a_(n+1)-a_n 的关系 | 递推式表现为相邻两项之差 | 需要由差分关系还原数列
- steps: 先把递推关系改写成标准差分形式 | 从起点累加到目标项前 | 利用中间项相消得到 a_n 与首项关系 | 整理得到通项或所求量
- applicable_problem_types: 差分型递推数列 | 由相邻差求通项 | 求和前先还原数列
- failure_modes: 累加上下限写错 | 忘记利用首项条件 | 相消后剩余项整理错误
- review_cue: 看到 a_(n+1)-a_n 型递推，先想能不能一路累加把中间项消掉。
- example_refs: problem.demo.termwise_difference_accumulation.01

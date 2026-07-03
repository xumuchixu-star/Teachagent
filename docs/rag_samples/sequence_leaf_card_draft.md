### math.数列与不等式.数列.基础概念.数列的概念与分类
- keywords: 数列 | 项 | 项号 | 有穷数列 | 无穷数列
- definition: 按照一定顺序排成一列的数构成数列，其中每个数叫作这个数列的项。
- recognition_signals: 题目用 a_n 表示第 n 项 | 强调“按顺序”给出一列数 | 需要区分前几项与第 n 项
- core_idea: 先把项号和项值一一对应起来，再谈通项、性质和求和。
- boundary: 数列本质上是定义在正整数集或其有限子集上的函数，顺序不能打乱。
- common_errors: 把数集当成数列忽略顺序 | 将 a_n 与 n 混淆 | 不会区分有穷数列和无穷数列
- review_cue: 看见一列数先问自己，第 n 项是谁，项号和项值如何对应？
- example_refs: problem.sequence.concept.01

### math.数列与不等式.数列.基础概念.数列三种表示方法解析___图象___列表
- keywords: 解析式 | 图象 | 列表 | 数列表示
- method_goal: 在解析式、列表、图象三种表示之间互相读取并转换数列信息。
- trigger_signals: 题目给出前几项要求猜规律 | 题目给出点列图象读取增减或符号 | 需要把通项和表格信息对应起来
- applicable_problem_types: 由列表归纳规律 | 由解析式写出前几项 | 读图判断数列性质
- steps: 先明确横坐标 n 与第 n 项 a_n 的对应 | 观察数值变化、符号变化、周期或倍数关系 | 将读出的规律写成解析式或口头结论 | 再用前几项回代验证
- failure_modes: 只看项值不看项号 | 把函数连续图象理解成数列完整图象 | 猜到规律后不验证
- review_cue: 数列图象是离散点，不要把它看成连续曲线。
- example_refs: problem.sequence.representation.01

### math.数列与不等式.数列.基础概念.数列通项公式求解
- keywords: 通项公式 | 归纳规律 | a_n | 数列
- method_goal: 从前几项、结构特征或已知关系中写出数列的通项公式。
- trigger_signals: 题目给出前几项求 a_n | 题目给出某种递推或结构规律 | 需要判断数列属于等差、等比或分段规律
- applicable_problem_types: 已知前几项求通项 | 由递推关系猜测通项 | 含奇偶项或周期项的规律归纳
- steps: 先观察相邻项差、比、符号与奇偶位置特征 | 判断能否归入等差、等比、周期或分段模型 | 写出候选通项公式 | 用前几项和一般项关系回代检验
- failure_modes: 只凭前两三项草率下结论 | 混淆项号 n 与项值 a_n | 写出公式后不检验适用范围
- review_cue: 求通项不是先猜，而是先看差、比、奇偶和周期。
- example_refs: problem.sequence.general_term.01

### math.数列与不等式.数列.基础概念.数列递推公式解读
- keywords: 递推公式 | 前后项关系 | 首项 | 数列
- method_goal: 从递推关系中读出前后项联系、初始条件和可转化方向。
- trigger_signals: 题目出现 a_(n+1) 与 a_n 的关系 | 同时给出首项或前几项 | 需要由递推式求若干项、性质或通项
- applicable_problem_types: 由递推式写前几项 | 由递推式判断单调性 | 由递推式转化为等差或等比模型
- steps: 先找清楚递推涉及哪些项以及起始下标 | 单独记录首项或初值条件 | 试写前几项观察差、比或可变形结构 | 判断适合逐差、逐商还是构造新数列
- failure_modes: 忽略初始条件 | 下标错位导致前后项关系写反 | 只会机械代几项，不会观察转化方向
- review_cue: 读递推式时先找“谁由谁决定”，再看“从哪一项开始”。
- example_refs: problem.sequence.recursion.01

### math.数列与不等式.数列.等差_等比数列.等差数列通项公式
- keywords: 等差数列 | 通项公式 | 公差 | a_n
- formula: a_n = a_1 + (n-1)d
- applicable_conditions: 数列已知为等差数列 | 已知首项与公差或可转化得到它们 | 目标是求第 n 项或建立项间关系
- special_cases: 若已知第 m 项，可改写为 a_n = a_m + (n-m)d | 当 d=0 时数列为常数列
- variable_notes: a_1 是首项，d 是公差，n 是项号。
- derivation_hint: 等差数列每前进一步都增加同一个公差，所以第 n 项比首项多走了 n-1 步。
- common_errors: 把 n-1 写成 n | 混淆公差 d 的正负 | 已知 a_m 时不会改写项间公式
- review_cue: 套等差通项前先确认“首项”和“公差”是否已经确定。
- example_refs: problem.sequence.arithmetic_term.01

### math.数列与不等式.数列.等差_等比数列.等差数列求和公式
- keywords: 等差数列 | 前n项和 | 求和公式 | S_n
- formula: S_n = n(a_1 + a_n)/2 = n[2a_1 + (n-1)d]/2
- applicable_conditions: 数列已知为等差数列 | 目标是求前 n 项和 | 已知首项、末项、公差或足够转化信息
- special_cases: 已知首项和末项时优先用 S_n = n(a_1 + a_n)/2 | 已知首项和公差时优先用含 d 的公式
- variable_notes: S_n 表示前 n 项和，a_n 表示第 n 项，d 表示公差。
- derivation_hint: 首尾配对后，每一对的和相等，这是等差求和公式的核心来源。
- common_errors: 把项数 n 漏掉 | 首项末项位置代错 | 不会根据已知条件选择更简洁的公式
- review_cue: 求和前先看已知里有没有 a_n，没有时再考虑先求末项或直接用含 d 公式。
- example_refs: problem.sequence.arithmetic_sum.01

### math.数列与不等式.数列.等差_等比数列.等差数列性质与判定
- keywords: 等差数列 | 性质 | 判定 | 中项
- definition: 若一个数列从第二项起每一项与前一项的差都等于同一常数，则该数列为等差数列。
- recognition_signals: 题目给出相邻两项差相等 | 题目出现 a_n = pn + q 这类一次式 | 需要利用中项或下标和相等性质解题
- core_idea: 等差数列的本质是“相邻项差不变”，很多性质都从这一点展开。
- boundary: 某几段局部差相等不代表整个数列都是等差数列，判定时要看一般关系。
- common_errors: 只验证前几项就断定是等差数列 | 把等差中项性质乱用于非等差数列 | 忽略公差可以为负数或 0
- review_cue: 判定等差最稳的方法仍是回到“相邻项差是否恒定”。
- example_refs: problem.sequence.arithmetic_property.01

### math.数列与不等式.数列.等差_等比数列.等比数列通项公式
- keywords: 等比数列 | 通项公式 | 公比 | a_n
- formula: a_n = a_1 q^(n-1)
- applicable_conditions: 数列已知为等比数列 | 已知首项与公比或可转化得到它们 | 目标是求第 n 项或建立项间关系
- special_cases: 若已知第 m 项，可改写为 a_n = a_m q^(n-m) | 当 q=1 时数列为常数列
- variable_notes: a_1 是首项，q 是公比，n 是项号。
- derivation_hint: 等比数列每前进一步都乘同一个公比，所以第 n 项相当于首项连续乘了 n-1 次 q。
- common_errors: 把 q^(n-1) 写成 q^n | 混淆公比与公差 | 已知 a_m 时不会写成项间形式
- review_cue: 先确认这是“等比”而不是“相邻差固定”的等差模型。
- example_refs: problem.sequence.geometric_term.01

### math.数列与不等式.数列.等差_等比数列.等比数列求和公式
- keywords: 等比数列 | 前n项和 | 求和公式 | q=1
- formula: S_n = a_1(1-q^n)/(1-q), when q != 1; S_n = n a_1, when q = 1
- applicable_conditions: 数列已知为等比数列 | 目标是求前 n 项和 | 已知首项、公比、项数或足够转化信息
- special_cases: 必须分类讨论 q=1 与 q!=1 | 处理实际题目时要先判断公比是否为 1
- variable_notes: S_n 表示前 n 项和，a_1 是首项，q 是公比。
- derivation_hint: 等比求和常通过“错位相减”消去中间项得到。
- common_errors: 漏分 q=1 和 q!=1 | 把 1-q^n 与 1-q 的顺序写错 | 对负公比情形不敢直接代公式
- review_cue: 一看到等比求和，先判公比是不是 1。
- example_refs: problem.sequence.geometric_sum.01

### math.数列与不等式.数列.等差_等比数列.等比数列性质与判定
- keywords: 等比数列 | 性质 | 判定 | 公比
- definition: 若一个非零数列从第二项起每一项与前一项的比都等于同一常数，则该数列为等比数列。
- recognition_signals: 题目给出相邻两项比相等 | 题目出现 a_n = c·q^(n-1) 这类指数式 | 需要利用等比中项性质或乘积关系
- core_idea: 等比数列的本质是“相邻项比不变”，性质判断都围绕这个乘法结构展开。
- boundary: 只在个别相邻项上比值相同，不能直接推出整个数列等比；同时要注意零项会影响公比判定。
- common_errors: 看到指数形式就草率断定等比 | 把等比中项性质用到含零或非等比情形 | 忽略公比可以为负数
- review_cue: 判定等比最核心的问题是，相邻项的比是否在整体上保持不变。
- example_refs: problem.sequence.geometric_property.01

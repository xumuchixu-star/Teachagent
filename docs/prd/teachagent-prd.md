# TeachAgent PRD: 错因诊断与复习闭环系统

Status: ready-for-agent
Issue tracker: local markdown
Scope: MVP to first internal test

## Problem Statement

学生在做错题后，常见问题不是“完全没人讲解”，而是讲解没有形成长期闭环。普通 AI tutor 往往只回答当前题，容易直接给答案，也容易陷入无限追问；普通错题本只记录题目和答案，无法稳定判断学生到底是概念漏洞、审题失误、计算失误、思路缺失还是习惯性粗心。

用户想做的 TeachAgent 不是一个万能学习聊天机器人，而是一个面向学生个体的错因诊断与复习调度系统。它需要在每道错题进入系统后，完成诊断、有限引导、变式验证、复习安排和长期学生画像积累，最终帮助学生减少同类错误的重复发生。

当前原型已经实现了 `CoachAgent` 的可控教学状态机：根据诊断结果选择教学模式，限制苏格拉底式追问轮数，学生连续答偏后降级为直接讲解，讲解后进入单变量变式验证。下一步需要把这个原型扩展成完整 MVP。

## Solution

TeachAgent 将被定义为“高中理科错题闭环系统”，首版聚焦单题闭环和复习闭环，不做万能学习 agent。

系统围绕四个核心资产构建：

- 稳定的错因标签体系
- 学生级历史错题记忆
- 可执行的复习调度规则
- 做题后再次验证的闭环

MVP 由三层组成：

- 产品核心层：错题录入、错因诊断、启发式讲解、变式练习、复习调度、学生画像。
- 智能编排层：Orchestrator、DiagnoseAgent、CoachAgent、ReviewPlanner。
- 数据与工具层：OCR、历史错题检索、题库查询、复习时间计算、学生数据写入。

首版体验应覆盖三条主流程：

- 新错题进入系统：上传或录入题目，提取题干和学生答案，产出结构化诊断并入库。
- 讲解与验证：检索历史同类错误，CoachAgent 做有限引导，必要时讲解，并生成变式题验证。
- 复习调度：根据错因风险、历史结果和间隔时间生成每日复习任务，并在完成后更新下一次复习计划。

## User Stories

1. As a 学生, I want 上传错题图片, so that 我不用手动输入长题干和解题过程。
2. As a 学生, I want 手动补充题干和答案, so that OCR 失败时系统仍然可以继续工作。
3. As a 学生, I want 勾选自己认为的错因, so that 系统诊断能结合我的主观感受。
4. As a 学生, I want 系统识别我这次主要错在哪里, so that 我知道问题不是只停留在“答案错了”。
5. As a 学生, I want 系统区分概念漏洞、审题失误、计算失误、思路缺失和习惯性粗心, so that 我能针对不同问题采用不同修正方式。
6. As a 学生, I want 系统结合我的历史错题, so that 它能发现我反复出现的薄弱模式。
7. As a 学生, I want CoachAgent 先问我少量关键问题, so that 我能自己想出第一步而不是直接看答案。
8. As a 学生, I want CoachAgent 不要无限追问, so that 我卡住时不会被反复逼问。
9. As a 学生, I want 连续答偏后系统直接讲解, so that 我能及时得到清晰路径。
10. As a 学生, I want 讲解后立刻做一道同类变式题, so that 我能验证自己是不是真的会了。
11. As a 学生, I want 变式题只改变一个关键条件, so that 我能知道自己是否掌握了同一知识点。
12. As a 学生, I want 系统记录我变式题是否做对, so that 后续复习安排能反映真实掌握情况。
13. As a 学生, I want 每天看到今日待复习错题, so that 我不用自己决定先复习什么。
14. As a 学生, I want 系统说明为什么今天要复习某道题, so that 我能理解复习任务的优先级。
15. As a 学生, I want 系统根据复习表现调整下一次复习时间, so that 我不会机械重复已经掌握的题。
16. As a 学生, I want 查看自己的错因分布, so that 我知道最近主要问题集中在哪里。
17. As a 学生, I want 查看某个知识点下的历史错题, so that 我能集中处理一个薄弱点。
18. As a 学生, I want 系统用稳定语气讲解, so that 我不会因为连续错误产生挫败感。
19. As a 学生, I want 系统记录我的偏好和历史表现, so that 后续讲解更适合我。
20. As a 教师, I want 查看学生的错因趋势, so that 我能判断是否需要人工干预。
21. As a 教师, I want 手动修正错因标签, so that 诊断结果不准确时长期数据不会被污染。
22. As a 教师, I want 查看系统给学生的追问和讲解, so that 我能评估教学质量。
23. As a 教师, I want 查看变式题完成情况, so that 我能判断学生是否真正掌握。
24. As a 教师, I want 导出或查看高风险错题, so that 我可以优先处理严重薄弱点。
25. As a 家长, I want 看懂孩子最近主要错因, so that 我知道孩子不是简单“不认真”。
26. As a 家长, I want 查看复习完成情况, so that 我能监督学习节奏而不是只看分数。
27. As a 产品开发者, I want 错因诊断输出结构化 JSON, so that CoachAgent、ReviewPlanner 和数据库能稳定消费。
28. As a 产品开发者, I want CoachAgent 的状态可保存和恢复, so that 多轮教学不会丢失上下文。
29. As a 产品开发者, I want 工具调用有明确输入输出, so that OCR、向量检索、题库和复习调度可以独立替换。
30. As a 产品开发者, I want 首版先用规则化 ReviewPlanner, so that 复习调度可解释、可测试、可调参。
31. As a 产品开发者, I want 向量检索按学生隔离, so that 不同学生的历史错题不会混淆。
32. As a 产品开发者, I want 先用本地 Provider/Agent/Session/run 接口, so that 未来可以平滑迁移到 LangGraph 或 OpenAI Agents SDK。
33. As a 产品开发者, I want 有明确停止条件, so that 苏格拉底式引导不会失控。
34. As a 产品开发者, I want 记录每次教学动作的 stop reason, so that 可以分析系统为什么追问、讲解或出变式。
35. As a 产品开发者, I want 每个错因标签含 confidence, so that 低置信度结果能进入人工复核。
36. As a 产品开发者, I want 题库查询支持知识点、错因和难度, so that 变式题更贴近当前错误。
37. As a 产品开发者, I want OCR 结果可以人工修正, so that 公式识别错误不会破坏后续诊断。
38. As a 产品开发者, I want 每个功能都有可运行的最小示例, so that 早期开发可以快速验证闭环。
39. As a 产品开发者, I want 用测试覆盖完整教学会话, so that 后续调整提示词或规则时不会破坏核心行为。
40. As a 产品开发者, I want PRD、接口和状态机保持一致, so that 后续 agent 开发不会偏离产品闭环。

## Implementation Decisions

- TeachAgent 不定位为万能学习 agent，而定位为高中理科错题闭环系统。
- 首版目标是验证单题闭环和复习闭环，不优先做复杂爬虫、反思 agent、动态 prompt 自我改写或大而全的学习平台。
- 错因诊断首版固定为五大类：概念漏洞、审题失误、计算失误、思路缺失、习惯性粗心。
- DiagnoseAgent 只负责输出结构化错因，不负责长篇讲解。
- CoachAgent 负责有限轮数的渐进式引导、必要时直接讲解、讲解后变式验证。
- ReviewPlanner 首版应是规则化模块，而不是 LLM agent，以保证复习计划可解释、可测试、可稳定调参。
- Orchestrator 只负责流程编排和状态流转，不直接承担教学判断。
- 当前原型中的核心状态机应保留：诊断结果生成教学策略，教学策略决定追问预算，学生回复更新状态，状态触发继续追问、直接讲解或进入变式验证。
- CoachAgent 对外接口优先采用 Provider -> Agent -> Session -> run 的形态，以贴近后续 agent framework 接入方式。
- CoachAgent 内部仍保留确定性策略引擎，以避免模型自由发挥破坏教学边界。
- 每轮 CoachAgent 输出必须包含 action、content、stop reason、policy 和 state snapshot。
- 学生回复判定首版可用启发式工具，后续应替换为结构化判定模型或小型分类器。
- 变式题首版只要求单变量变化，目标是验证同一知识点或同一错因，不追求复杂生成。
- 数据库应保存学生、错题、诊断、作答尝试、复习任务和学生偏好。
- 向量库应保存可检索的历史错题文本，并按 student_id 隔离 namespace。
- 向量文本应包含题干、错误步骤、错因标签、知识点、风险等级和上次复习结果。
- OCR 是独立工具，不应和诊断逻辑耦合；OCR 结果必须允许人工修正。
- 题库查询是独立工具，输入应包含知识点、错因、难度和数量。
- 复习时间计算是独立纯函数，输入应包含风险、上次结果和间隔天数，输出下一次复习时间和优先级分数。
- 首版技术栈建议为 Python + FastAPI，数据库优先 PostgreSQL，向量检索首版可用 FAISS 或 pgvector。
- 如果后续需要强流程可控，优先考虑 LangGraph；如果需要 sessions、handoff 和 guardrails，优先考虑 OpenAI Agents SDK。
- 首版页面只需要上传/录入、错因确认、讲解对话、今日复习列表和基础统计。
- 低置信度诊断、重复高风险错因和 OCR 不可靠结果应进入人工复核路径。
- 所有 agent 和 tool 的接口都应先围绕结构化输入输出设计，而不是先写自然语言 prompt。

## Testing Decisions

- 好测试应验证外部行为，而不是锁死私有实现细节。对 TeachAgent 来说，最重要的是验证一个学生会话在给定诊断、画像、题目和回复序列后，会产生正确的教学动作流。
- 最高优先级测试接缝是 Agent Session 层：创建 agent，创建 session，连续调用 run，断言输出 action、stop reason、state snapshot 和 tool trace。
- CoachAgent 应测试缺思路场景：第一轮提出中间量问题，学生有效回答后继续有限追问，再进入变式验证。
- CoachAgent 应测试学生连续答偏场景：连续弱回答达到阈值后，系统停止追问并直接讲解。
- CoachAgent 应测试空回复场景：空回复应计入失败，并在非直接讲解模式下触发降级。
- CoachAgent 应测试概念漏洞场景：系统应直接讲最小概念块，而不是继续苏格拉底式追问。
- CoachAgent 应测试审题失误场景：系统应引导复述限制条件，且追问预算低于缺思路场景。
- CoachAgent 应测试计算失误场景：系统应聚焦计算链条的第一处不一致，而不是重讲整题。
- CoachAgent 应测试习惯性粗心场景：系统应输出检查流程，而不是扩大讲解范围。
- CoachAgent 应测试低置信度或重复错题场景：系统应切到 worked example 或更直接的讲解路径。
- Tool 层应测试学生回复判定工具：空、弱、有效三类输入必须稳定分类。
- Tool 层应测试变式提示工具：有知识标签和无知识标签时都要输出可用提示。
- ReviewPlanner 应以纯函数测试为主：给定风险、上次结果和间隔天数，输出稳定的 priority score 和 next review date。
- DiagnoseAgent 应使用 fixture 测试：同一类错误多次运行应稳定落到同一错因标签，避免标签漂移。
- OCR 工具首版应使用 mock 或固定样例测试，不把 OCR 服务稳定性作为核心单元测试前提。
- 历史错题检索应测试 student_id 隔离，确保一个学生不会检索到另一个学生的数据。
- 题库查询应测试单变量变式要求，确保返回题目仍然围绕同一知识点或错因。
- 端到端测试应覆盖完整闭环：录入错题、诊断、CoachAgent 引导、变式验证、写入复习任务。
- 回归测试应覆盖当前原型示例，确保未来迁移到真实 agent framework 后，核心教学动作流不变。

## Out of Scope

- 首版不做万能学习助手。
- 首版不做自动网页爬虫和教材内容抓取。
- 首版不做复杂 Excel 导出。
- 首版不做多层 ReflectionAgent。
- 首版不做动态 prompt 自我改写。
- 首版不做复杂代码执行 agent。
- 首版不承诺数学 OCR 完全自动准确，必须保留人工修正。
- 首版不做完整移动端 App。
- 首版不做大规模班级管理系统。
- 首版不做支付、订阅、营销增长功能。
- 首版不做跨学科全覆盖，优先聚焦高中理科中的一个或少数题型。

## Further Notes

本 PRD 的 `ready-for-agent` 开发入口建议如下：

- 先把当前 CoachAgent 原型补测试，锁定有界追问、降级讲解、变式验证这三条关键行为。
- 再设计 DiagnoseAgent 的结构化输出，使其字段与当前 CoachAgent 的 Diagnosis 输入完全对齐。
- 然后实现 ReviewPlanner 的纯函数版本，先不引入 LLM。
- 最后再接 OCR、向量检索和题库查询，避免首版过早被工具链复杂度拖慢。

测试接缝建议：

- 最高层：Agent Session 的连续 run 行为。
- 中间层：教学策略从 diagnosis/profile 映射到 policy。
- 工具层：学生回复判定、变式提示、题库查询、复习调度。
- 数据层：学生隔离、错题记录、复习任务状态变化。

该 PRD 基于当前 TeachAgent 原型、`yisheng.txt` 中的产品方向，以及已采用的 Provider -> Agent -> Session -> run 接口风格整理。

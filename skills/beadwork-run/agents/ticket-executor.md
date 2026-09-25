# Ticket Executor

你协调一张已领取 ticket 的实现、验证和双轴 review，只写执行证据。controller 管批次、Beads 和 Git/worktree；当前 implementer 是唯一源码 writer。

## 建立上下文

读取 root dispatch 的 required_reads 和适用规则；填写报告时读取当前 stage 的 draft_schema_path。执行 `beadwork.py executor inspect`，核对 ticket、comments、parent、BASE、linked spec、相关 ADR 和验证 recipes。原始需求与实现证据存在矛盾时定点追查。

你负责 acceptance、Test plan、seam 授权、验证覆盖和失败类别的语义判断；脚本管理身份、阶段、额度和来源。按返回的模型配置派发独立上下文 agent，使用 `fork_turns: "none"`。宿主需支持 implementer 和同层的两名并行只读 reviewers。

## 阶段循环

1. 按 [ticket-execution.md](../references/ticket-execution.md) 准备或恢复 stage，读取该 stage 的 required_reads，按当前有效测试模式建立上下文，再向全新 implementer 交接 dispatch、需求/规则来源及进度通信目标。后续修复交接 active_stage_context_source 和 context_sources。
2. implementer 集中完成实现、定向验证、提交和阶段内最多三次交付 gate-fix。等待其停止后，核对 acceptance、有效 red、seams、本票行为证据、干净候选 gate-core 及失败处置，再执行 implementer-accept。完整项目回归由 parent finalize 执行。
3. 实现通过后按 [review.md](../references/review.md) 派发两轴，BASE 为原 ticket base_commit。review 期间冻结候选。
4. 组装阶段报告。passed 进入整票交付；code_failure 在额度内进入下一 stage；其他阻塞保存来源并交回 controller。报告错误走更正流程。

同 HEAD 的有效 gate 结果复用。review 开始后的源码修复进入新 stage；阶段进度直接发送 controller。额度来自返回的 dispatch；特殊恢复和授权扩展按 ticket-execution 的条件入口处理。

## 计划适配与交付

BASE 已满足原计划行为时，按 [baseline-adaptation.md](../references/baseline-adaptation.md) 核对实现者证据并调整验证策略；读取更新后的 stage.required_reads，同一 implementer 使用新 dispatch 继续。需求、产品范围或 seam 授权变化交回 controller。

整票完成要求 commits 属于本票、acceptance 有证据、gate-core 与最后双轴 PASS 覆盖交付 HEAD，现场干净且任务结束。使用 ticket-deliver 生成 root 回执后交付，包括合法阻塞报告。恢复指针、原始 findings 和未完成现场由证据链保留。

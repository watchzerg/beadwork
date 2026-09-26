---
name: beadwork-run
description: "按批准顺序串行实现一个 Beads parent 下的 ticket 依赖图，经双轴 review 完成本地提交与 main 集成。"
---

# Beadwork Run

给定完整 Beads parent ID，按批准顺序完成其 direct children，经逐票实现与双轴 review、最终文档同步和完整验收，合入本地 main、关闭 tickets 并清理。交付止于本地；Git/Beads push 和 bd dolt pull 属于单独操作。

```text
$beadwork-run <full-parent-bead-id>
branch:   implement/<full-parent-id>
worktree: .worktrees/<full-parent-id>
```

parent 的 Beads type 不受限制。controller 管批次、Git/worktree、环境、Beads 写入与最终集成；每票派全新 executor，后者管理 implementer、文档收尾的 document-syncer 与双轴 reviewers；全部 tickets 完成后派 finalizer，管理 document-syncer、fixer 与最终 reviewers。

## 开始执行

- 解析 skill 与项目规则的真实绝对路径。内置 Python CLI 使用 python3 ≥ 3.14，在目标 repository/worktree 执行；stdout 为 JSON，普通操作非零退出时保留现场并处理原因。验证采集的退出码另见 [verification.md](references/verification.md)。
- 读取 [testing-contract.md](references/testing-contract.md)、[report-delivery.md](references/report-delivery.md) 和 [controller-operations.md](references/controller-operations.md)。建立基线和核对最终覆盖时读 testing-gates.md；测试计划或 seam 冲突按共享测试契约路由。
- 宿主为 Codex，支持 controller → preflight、controller → executor → implementer/document-syncer/reviewers、controller → finalizer → document-syncer/fixer/reviewers 的独立上下文派发、并行只读 review、文件报告和任务结束观察。写入前确认这些能力。
- 子 agent 按 prepare 返回的模型配置派发，使用 `fork_turns: "none"`，交接 dispatch 路径、required_reads、适用规则、任务来源及进度通信目标。preflight/finalizer 默认 Sol-medium，复杂现场可用 Sol-high；controller 建议 Sol-medium，复杂恢复可用 high。模型政策和明确授权扩展见 [model-policy.md](references/model-policy.md)。
- Beads 查询使用结构化 `--json`；写入统一走 controller 的 tracker intent/readback 入口。

## 1. Preflight 与初始化

执行 `controller prepare preflight`，使用返回的 primary、固定 branch/worktree 和证据目录派发 preflight。controller 先交接来源，票据和 spec 正文由 preflight 收集。

按共享交付协议执行 accept，核对结论与来源。READY 固定首次 expected_children、执行计划及逐票测试计划；controller 按疑问读取相关原文。BLOCKED 修复准入缺项后重新派发，沿用首次 children 集合。

进入初始化前复核 `.beads` 无 diff，branch/worktree、checkout 与 dirty 状态符合报告。READY 后仍需 install、安装后 gate-core 基线和原子 claim。

- 新批次：按 controller-operations 执行 update-main，再 batch-initialize prepare/execute；脚本完成 worktree、环境、基线、parent claim 和批次 comment。
- 已有现场：[recovery-batch.md](references/recovery-batch.md)。
- parent 或全部 children 已关闭：[recovery-post-merge.md](references/recovery-post-merge.md)。
- 初始化失败：保留原 intent 和日志，按 controller-operations 恢复。

## 2. 串行 ticket 循环

```bash
python3 <skill-dir>/scripts/beadwork.py graph next <parent-id> <expected-child-id>...
```

expected children 逐个传参。脚本核对固定范围、计划、依赖和实时状态，选择批准序列中第一张未关闭的票。

1. `claim` frontier：确认旧 writer 及命令结束，执行 sync-main；仅按返回的刷新 frontier 原子领取。同步变化时脚本按安装输入决定 install，并建立 gate-core 基线。冲突按项目规则及 resolving-merge-conflicts 处理后恢复原同步。
2. 领取成功后 prepare executor（mode=new，带 sync_result 和 READY preflight_acceptance）。写 start comment，记录 parent、branch、worktree、完整 BASE、root dispatch 与 sync_result；成功后派发 executor。
3. `resume` frontier：按 [recovery-ticket.md](references/recovery-ticket.md) 核实原 BASE/root，prepare mode=resume 后接续。`done` 进入最终集成；其他阻塞按停止处理。
4. executor 自行完成 stage 循环。controller 接收进度，等待 root 交付；按共享契约确认后代任务结束并 accept。
5. 核对整票来源、最终状态、gate-core、本票行为证据、代码候选 review 与适用文档收尾的 HEAD 关系、现场和收尾。日常 Test plan/red/seam/acceptance 语义由 executor 验收；矛盾、缺证或越界时追查。误写 primary 时保留现场并停止。
6. DONE：调用 controller comment，以已验收报告生成 completion；直接将 comment_source 用作 tracker body_source。写入成功后 close，绑定 acceptance，再刷新 frontier。
7. NEEDS_CONTEXT 按 [recovery-needs-context.md](references/recovery-needs-context.md) 补事实；BLOCKED 按 [recovery-blocked.md](references/recovery-blocked.md) 保存停止与恢复入口。

补证使用 append-only acceptance-evidence-N.json，字段为 report_path、report_sha256、sources（source/evidence）。completion 引用原报告、更正和补证。

## 3. 最终验证与 review

1. graph next 确认固定 children 全部关闭。update-main 固定本地 main，使用返回完整 SHA 作为 reviewed_main 执行 sync-final；已有未完成 intent 时恢复原输入。同步成功后派 finalizer。
2. prepare finalizer，交接 reviewed_main、final_sync_result、linked spec、ticket/completion pointers、规则和通信目标。首次 prior_finalization 为 null；接替时读 [recovery-finalizer.md](references/recovery-finalizer.md)。
3. finalizer 管文档同步、完整 gate-full、修复与双轴 review；executor/finalizer 对纯文档 findings 均使用一次 [限定文档收尾](references/document-closeout.md)。controller 等待 final-deliver 的 root 交付，确认任务结束并 accept。
4. READY_TO_MERGE 时核对批次身份、固定 children、reviewed_main、文档结果、完整 gate-full、parent acceptance 覆盖、最后双轴 review、适用的文档收尾验收、提交和原始 findings 来源，以及干净现场和实际收尾。有矛盾时定点追查；通过后复用有效 gates/review。

BLOCKED 保存 parent 停止记录；根因不明时读 [recovery-diagnosis.md](references/recovery-diagnosis.md)。

## 4. 集成与清理

1. 从已验收报告生成 integration-ready，直接将 comment_source 写入 parent。
2. 使用实际 comment ID 调用 controller merge，checkpoint 留在本轮证据目录。脚本复核现场后 fast-forward。仅 primary dirty 时恢复干净后复用验收；main 已移动则重新最终集成。中断或失败按 [recovery-merge.md](references/recovery-merge.md) 核对。
3. `merged: true` 后使用返回 reviewed_head，写 parent completion，只记录该 SHA 与 integration-ready comment ID；已有对应 completion 则复用。
4. completion 成功后 close parent，绑定 merge checkpoint。再调用 cleanup，检查 ancestry、归属和干净状态后非强制清理，保留证据目录。

## 停止与最终报告

检查失败或契约不满足时保留现场。恢复先核实原因已解除、旧 writer 与命令已结束，沿用既有证据和额度。

parent 已领取后的实际批次停止，controller 先写中文 parent comment：停止原因、已完成进度、确定判断与不确定性、推荐下一步及依据、恢复入口。child 阻塞详情在 child comment，parent 留指针。只有用户决定会改变行为、范围或风险时提出选择。executor 内部自动修复仅追加检查点并报告进度。

向用户报告 parent 状态、按顺序的 tickets/commit ranges、每票与最终验证/review、文档结果、非阻塞 smells、本地 main SHA、清理结果和保留证据路径 `<primary>/.worktrees/.evidence/<parent-id>/`，说明本次本地交付范围。

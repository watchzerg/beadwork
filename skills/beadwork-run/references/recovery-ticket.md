# 恢复 ticket

从 start comment 核实完整 BASE 和 executor root dispatch。BASE 缺失且无法由批次记录、已完成票证据和干净现场证明时停止，不从 HEAD~1 猜测。

controller 使用 prepare executor mode=resume，提供原 root 的 previous_dispatch、原 BASE、test mode/seams 及身份字段；只恢复原整票入口，不填写 stage/models、previous_report/receipt 或 continuation=repair。脚本返回原 root；executor 从连续检查点中恢复当前 stage、明确选中的报告及有效计划。计划适配来源以检查点选中的 stage 为准。

恢复前核实旧 executor、implementer、reviewers 及命令结束。未确认停止时不派接替 writer。具体恢复位置和禁止重置的计数见 ticket-execution.md；代码失败在 executor 内推进 stage，controller 不自动新增额度；用户明确追加时按 recovery-blocked.md 交接给恢复的 executor。已完成 ticket 应复用整票交付并关闭，不再恢复实现。

## executor 阶段恢复

- `continuation: resume`：恢复当前阶段；无阶段时建立 stage 0。恢复返回原 dispatch、已选中的交付来源和 review 状态，不重新分配额度。
- `continuation: repair`：前阶段必须有已验收的 `code_failure`，且旧任务已结束；建立下一阶段，新 implementer，最多到当前授权上限（dispatch.stage_limit，未设置时为默认 stage 5）。
- `continuation: recover`：仅恢复已按 `blocked` 封存的未登记 gate 修正。review 尚未开始、当前干净 HEAD 必须与阶段报告一致并且是修正前候选的不同后继，旧任务必须结束，同时提供非空 `recovery_reason`。已有已绑定 repair 候选时直接引用；首次修正在 `begin-gate-repair` 前提交、尚无候选时必须另传 `recovery_failure`，绑定修正前原始 delivery gate 失败的 `result.json`。脚本验证失败的 stage identity、日志哈希、干净 HEAD、退出状态和 ancestry，在旧阶段目录追加 `unregistered-gate-repair-recovery.json`，再建立下一阶段并消耗一个 stage。普通环境、spec、seam 或证据阻塞不能使用该入口。
- `continuation: extend`：读取 [模型政策与授权扩展](model-policy.md)，按用户明确授权追加一次额度。
- 新阶段可提供 `model_overrides` 和非空 `model_override_reason`，角色只允许 implementer/standards/spec；覆盖只能提高档位，后续不降档。已有 stage 恢复沿用模型。


review_started 时读取原 round 和已选 collection，按 repair_route 继续；已有 implementer DONE 则直接继续 review。已有阶段报告时按 outcome 继续或交付。恢复保留原 BASE、正确实现与额度。

已存在 document_closeout 时，先读取绑定的 dispatch 与 acceptance，按 [文档收尾](document-closeout.md) 接续。已验收的收尾不重新派 writer/reviewer；通过则交付，blocked 则报告阻塞，code_required 则按代码修复规则推进。尚未交付的中断任务只在确认旧任务及命令结束后接续原 dispatch，不重新调用 prepare。

# executor 阻塞

根因不明的技术失败先读取 `recovery-diagnosis.md`。controller 验收报告并确认 writer、命令和子任务已结束后，按 `outcome` 处理：

- `code_failure`：本票代码导致交付 gate 或 review 失败；writer 的最多三次就地 gate 修正按 `verification.md` 处理，正式返回 code_failure 后不在原阶段重新发放机会。`stage < 3` 时记录已完成工作、失败证据及剩余问题，ticket 保持 `in_progress`，用 `continuation: repair` 派下一阶段；`stage == 3` 时设为 `blocked` 并执行停止记录。
- `interrupted`：预算或会话中断，记录现场，用 `continuation: resume` 接续当前阶段；沿用阶段和历史证据，不重置额度。
- `blocked`：宿主能力、环境、外部依赖、产品/spec 决策、seam 授权或报告验收问题，记录原因并停止；原因已解除后接续当前阶段。写入停止状态无法确认时保持现场，不能派接替 writer。

代码修复最多四阶段，每阶段的就地 gate 修正另按验证契约计数，不另设恢复次数或无进展计数。历史报告没有 outcome 时，按 controller 入口核对原始 gate/review 证据后导入；原文件保持不变。

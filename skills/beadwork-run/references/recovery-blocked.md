# executor 阻塞

controller 验收整票报告并确认 executor、后代 writer/reviewers 与命令结束后处理：

- code_failure：executor 已用尽当前授权阶段，设为 blocked 并记录停止。仅在尚未追加过额度且用户明确追加 1–5 个 stage 时，controller 按 recovery-ticket.md 恢复原 root，交接追加数量和具体授权说明，由 executor 按 ticket-execution.md 调用 extend；不自动增加额度。
- interrupted：保存整票 root 和检查点、已有 commits、dirty 现场与剩余工作；恢复原 root 和未完成 stage，不重置 gate-fix 额度。
- blocked：环境、工具、能力、外部依赖、spec、seam 授权或证据问题；记录原因并停止，解除后恢复原 root。已有 review 则继续该 round 或同 HEAD 的报告更正，不重派同 stage writer。

若阻塞原因是 writer 在 `begin-gate-repair` 前已经提交修正，且 review 未开始、当前现场是报告绑定的干净后继，解除阻塞后由原 executor 对 root 调用 `ticket-stage`。旧阶段已有 repair 候选时传入 `{"continuation":"recover","recovery_reason":"<具体原因>"}`；首次修正尚无候选时另传 `recovery_failure`，其值为修正前原始 delivery gate 失败的 `result.json` 绝对路径。脚本校验失败来源并追加恢复证据，再进入下一 stage；不改写旧候选或失败证据，不恢复旧 writer。其他 blocked 原因继续按原 stage 恢复。

根因不明时读取 recovery-diagnosis.md。写入停止状态无法确认时保留现场，不派接替 writer。所有报告、日志和更正来源 append-only；不另设无进展计数或恢复次数。单票内部的代码修复和最多三次就地 gate-fix 分别由 executor 与 implementer 管理。

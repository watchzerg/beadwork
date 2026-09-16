# executor 阻塞

controller 验收整票报告并确认 executor、后代 writer/reviewers 与命令结束后处理：

- code_failure：executor 已用尽 stage 0..3，设为 blocked 并记录停止，不再自动派第五阶段。
- interrupted：保存整票 root 和检查点、已有 commits、dirty 现场与剩余工作；恢复原 root 和未完成 stage，不重置 gate-fix 额度。
- blocked：环境、工具、能力、外部依赖、spec、seam 授权或证据问题；记录原因并停止，解除后恢复原 root。已有 review 则继续该 round 或同 HEAD 的报告更正，不重派同 stage writer。

根因不明时读取 recovery-diagnosis.md。写入停止状态无法确认时保留现场，不派接替 writer。所有报告、日志和更正来源 append-only；不另设无进展计数或恢复次数。单票内部的代码修复和最多三次就地 gate-fix 分别由 executor 与 implementer 管理。

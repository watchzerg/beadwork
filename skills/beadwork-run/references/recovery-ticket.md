# 恢复 ticket

从 start comment 核实完整 BASE 和 executor root dispatch。BASE 缺失且无法由批次记录、已完成票证据和干净现场证明时停止，不从 HEAD~1 猜测。

controller 使用 prepare executor mode=resume，提供原 root 的 previous_dispatch、原 BASE、test mode/seams 及身份字段；只恢复原整票入口，不填写 stage/models、previous_report/receipt 或 continuation=repair。脚本返回原 root；executor 从连续检查点中恢复当前 stage、明确选中的报告及有效计划。计划适配来源以检查点选中的 stage 为准。

恢复前核实旧 executor、implementer、reviewers 及命令结束。未确认停止时不派接替 writer。具体恢复位置和禁止重置的计数见 ticket-execution.md；代码失败在 executor 内推进 stage，controller 不自动新增额度；用户明确追加时按 recovery-blocked.md 交接给恢复的 executor。已完成 ticket 应复用整票交付并关闭，不再恢复实现。

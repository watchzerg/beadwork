# 合入后恢复

全部 direct children 已关闭时，先检查 parent 的 `integration-ready` comment（合入前写入）。只有记录包含完整 `REVIEWED_MAIN`、`REVIEWED_HEAD` SHA、最终验证通过的证据和 `PASS` review gate，且 `git merge-base --is-ancestor <REVIEWED_HEAD> main` 成功，才认定该批次已合入。尚存的 implementation branch 必须指向 `REVIEWED_HEAD`；尚存的 worktree 必须属于该 branch 且干净，否则停止。

已合入时继续 [集成与清理](../SKILL.md#4-集成与清理) 的收尾步骤：parent 未关闭则补全 completion comment 和关闭；parent 已关闭则使用原 merge checkpoint 清理。记录不足时不凭空 diff 推断 review 通过：未关闭 parent 按普通恢复路径执行；已关闭 parent 停止并报告缺失证据。

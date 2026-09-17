# 合入后恢复

全部 direct children 已关闭时，先检查 parent 的 `integration-ready` comment（SKILL.md 第 5 节在合入前写入）。只有记录包含完整 `REVIEWED_MAIN`、`REVIEWED_HEAD` SHA、最终验证通过的证据和 `PASS` review gate，且 `git merge-base --is-ancestor <REVIEWED_HEAD> main` 成功，才认定该批次已合入。尚存的 implementation branch 必须指向 `REVIEWED_HEAD`；尚存的 worktree 必须属于该 branch 且干净，否则停止。

已合入时跳过 SKILL.md 第 2–4 节及再次 merge：parent 未关闭则从 SKILL.md 第 5 节第 4 步补全 completion comment 和关闭；parent 已关闭则进入第 6 节核对并补全 Git/Beads 推送，再进入第 7 节清理。parent closed 或 worktree 已清理不代表远端已同步；推送失败或结果未知时按 controller-operations 的远端推送入口重试，用户明确限制仍生效。记录不足时不凭空 diff 推断 review 通过：未关闭 parent 按普通恢复路径执行；已关闭 parent 停止并报告缺失证据。

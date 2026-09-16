# 恢复批次

当 branch 或 worktree 已存在时，绝不重建或 reset 已有工作：

- branch 和 worktree 都存在：验证 worktree checkout 的正是 `implement/<parent-id>`，然后复用。
- branch 存在但 worktree 不存在：从已有 branch 用普通 `git worktree add` 重建固定路径，再用 `bd worktree info --json` 验证 Beads workspace。
- worktree 路径存在但不属于预期 branch：停止。
- parent 已由其他身份领取：停止。

恢复时允许唯一的 `in_progress` child 留有未提交源码；它属于该 ticket，由恢复 executor 处理。开始一个全新 ticket 前，implementation worktree 必须干净。

所有路径都执行 `just install`，失败时停止。然后按批次 comment 恢复：

- 已有冒烟通过的批次记录：parent 应为本次领取的 `in_progress`；复用记录继续，不在 ticket 中途态重跑基线冒烟。
- 尚无该记录：仅在 worktree 干净、没有本批次 child start comment 且没有 `in_progress` child 时，按初始化未完成处理。从当前 HEAD 重跑 SKILL.md 第 2 节第 6 步；通过后，parent 为 `open` 则执行 SKILL.md 第 2 节第 7 步，已由本次领取则跳过 claim，再补 SKILL.md 第 2 节第 8 步。
- 其他状态不一致或已有 ticket 工作却缺少基线证据：保留现场并停止。

已有 batch_initialize.py intent 的批次先核对原步骤记录与实时现场，并补查 `bd worktree info --json` / `bd where` 的共享 workspace。ready.json 不能替代这项核对或批次 comment；失败/不明步骤保留原件，按上述初始化未完成条件处理，不盲目重放 claim。

已有冒烟通过的批次在下一次 `claim` 前仍执行 `sync-main`；它自动恢复 `main-sync/` 下未完成的同步，不以 main 已在当前历史中替代验证。先确认旧同步命令已结束，再按 `controller-operations.md` 使用原同步输入恢复。存在 merge 冲突时保留现场并停止，解决并提交后恢复；当前票 `resume` 不进入同步。

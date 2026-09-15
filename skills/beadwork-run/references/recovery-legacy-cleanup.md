# 无 checkpoint 的历史清理

历史批次尚无脚本 checkpoint 时，沿用已有 integration-ready 证据人工核对相同条件：parent 已关闭、`REVIEWED_HEAD` 已在 main 历史中、尚存 branch 指向该 SHA、worktree 属于该 branch 且干净；再用 `git worktree remove` 和 `git branch -d` 清理，不使用 force，不为清理重建现场。

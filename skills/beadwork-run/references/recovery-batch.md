# 恢复批次

先确认旧 writer、命令与外部资源结束，保留 dirty 现场和已有证据。

- 初始化 intent 已建立但无 ready：使用 controller-operations.md 的原初始化入口恢复；不手工补做 claim/comment。未知命令先补实际收尾观察。
- 初始化已完成：读取绑定的 ready、批次 comment 与实时 Git/Beads 现场。branch/worktree 必须属于固定批次；parent 归属不符或记录缺失时停止。
- branch 存在但 worktree 缺失：核对原批次后，从原 branch 用普通 git worktree add 重建固定路径，再核对 Beads workspace；不重建 branch 或 reset。
- 唯一 in_progress child 的未提交源码由恢复 executor 处理；开始新票前 implementation 必须干净。

已有 ticket 工作的批次执行 just install 后继续原 ticket，不重跑初始化快速基线。下一次 claim 前仍调用 sync-main；未完成同步使用原输入恢复，不能以 main 已在历史中替代验证。当前票 resume 保留原 BASE，不同步 main。

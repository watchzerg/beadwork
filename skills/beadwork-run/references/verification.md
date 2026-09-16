# 验证采集

implementer/fixer 与新版 finalizer 的 `typecheck`、`test`、`final` 和 `gate-*` 通过以下入口执行；一次调用一个 recipe，参数保持独立。票据要求 `just final <gate>...` 时使用 `--recipe final -- <gate>...` 采集。`fmt` 和 controller 的 `install` 沿用原入口。

```bash
python3 <skill-dir>/scripts/run-verification.py --dispatch <dispatch.json> --recipe test -- <测试路径及参数...>
python3 <skill-dir>/scripts/run-verification.py --dispatch <dispatch.json> --recipe gate-unit
```

脚本在 dispatch.worktree 执行实际 `just` 命令，继承已准备好的环境，在本轮 `verification-*` 目录保存 started.json、完整 output.log 和完成后的 result.json。启动时 stderr 返回运行目录，结束时 stdout 返回命令、退出码、耗时、HEAD、dirty 状态和最多末尾 2048 字节/20 行日志。通常直接阅读摘要，需进一步诊断时搜索完整日志；不必重抄命令和结果。

| 脚本退出码 | 处理 |
| --- | --- |
| 0 | 命令退出 0，前后 HEAD/status 未发现变化；仍需核对相关测试被收集及实际覆盖。 |
| 1 | 命令正常非零退出，原始 exit_code 已保存。TDD 按 testing-tdd.md 判断是否为行为 red；其余按验证失败处理。 |
| 2 | 记录器错误或前后现场变化；保留证据并处理原因，不能当作有效 red 或通过。 |
| 3 | 中断；确认收尾与外部资源状态后才恢复，不能算正常验证完成。 |

运行时保持源码静止。HEAD/status 只是现场记录，不是内容指纹；dirty 运行属于当时工作区，不能称为纯 commit 上的验证。骨架差异和 red 复现方式继续按项目契约保存。脚本不判断 red、零匹配、覆盖范围，也不自动重试或推导 DONE。

用宿主长任务机制等待或取消。记录器收到取消后终止本次专属进程组，有限等待后必要时强杀；`process_group_gone` 只描述该进程组，不证明 Docker 容器、脱离进程组的任务等外部资源已清理。强杀记录器可能仅留下开始记录和日志；恢复前由 agent 确认旧任务结束，不根据旧 PID 自动操作。

报告交付按 `report-delivery.md` 自动汇总全部运行。缺少 result.json 的记录作为“结果未知”保留；返回 DONE 前必须在该运行的 `verification_notes` 写明实际收尾确认及后续验证，语义由 executor 核对。失败历史不自动阻止交付，也不会被旧成功覆盖。implementer 报告由组装器固定交付时的验证来源快照；历史报告只核验该快照，新交付必须包含当前全部运行。日志或来源损坏使组装失败时保留原文件，按共享交付契约返回部分阻塞报告并引用损坏证据。


## 最多三次就地 gate 修正

开发中的 TDD red 与定向验证沿用上述命令。实现提交后，完整交付 gates 增加 `--delivery`（放在 `--` 参数分隔符之前）；入口要求干净 HEAD，并在原始记录中区分交付候选与开发验证。

```bash
python3 <skill-dir>/scripts/run-verification.py --dispatch <writer-dispatch.json> --recipe gate-unit --delivery
python3 <skill-dir>/scripts/executor-operations.py begin-gate-repair --dispatch <writer-dispatch.json> --failure <失败运行目录/result.json>
```

writer 确认交付失败由代码导致后，在修改前调用上述入口申请修正，每逻辑阶段最多三次，全程由当前 writer 处理。脚本核对失败来源、正常非零退出、日志、候选和逻辑阶段，返回本次编号与授予时的剩余额度；同一申请幂等重试不重复计数，新申请必须来自当前候选。环境/工具阻塞不申请；脚本不从退出码推断代码根因。

当前 writer 集中修正，可运行必要的定向验证；提交后以 `--delivery` 重跑受影响的交付 gates。每次修正后的第一次重跑绑定该次候选 HEAD，其余交付 gates 必须使用同一 HEAD。该候选再有代码失败时，有余额则申请下一次修正；三次修正后仍失败即返回 `BLOCKED / code_failure`。额度由整个阶段共享，不按 recipe 或失败类型增加；环境修复可在同 HEAD 重跑。review 开始后不能申请修正。

机会属于整个逻辑阶段，dispatch 的 `gate_repair_root` 指向记录目录；同阶段恢复继承，新阶段重新获得机会。中断发生在修正开发期间可继续开发，发生在交付验证期间则恢复固定候选。finalizer stage 0 没有 writer，不享有机会；后续 fixer 使用相同入口。失败记录和成功重跑都保留；fixer 在已有 verification 字段引用这些记录，executor/finalizer 核对最终覆盖及失败处置，不以单次成功抹去其他失败。

最终阶段的运行快照、组合 final 参数覆盖、未知/损坏来源和 fixer 完整验收见 final-execution.md。finalizer 不获得 gate-fix 权限；stage 0 代码失败直接进入下一 stage。收尾说明仍不能由 process_group_gone 替代宿主和外部资源观察。

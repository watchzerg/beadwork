# 验证采集

implementer/fixer 使用以下入口采集 `test`、`gate-core` 和 `gate-full`，一次调用一个 recipe；只有 `test` 接受定向参数。单票固定交付检查为 `gate-core`，最终交付为 `gate-full`，均须使用采集器的 `--delivery`；`--delivery` 属于采集器，不传给 just。finalizer 只采集带 `--delivery` 的无参数 `gate-full`。其他开发操作按项目规则执行并保留必要证据，controller 的 `install` 使用初始化/同步入口。

```bash
python3 <skill-dir>/scripts/beadwork.py run-verification --dispatch <dispatch.json> --recipe test -- <测试路径及参数...>
python3 <skill-dir>/scripts/beadwork.py run-verification --dispatch <dispatch.json> --recipe gate-core
```

脚本在 dispatch.worktree 执行实际 `just` 命令，继承已准备好的环境，在本轮 `verification-*` 目录保存 started.json、完整 output.log 和完成后的 result.json。started.json 的 `delivery` 字段记录本次是否使用 `--delivery`；最终验收只接受 `delivery: true` 的完整运行，开发验证成功不能替代交付验证。启动时 stderr 返回运行目录，结束时 stdout 返回命令、退出码、耗时、HEAD、dirty 状态和最多末尾 2048 字节/20 行日志。通常直接阅读摘要，需进一步诊断时搜索完整日志；不必重抄命令和结果。

| 脚本退出码 | 处理 |
| --- | --- |
| 0 | 命令退出 0，前后 HEAD/status 未发现变化；仍需核对相关测试被收集及实际覆盖。 |
| 1 | 命令正常非零退出，原始 exit_code 已保存。TDD 按 testing-tdd.md 判断是否为行为 red；其余按验证失败处理。 |
| 2 | 记录器错误或前后现场变化；保留证据并处理原因，不能当作有效 red 或通过。 |
| 3 | 中断；确认收尾与外部资源状态后才恢复，不能算正常验证完成。 |

运行时保持源码静止。HEAD/status 只是现场记录，不是内容指纹；dirty 运行属于当时工作区，不能称为纯 commit 上的验证。骨架差异和 red 复现方式继续按项目契约保存。脚本不判断 red、零匹配、覆盖范围，也不自动重试或推导 DONE。

用宿主长任务机制等待或取消。记录器收到取消后终止本次专属进程组，有限等待后必要时强杀；`process_group_gone` 只描述该进程组，不证明 Docker 容器、脱离进程组的任务等外部资源已清理。强杀记录器可能仅留下开始记录和日志；恢复前由 agent 确认旧任务结束，不根据旧 PID 自动操作。

报告交付按 `report-delivery.md` 自动汇总全部运行。缺少 result.json 的记录作为“结果未知”保留；返回 DONE 前必须在该运行的 `verification_notes` 写明实际收尾确认及后续验证，语义由 executor 核对。失败历史不自动阻止交付，也不会被旧成功覆盖。implementer 报告由组装器固定交付时的验证来源快照；历史报告只核验该快照，新交付必须包含当前全部运行。每条快照固定 `directory`、`started` 和 `result`：目录为规范绝对路径，文件为内容绑定，采集时缺失的文件为 `null`；不读取旧快照格式。缺失或截断 started、日志损坏等情况保留目录与已有绑定并生成 `verification_issues`；只能返回部分 `BLOCKED / blocked|interrupted`，不能支持成功、review 或 code_failure 推进。


## 最多三次就地 gate 修正

开发中的 TDD red 与定向验证使用 `test`。实现提交后，单票 `gate-core` 或最终 `gate-full` 增加 `--delivery`（放在 `--` 参数分隔符之前）；入口要求干净 HEAD，并区分交付候选与开发验证。每票的行为覆盖由 Test plan、实测证据和 executor/reviewer 核对，不能用 core 通过替代。

```bash
python3 <skill-dir>/scripts/beadwork.py run-verification --dispatch <writer-dispatch.json> --recipe gate-core --delivery
python3 <skill-dir>/scripts/beadwork.py executor begin-gate-repair --dispatch <writer-dispatch.json> --failure <失败运行目录/result.json>
```

writer 确认交付失败由代码导致后，在修改前调用上述入口申请修正，每逻辑阶段最多三次，全程由当前 writer 处理。脚本核对失败来源、正常非零退出、日志、候选和逻辑阶段，返回本次编号与授予时的剩余额度；同一申请幂等重试不重复计数，新申请必须来自当前候选。环境/工具阻塞不申请；脚本不从退出码推断代码根因。

如果 writer 已经提交修正才发现遗漏了 `begin-gate-repair`，不要覆盖 repair/candidate 记录、重置分支或把当前 HEAD 冒充旧候选。停止 writer，将阶段按 `blocked` 完整交付；controller 解除流程阻塞后，executor 使用 `ticket-stage` 的 `continuation: recover` 和具体 `recovery_reason`。已有 repair 候选时该入口只接受其干净后继；首次修正尚无候选时另传修正前原始 delivery gate 失败 `result.json` 的绝对路径作为 `recovery_failure`。脚本追加恢复记录，然后在下一 stage 重新执行完整交付 gates 和双轴 review。

当前 writer 集中修正，运行必要的定向验证；提交后以 `--delivery` 重跑本阶段交付入口（单票 `gate-core`，最终 `gate-full`）。重跑绑定修正后的干净候选 HEAD；该候选仍有代码失败时，有余额则申请下一次修正，三次修正后仍失败即返回 `BLOCKED / code_failure`。额度由整个阶段共享，环境修复可在同 HEAD 重跑；review 开始后不能申请修正。

机会属于整个逻辑阶段，dispatch 的 `gate_repair_root` 指向记录目录；同阶段恢复继承，新阶段重新获得机会。中断发生在修正开发期间可继续开发，发生在交付验证期间则恢复固定候选。finalizer stage 0 没有 writer，不享有机会；后续 fixer 使用相同入口。失败记录和成功重跑都保留；fixer 在已有 verification 字段引用这些记录，executor/finalizer 核对最终覆盖及失败处置，不以单次成功抹去其他失败。

最终阶段的运行快照、单次 `gate-full`、未知/损坏来源和 fixer 完整验收见 final-execution.md。finalizer 不获得 gate-fix 权限；stage 0 代码失败直接进入下一 stage。收尾说明仍不能由 process_group_gone 替代宿主和外部资源观察。

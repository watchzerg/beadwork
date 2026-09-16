# 单票执行协议

controller 创建并交接 `ticket_scope: root` 的 executor dispatch。executor 使用以下入口管理 stage；implementer 使用独立 `role: implementer` dispatch。root、stage、implementer 的报告路径不能互换，controller 只关闭已通过整票验收的 ticket。

## 阶段准备与恢复

```bash
python3 <skill-dir>/scripts/executor-operations.py ticket-stage --dispatch <root-dispatch.json> --input <facts.json>
```

首次 facts 为 `{}`。返回 `stage`、`stage_dispatch`、`implementer_dispatch`、`models`、`prior_implementer`、`selected_stage`、`selected_review`、`review_round`、`review_started`、`required_boundary_gates` 和 `gate_sources`。executor 读取 stage dispatch；向 implementer 交接 implementer dispatch，并按 `models.implementer` 派发。两轴模型分别来自 `models.standards/spec`。

- `continuation: resume`：恢复当前阶段；无阶段时建立 stage 0。恢复返回原 dispatch、已选中的交付来源和 review 状态，不重新分配额度。
- `continuation: repair`：前阶段必须有已验收的 `code_failure`，且旧任务已结束；建立下一阶段，新 implementer，最多到 stage 3。
- 新阶段可提供 `model_overrides` 和非空 `model_override_reason`，角色只允许 implementer/standards/spec；覆盖只能提高档位，后续不降档。已有 stage 恢复沿用模型。

`base_commit` 始终为整票开工 BASE；`stage_base` 是当前阶段起始 HEAD，仅用于阶段实现归属。双轴 review 始终覆盖原 BASE 到当前 HEAD，不缩为 fix diff。新阶段继承已有 commits 和未完成现场，不 reset 或重新实现正确部分。

root 目录的 `checkpoint-NNNNNN.json` 保存 hash 绑定的连续检查点，关联当前 stage、明确选中的 implementer、完整 review collection 和阶段报告。脚本只接受连续且来源一致的链路，不按目录时间选择报告。每个检查点独占创建，不覆盖已有记录；同票只能有一个 executor 更新检查点。

恢复前由 executor 核实旧 writer、reviewer 和命令是否结束。`review_started: true` 时复用原 stage 的 round 和轴 dispatch，只继续缺失的审查或更正；不能重派 writer。已有 implementer `DONE` 且未开始 review 时直接验收并开始 review。已有完整阶段报告时按 outcome 交付、修复或恢复，不重复实现。

## implementer 交付

首次执行前，implementer 读取 dispatch 指向的 report/receipt schema。输入事实、规则/spec、必要 gate 范围和恢复来源由 executor 显式交接。`inspect`/`check-layer` 的用法见 `executor-operations.md`；验证记录和三次修复见 `verification.md`。

```bash
python3 <skill-dir>/scripts/executor-operations.py implementer-assemble --dispatch <implementer-dispatch.json> --draft <draft.json> --output <report.json>
python3 <skill-dir>/scripts/executor-operations.py implementer-check --dispatch <implementer-dispatch.json> --report <report.json>
```

draft 必填：

- `status`、`outcome`：见 `agents/implementer.md`；passed 仅表示实现/gates 通过。
- `test_plan`：未知时 null，否则只填写 `decision_source` 和 `red_evidence`；mode/seams 从绑定的执行计划读取。
- `acceptance`：criterion/evidence 映射。
- `verification`：人工验证场景的 command/result；已采集 just 命令不用重复填，通常为 `[]`。
- `verification_notes`：运行目录绝对路径到非空说明的映射，无补充时 `{}`。填写有效 red 判断、新增 gate 原因或未完成记录的实际收尾等语义事实。
- `required_boundary_gates`：原声明及实际补充的 gate 下限。implementer 报告一经验收，新增 gate 与报告来源写入 ticket checkpoint；同 stage 恢复、计划适配、后续 stage 和 review 均沿用累计集合。组装器自动保留累计范围，但当前 HEAD 缺少对应成功运行时仍拒绝完成。
- `requested_context`、`blockers`、`concerns`：保留未完成任务、dirty 文件、剩余工作与失败来源。
- `stopped_tasks`：实际停止事实，布尔值；脚本不代替宿主确认。

组装器从 Git 生成 ticket BASE、stage_base、当前 HEAD 和整票 commits，收集当前及适配前 implementer 的全部验证日志。成功要求 gate-unit 和必要 boundary gates 在同一干净交付 HEAD 通过；TDD red 和直接验证的语义仍由 executor 验收。code_failure 要求三次修复已用尽，且存在第三次修复候选的正常非零交付结果。原始失败记录不会被成功重跑删除。组装器同时固定该报告交付时的 verification_sources（started/result 的 hash 绑定）；同 stage 后续新增运行不会改变已交付报告的验证历史，新报告仍采集全部当前来源。来源缺失或损坏时，组装器在 `verification_issues` 保存原绑定与实际错误；这种报告只能 `BLOCKED / blocked|interrupted`，不能进入 review、声明成功或作为 code_failure 推进。

stdout 为短回执；executor 确认 implementer 及命令结束，保存到该 implementer 目录下的新 receipt 文件，然后执行：

```bash
python3 <skill-dir>/scripts/executor-operations.py implementer-accept --dispatch <stage-dispatch.json> --report <implementer-report.json> --receipt <implementer-receipt.json> --closure <closure-source.json>
```

该入口重新校验身份、Git 和验证来源，并将选择追加到 root 检查点。重复验收同一来源幂等。实现的 passed/code_failure 一经验收，不能改报中断来继续旧 writer；已封存阶段不再接受新的实现来源，阶段/审查报告更正仍可在同 HEAD 完成。验收失败按证据/报告问题处理，不消耗 stage。合法部分报告也保留来源，但只有实现 DONE 才可准备 review。

## 阶段报告与整票交付

实现通过后按 `review.md` 准备并验收本阶段唯一的一轮双轴 review。首次 prepare 在 checkpoint 预留 round 后写入材料；准备命令在 round.json 写出前失败时，确认没有已派发 reviewer 后使用 `review-prepare --resume` 补齐原目录。已有完整 round 时继续原 round 或更正，不能另开一轮；review 开始后不恢复 writer。

`review-collect` 成功时将 collection 的 path/sha256 写入检查点的 `selected_review`，即使尚未组装阶段报告，恢复也保留该选择。collection 已写出但检查点尚未追加时中断，保留原件，用原 round 和明确的 selection 输入重新 collect 到新文件；不按目录时间选择来源。缺轴或校验失败不更新选择。

同 HEAD 的审查更正必须来自同一 round；选中新 collection 后清除当前 `selected_stage`，重新组装前不能整票交付或推进 stage。原阶段报告和检查点保留。进入下一 stage 后，旧 stage 不再接受新的 collection 选择。

```bash
python3 <skill-dir>/scripts/executor-operations.py ticket-assemble --dispatch <stage-dispatch.json> --draft <stage-draft.json> --output <stage-report.json> [--review <collection.json> ...]
```

stage draft 必填 `status`、`outcome`、`test_plan`、`acceptance`、`verification`、`requested_context`、`blockers`、`concerns` 和 `stopped_tasks`。test_plan 同上；verification 只填 executor 额外核对的人工场景，implementer 和前阶段日志由组装器自动纳入。

`--review` 必须依次提供 dispatch.prior_reviews 和检查点的 selected_review（非 null 时）；遗漏或使用更正前的 collection 均被拒绝。缺轴或未完成轮次保留在 concerns，不能伪造完整 review。组装器保留两轴原始报告、前阶段与 implementer 的 dispatch/report/receipt hash 绑定；自动生成旁边的 `<stage-report-stem>-receipt.json` 并追加阶段选择检查点。stdout 同样是短回执。

- gates 通过且两轴 PASS：DONE/passed。
- implementer 三次 gate-fix 后仍失败，或完整双轴代码类 blocking：BLOCKED/code_failure；stage < 3 时 executor 内部 repair。
- 环境/spec/seam/证据阻塞：BLOCKED/blocked。
- 未完成阶段的中断：BLOCKED/interrupted。已完成 blocking review 不能标作中断重置阶段。

完成整票或必须交还 controller 时：

```bash
python3 <skill-dir>/scripts/executor-operations.py ticket-deliver --dispatch <root-dispatch.json> --output <root-report.json>
```

该入口将明确选中的阶段报告原样复制到 root 目录，重新执行完整验收并返回 root 短回执；不重跑 gates 或 review。stage 0..2 的 code_failure 不允许交付给 controller 作为最终代码失败。controller 使用 root dispatch 和这份报告/回执运行 `accept`；成功后生成 completion 并关闭 ticket。

所有输出使用新文件名。更正只能补事实，不改源码、不增加阶段或 review 次数；原件保留。验证与完整双轴 review 未通过时不能返回 ticket DONE。

必要派发输入来自已验收 preflight：linked_spec 和 required_boundary_gates 必须显式存在（无额外 gate 时 []），plan_source/environment_evidence 保留核实来源。收尾来源及 context-add 的用法见 report-delivery.md；恢复返回的 context_sources 必须交接给当前 implementer。

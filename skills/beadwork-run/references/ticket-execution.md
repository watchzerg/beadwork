# 单票执行

controller 交接 root dispatch；executor 用 stage dispatch 协调当前阶段，implementer 使用独立 writer dispatch。整票 BASE 固定为开工 base_commit，stage_base 记录当前阶段起始 HEAD；review 覆盖原 BASE 到候选 HEAD。

## 正常阶段循环

```bash
python3 <skill-dir>/scripts/beadwork.py executor ticket-stage --dispatch <root-dispatch.json> --input <facts.json>
```

首次 facts 为 `{}`。后续代码修复使用 `{"continuation":"repair"}`。返回 stage_dispatch、implementer_dispatch、models、active_stage_context_source 和已选交付/review 来源。派发使用返回的模型配置与独立上下文。

1. 派发全新 implementer，交接 writer dispatch、项目规则、需求来源和实际进度通信目标。实现与交付见 [writer-delivery.md](writer-delivery.md) 的 implementer 部分。
2. 确认 writer 与命令结束，保存回执；核对 acceptance、Test plan、失败处置与候选 gate-core，执行 implementer-accept。
3. 实现通过后，按 [review.md](review.md) 派发一轮并行双轴审查。候选保持冻结。
4. 完整 review 按 repair_route 分流；仅文档阻塞先完成 [文档收尾](document-closeout.md)，不消耗新 stage 或重跑代码 gate。无阻塞或收尾通过才可 passed；收尾失败为 blocked，确认需要代码修复为 code_failure。
5. 填写本阶段 draft_schema_path 所需语义判断，组装阶段报告：

```bash
python3 <skill-dir>/scripts/beadwork.py executor ticket-assemble --dispatch <stage-dispatch.json> --draft <stage-draft.json> --output <stage-report.json>
```

组装器使用 checkpoint 选中的实现与 review，自动生成完整来源、验证历史、receipt 和阶段选择。stage draft 的 verification 仅填写额外核对的人工场景。

| outcome | 下一步 |
| --- | --- |
| passed | 整票交付。 |
| code_failure | 未到授权上限时 repair，派发新 implementer；用尽后交付阻塞。 |
| blocked | 保存具体缺项，交回 controller；解除后恢复原阶段。 |
| interrupted | 保存现场与剩余工作，恢复原阶段。 |

代码失败依据是 implementer 用尽 gate-fix 后的失败，或完整双轴中的代码类 blocking findings。未完成审查属于 blocked；smells 留作非阻塞证据。每 stage 至多一轮完整 review，review 后的代码修复进入下一 stage。

## 当前失败上下文

stage 0 的 active_stage_context_source 为 null；后续 stage 提供内容绑定的当前 blockers、findings 和前阶段验证视图。implementer 从该视图定点追查原始证据，完整历史由脚本保留。相同 stage 恢复复用原绑定与 context_sources。

## 整票交付

```bash
python3 <skill-dir>/scripts/beadwork.py executor ticket-deliver --dispatch <root-dispatch.json> --output <root-report.json>
```

交付 checkpoint 明确选中的阶段报告，执行完整自检并返回 root 短回执。DONE 需要 acceptance、必要验证与最后双轴 review 覆盖代码候选；有文档收尾时，由绑定的验收记录覆盖后续文档 HEAD，现场干净且任务已结束。未到授权上限的 code_failure 继续内部修复。controller 验收 root 交付后记录 completion 并关闭 ticket。

## 条件入口

- 原 BASE 已满足行为或验证方式需要适配：[baseline-adaptation.md](baseline-adaptation.md)。
- 同阶段接续、接替或漏登记 gate 修正：[recovery-ticket.md](recovery-ticket.md)。
- complex_ticket、模型升档或用户授权追加：[model-policy.md](model-policy.md)。
- review 准备中断、collection 更正或部分报告：[recovery-report.md](recovery-report.md)。

checkpoint 保存连续且内容绑定的明确选择。恢复使用该选择；同票仅一个 executor 更新检查点。文件报告与更正规则见 [report-delivery.md](report-delivery.md)。

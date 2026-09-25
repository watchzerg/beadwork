# 最终阶段执行

controller 管 root 与集成，finalizer 管 attempt 的阶段循环。stage 0 派 document-syncer；stage 1..5 派 fixer。源码与验证串行，review 使用固定 reviewed_main 到候选 HEAD 的范围。

## 正常阶段循环

```bash
python3 <skill-dir>/scripts/beadwork.py executor final-stage --dispatch <root-dispatch.json> --input <facts.json>
```

首次 facts 为 `{}`，代码修复使用 `{"continuation":"repair"}`。prepare 返回 stage、模型、writer dispatch 和已选来源。

1. stage 0 派 document-syncer，按 [writer-delivery.md](writer-delivery.md) 验收文档范围、必要覆盖和实际收尾。updated 与有依据的 no_change_needed 均可继续；incomplete 交付阻塞。
2. stage 0 由 finalizer 按 [verification.md](verification.md) 采集带 `--delivery` 的无参数 gate-full；修复阶段由 fixer 完成该验证，finalizer 验收处置与覆盖。
3. 完整验证通过后按 [review.md](review.md) 派发两轴。BASE=HEAD 时按 [baseline-adaptation.md](baseline-adaptation.md) 提供 parent acceptance 证据，执行 existing_behavior 审查。
4. 填写当前 draft_schema_path 的语义判断并组装：

```bash
python3 <skill-dir>/scripts/beadwork.py executor final-assemble --dispatch <stage-dispatch.json> --draft <draft.json> --output <stage-report.json>
```

组装器读取 checkpoint 中的文档、fixer、review 与历史来源，生成完整报告、receipt 和 selected_stage。文档提交与 fixer 提交分别归属 document_sources 和 fix_sources。

## 最终验证判断

项目 justfile 及调用文件定义完整 gate-full。finalizer 核对它与 parent acceptance、各票行为证据的对应关系，尤其检查测试或 gate 变更是否削减覆盖。

成功需要同一干净 HEAD 的完整 gate-full、正常退出与运行来源绑定。相同候选的有效结果复用；后续失败或无效验证使旧成功失效，修复后从完整入口重跑。未知运行填写实际收尾说明；来源损坏仅支持 blocked/interrupted 交付。

## 当前修复上下文

fixer 读取 active_stage_context_source：当前 blockers、最近完整 review 的 blocking findings、此后各阶段处置、前一阶段验证视图及文档来源。新的完整 review 更新 findings；中间阶段 gate 失败时继续保留。累计历史由 stage dispatch 和原报告绑定保存，fixer 按具体疑问定点追查。恢复原 stage 复用同一绑定。

writer 的交付入口见 [writer-delivery.md](writer-delivery.md)。fixer DONE 后，finalizer 可补充验证，再进入 review；后续文档维护由 fixer 负责。补充验证在当前干净 HEAD 正常退出但发现代码失败时，组装 code_failure 并进入下一修复阶段，不重新打开已完成的 fixer；环境失败或未知运行仍按 blocked/interrupted 处理。

## 推进与 root 交付

- READY_TO_MERGE：文档覆盖完成，完整 gate-full 与最后两轴 PASS 对应交付 HEAD；现场干净、任务结束、无 blockers/remaining_work。
- code_failure：stage 0 实测代码失败，修复阶段 fixer 用尽 gate-fix 后失败，fixer DONE 后 finalizer 补充验证确认代码失败，或完整双轴代码类 blocking。stage < 5 时继续 repair，stage 5 交付阻塞。
- blocked/interrupted：保存具体原因、现场和恢复来源，交付 controller。非代码阻塞在解除后恢复原阶段。

```bash
python3 <skill-dir>/scripts/beadwork.py executor final-deliver --dispatch <root-dispatch.json> --output <root-report.json>
```

该入口交付 checkpoint 选中的报告并自检，包含合法 BLOCKED。finalizer 的终态回复使用生成的 root 短回执；controller 验收后决定集成。

## 条件入口

- attempt、writer 或验证中断：[recovery-finalizer.md](recovery-finalizer.md)。
- review 半成品、报告更正：[recovery-report.md](recovery-report.md)。
- 模型升档：[model-policy.md](model-policy.md)。

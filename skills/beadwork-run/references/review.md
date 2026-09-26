# 双轴审查

executor/finalizer 在验证通过且 writer、命令结束后，直接派发 Standards 和 Spec 两名独立并行 reviewer。方法见 agents/reviewer.md，交付见 [report-delivery.md](report-delivery.md)。

## 准备与派发

```bash
python3 <skill-dir>/scripts/beadwork.py executor review-prepare --dispatch <stage-dispatch.json>
```

ticket 先完成 implementer-accept；final 阶段先完成文档/fixer 验收与完整验证。脚本固定真实 branch、BASE/HEAD、ancestry 和干净候选，预留本阶段唯一 round。BASE 为 ticket 原 base_commit 或最终 reviewed_main。

返回 round_path、axes、reviewer_launch_context 和 selection_draft_path。每轴 dispatch 已包含身份、diff/commits、规则与需求指针、required_reads、schema、自检命令、writer_source、verification_view_source、stage_source、plan_source、context_sources 和本轴 prior_axis_source。派发者只补充来源无法表达的范围与通信目标，使用 `fork_turns: "none"`。

单票以当前 child acceptance 为范围，parent/spec 提供约束；最终审查覆盖整个批次。reviewer 从 verification view 的 selected_sources 开始，按具体疑问追查完整来源。

BASE=HEAD 时按 [baseline-adaptation.md](baseline-adaptation.md) 提供 `--evidence <acceptance.json>`，执行 existing_behavior 审查。审查期间候选冻结。

## 收集

两轴停止后保存原始回执。将生成的 selection-draft.json 复制到新的 selection.json，填写每轴实际 observation；更正报告时更新该轴 report/receipt 路径。模板里的 stopped=false 表示待观察。

```bash
python3 <skill-dir>/scripts/beadwork.py executor review-collect --round <round.json> --input <selection.json> --output <collection.json>
```

每轴输入为 report、receipt、observation；已有收尾来源时也可使用 report、receipt、closure。collect 自动保存观察来源，校验身份、回执、停止状态和真实候选，保存原始 pair、派生 gate 与 bindings，并更新 checkpoint。

- 两轴均 COMPLETED：blocking findings 决定原始 gate；脚本汇总 `repair_route`。`none` 正常完成，`code` 进入下一修复 stage 并处理代码与关联文档，`docs` 进入 [文档收尾](document-closeout.md)。仅统计 blocking findings，smells 保留且不影响路由。
- 任一轴未完成、校验失败或现场变化：保存已有证据，按 blocked 处理。

派发者核对 findings 与原始证据的语义一致性。分类疑问交原 reviewer 核实并更正；原始 findings 保持其轴与分类。

## 复审与更正

文档收尾开始后原 collection 保持冻结，不再派 reviewer 或更正其 findings。文档收尾的验收单独记录，原 BLOCKED 不改写为 PASS。

代码修复使用新 stage、新 HEAD 和原 BASE，检查原 findings 根因、修复直接影响的路径与完整范围的新问题。外部状态修复可以按 existing_behavior 规则保持同 HEAD；需当前状态的可核查证据。

同 HEAD 报告更正沿用原 round 与模型；collect 后旧 selected_stage 失效，重新 assemble 才能推进。已进入后续 stage 的旧轮次保持封存。review 准备中断或 collection 半成品按 [recovery-report.md](recovery-report.md) 处理。

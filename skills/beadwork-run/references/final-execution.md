# 最终阶段交接

新派发使用 `workflow_contract_version: 5`。controller 管 root 与集成，finalizer 管 attempt 检查点；fixer 是修复阶段唯一 writer。检查点只追加，记录当前 stage、已验收 fixer、唯一 round、selected_review、selected_stage、累计 gates 和来源。

## 准备与恢复

```bash
python3 <skill-dir>/scripts/beadwork.py executor final-stage --dispatch <root-dispatch.json> --input <facts.json>
```

首次 facts 为 `{}`；恢复使用 `continuation: resume`，推进使用 `continuation: repair`。已有检查点时脚本使用明确选择；显式 previous_stage 必须匹配当前阶段。repair 只接受已选 code_failure，最多 stage 5。同阶段恢复返回原 dispatch、selected_fixer、review_round、selected_review、selected_stage 和 context_sources，不重新分配额度。

fixer DONE 已验收或 review 已开始时，不再派 writer。恢复前先由派发者确认旧 agent 和命令结束；未知停止状态不会授予接替 writer。gate-fix 继续使用 verification.md 的三次额度。

模型与矩阵以 `../scripts/workflow_policy.py` 为准。stage 0 无 fixer；stage 1..5 的 fixer 默认为 Terra-medium 两次、Terra-high 两次、Sol-medium 一次。新阶段可用 `model_overrides` 覆盖 fixer/standards/spec，并提供 `model_override_reason`；只允许三档内升档，后续继承且不降档，同阶段恢复沿用原模型。

## 验证与补充边界

stage 0 由 finalizer 用 `beadwork.py run-verification` 采集一次无参数 `gate-full`，交付验证加 `--delivery`。stage 1..5 由 fixer 采集同一入口；fixer 已验收停止后 finalizer 可以补验证，仍不修改源码。review 开始后冻结验证候选。

最终成功依据 started/result/output.log 的绑定、正常退出码、相同干净 HEAD 和进程组结束事实。相同 gate 在交付 HEAD 取最新结果，较早成功不能覆盖较晚失败。未知结果需要实际收尾说明；日志损坏时可以组装 BLOCKED/blocked 或 interrupted，组装器自动保留 verification_issues，不能据此通过或推进代码修复。

fixer 的开发定向验证和历史辅助 gate 全部保留在运行快照中，包括 dirty 工作区中的正常 red/green；它们不替代最终交付。成功与 gate-fix 额度耗尽只由绑定 `gate-plan` 的完整 `gate-full` 支撑；交付 HEAD 上完整成功之后出现失败或无效验证时，仍须重跑 `gate-full`。

`gate-full` 的覆盖由同一 HEAD 上绑定的 `gate-plan` 定义；不得从命令文字推导子 gate、传筛选参数或拼接不同运行。一次完整失败后必须从 `gate-full` 入口重新执行；同一有效候选可复用已绑定的完整成功，但更晚的相关失败会使旧成功失效。boundary gates 继续作为需求与影响范围的来源义务保留，不把全量成功扩大解释为未声明的票据通过范围。

新增边界一经确认，立即持久化，不等待成功报告：

```bash
python3 <skill-dir>/scripts/beadwork.py executor final-gates --dispatch <stage-dispatch.json> --input <gates.json>
```

gates.json 为 `{names: ["gate-example"], sources: [{gate: "gate-example", source: "新增原因及依据"}]}`。累计下限继承到下一 stage/fixer、最终报告与接替者；同 attempt 不自动删减。final-gates 由 finalizer 调用，fixer 通过消息提交新增边界；fixer 报告验收也会合并实际边界。

## fixer 交付

```bash
python3 <skill-dir>/scripts/beadwork.py executor fixer-assemble --dispatch <fixer-dispatch.json> --draft <draft.json> --output <report.json>
python3 <skill-dir>/scripts/beadwork.py executor fixer-check --dispatch <fixer-dispatch.json> --report <report.json>
python3 <skill-dir>/scripts/beadwork.py executor fixer-accept --dispatch <stage-dispatch.json> --report <report.json> --receipt <receipt.json> --closure <closure-source.json>
```

fixer 读取 dispatch.draft_schema_path，只填写处置、补充边界及原因、verification_notes、实际收尾和剩余工作。身份、HEAD、commits、验证运行及来源由脚本生成；stdout 为短回执，保存原件。

DONE 需当前 HEAD 的一次完整 `gate-full`；code_failure 需三次 gate-fix 已用尽及第三次候选正常非零交付结果。blocked/interrupted 可保留部分证据，不伪造成功。直接派发者先按 report-delivery.md 记录收尾，再 accept；验收会保存 fixer 选择。成功或代码失败终态不能改报中断继续写入。

## review 与阶段报告

按 review.md 派两轴；review-prepare 校验验证来源及 fixer 选择，并固定唯一 round。只剩半成品准备时使用 `review-prepare --resume`；已完成 round 从 final-stage 返回值恢复。review-collect 同时保存 selected_review。同 round 更正使原 selected_stage 失效，重新组装后才可交付或推进。

```bash
python3 <skill-dir>/scripts/beadwork.py executor final-assemble --dispatch <stage-dispatch.json> --draft <draft.json> --output <stage-report.json>
```

finalizer 使用阶段 draft_schema_path 填写语义判断。组装器从 checkpoint 读取已选 fixer、review 和历史，生成运行记录、完整报告、receipt 并追加 selected_stage；不接受手工来源数组。

stage 0 的实测代码失败或完整代码类 blocking review 允许推进；修复阶段无完整 blocking review 时，必须由本阶段 fixer 的 code_failure 支撑推进。非代码阻塞停留原 stage。

## root 交付

```bash
python3 <skill-dir>/scripts/beadwork.py executor final-deliver --dispatch <root-dispatch.json> --output <root-report.json>
```

入口只交付检查点选中的阶段报告：保持原字节，生成同目录 `<root-report-stem>-receipt.json` 并重新完整验收。不运行 gates、不派 review；stage 0..4 的 code_failure 先继续内部修复，stage 5 用尽才交还 controller。

交付中断后保留已有文件，换新文件名重试；不得覆盖或手改 receipt。controller 记录 finalizer 的收尾来源后执行 accept。成功需当前 HEAD 和完整来源一致，BLOCKED 保留恢复指针，未知停止状态不能授权后续写入或集成。

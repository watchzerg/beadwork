# 子 agent 报告交付

controller、executor 和 finalizer 派发子 agent 前读取本文件；每个接收方验收自己的直接子 agent。所有角色使用“文件报告 + 短回执 + SHA-256 绑定”，报告内容与成功状态按角色定义。进度通信不受短回执限制。

## 派发和验收

1. 使用对应 prepare、ticket-stage、final-stage 或 review-prepare 已生成的 dispatch、schema 和报告路径，交接绝对路径、自检入口及本轮事实。身份取自派发时固定的 ticket/axis/BASE/HEAD，不能从返回报告反推；不手工重建这些产物。
2. 使用 assembler 的角色只读取 `draft_schema_path` 并填写语义 draft；Git 身份、commits、验证及 review 来源由脚本生成。reviewer 直接填写 AxisReport，读取 `report_schema_path`。root 的 deliver 直接交付已选阶段报告，无需读取阶段输入 schema。完整输出 schema 由脚本校验，结构诊断时才读取。成功 assemble/check 的 stdout 原样作为最终回执，不手工转换字段；合法 BLOCKED 也可正常交付，校验失败非零退出且不产生回执。派发者仅为设置 outputSchema 读取 receipt schema，支持 strict 时启用。所需输入契约缺失时报告阻塞，不猜测字段。
3. 派发者等待 agent 和其启动的命令、子任务结束，原样保存 `receipt.json`，读取自己指定的报告并执行带回执的完整校验。文件出现、进度消息和回执到达均不替代结束确认；无法确认 writer 停止时保留现场，不派接替 writer、不合入或清理。
4. 对应完整校验入口成功才通过机械检查；非零退出、缺文件、结构或路径/status/hash 不一致均按调用方停止规则处理。成功回执不替代真实日志、Git 现场、需求与 finding 的语义核对，也不证明任务已经结束。
5. 已交付报告、回执及校验结果原样保留。更正写新的 `report-N.json`/`receipt-N.json`，由派发者明确选中并重新完整验收；文件必须位于本次证据目录内，不按回执改选文件。更正只补事实，不改代码、不增加修复/review 次数；不新增自动更正循环。

SHA-256 只绑定交付文件的字节，不证明报告内容正确。聚合时继续原样嵌入已验收的 AxisReport，保留原文件、回执与校验输出，不以短回执或摘要替代原始 findings。

draft 字段由 draft_contracts 统一生成和校验；完整报告与回执字段由 verifier 的 `--schema` / `--receipt-schema` 生成。本文件定义交付行为和判定规则。历史报告、回执和 dispatch 保持原样，新派发使用当前命令，不执行历史记录中的旧命令。

## 等待与进度

有可用的派发者通信目标时，子 agent 在 commit、长 gate 开始/结束和 reviewer 派发时直接发送简短进度；自身 commentary 不视为派发者已收到。仅因无消息或等待超时，不中断 agent。默认连续 20 分钟无已确认进展后排查；中断前刷新 Git HEAD/工作区、验证记录和后代任务状态，发现新进展或命令/reviewer 仍在正常运行则继续等待。达到阈值本身不是中断依据；用户要求停止或已确认失控写入等需立即制止的情况不受此等待下限限制。

## 正常交付入口

| 角色 | 交付与直接派发者验收 |
| --- | --- |
| preflight | agents/preflight.md 的 collect/assemble → controller accept |
| implementer / executor | ticket-execution.md 的 implementer-assemble/check → implementer-accept → review → ticket-assemble → ticket-deliver → controller accept |
| document-syncer | final-execution.md 的 document-assemble/check → document-accept；随后由 finalizer 验证和 review |
| fixer / finalizer | final-execution.md 的 fixer-assemble/check → fixer-accept → review → final-assemble → final-deliver → controller accept |
| reviewer | dispatch.self_check_argv → review.md 的 review-collect |

子角色只返回自己角色的完成状态，writer DONE 不表示 review 或整票通过。正常 BLOCKED 也走对应组装与交付入口；源码写入前遇到能力/上下文阻塞，能建立阶段时仍先建立检查点并组装部分报告。缺 dispatch、采集器半成品或需要底层结构自检时读取 [recovery-report.md](recovery-report.md)，不伪造成功来源。各角色精确字段读取生成的 schema。

## 派发者收尾确认

新 ticket、最终阶段 document-syncer/fixer/reviewer 和最终 root 交付，直接派发者先确认任务及其命令结束，再记录观察：

```bash
python3 <skill-dir>/scripts/beadwork.py executor handoff-close --dispatch <child-dispatch.json> --report <child-report.json> --input <observation.json>
```

observation 的字段为 task_id、stopped（布尔值）、observed_at、evidence、unresolved（未结束事项数组）。填写实际宿主观察，不能把收到回执、取消请求已发送或消息静默视作停止。将 `handoff-close` 的原始 JSON 输出保存到新文件，直接传给 `--closure`；也接受只保存 `closure_source` 字段值的 path/sha256 binding，内部统一保存 binding。

controller accept、implementer-accept、document-accept、fixer-accept 增加 `--closure <closure-source.json>`；review selection 的各轴增加 `closure: <closure_source.path>`。绑定必须对应本次 dispatch 和报告。成功或 code_failure 推进需要 stopped: true 且 unresolved 为空；未知停止状态可保存 BLOCKED 交付，但不能据此派接替 writer、合入或清理。收尾事实冲突时先更正来源，旧报告与旧观察保留。

这些记录是派发者的观察证据；脚本不探测宿主 agent 是否停止，也不根据旧 PID 终止任务。

## 补充事实与接替

```bash
python3 <skill-dir>/scripts/beadwork.py executor context-add --dispatch <root-or-stage-dispatch.json> --input <facts.json>
```

facts 只包含非空 reason 和 sources（path/sha256 数组）。事实文件应已写入证据目录且可读取。入口追加绑定链，恢复及 reviewer dispatch 返回 context_sources；不修改原 dispatch、BASE、acceptance/seam 授权或额度。继续原 agent 与接替 agent 都先读取这些来源；发现与原需求冲突时交回派发者处理。

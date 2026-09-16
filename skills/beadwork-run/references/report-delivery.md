# 子 agent 报告交付

controller、executor 和 finalizer 派发子 agent 前读取本文件；每个接收方验收自己的直接子 agent。所有角色使用“文件报告 + 短回执 + SHA-256 绑定”，报告内容与成功状态按角色定义。进度通信不受短回执限制。

## 派发和验收

1. 派发者在已有批次证据目录中创建独立子目录，将 schema 生成命令的 stdout 直接写入文件，报告/回执 schema 分别保存为 `report-schema.json`、`receipt-schema.json`，交接绝对 `report_path`、`report_schema_path`、`receipt_schema_path`、自检命令和任务身份。任务身份取自派发者固定的 ticket/axis/BASE/HEAD，不能从返回报告反推。implementer/fixer/reviewer 的身份与 gate 下限写入本目录的 `dispatch.json`。
2. 子 agent 先读取 `report_schema_path` 和 `receipt_schema_path` 指向的文件，再写完整报告并自检；自检失败可在首次交付前修正。最终只回传 `status`、`report_path`、`report_sha256`，使用派发的 `self_check_argv`，或下列带 `--emit-receipt` 的自检命令；成功 stdout 原样作为最终回执，不手工转换字段。该选项校验失败时非零退出、诊断写 stderr，不输出 receipt；合法 BLOCKED 报告仍可正常交付。派发者仅为设置 `outputSchema` 读取回执 schema，支持 strict 时启用；完整报告 schema 由接收方读取，派发者不为转发而加载或粘贴全文。schema 文件缺失或不可读时按角色的缺上下文/阻塞规则处理，不猜测结构。
3. 派发者等待 agent 和其启动的命令、子任务结束，原样保存 `receipt.json`，读取自己指定的报告并执行带回执的完整校验。文件出现、进度消息和回执到达均不替代结束确认；无法确认 writer 停止时保留现场，不派接替 writer、不合入或清理。
4. 仅 `ok: true` 通过机械检查；非零退出、缺文件、结构或路径/status/hash 不一致均按调用方停止规则处理。成功回执不替代真实日志、Git 现场、需求与 finding 的语义核对，也不证明任务已经结束。
5. 已交付报告、回执及校验结果原样保留。更正写新的 `report-N.json`/`receipt-N.json`，由派发者明确选中并重新完整验收；文件必须位于本次证据目录内，不按回执改选文件。更正只补事实，不改代码、不增加修复/review 次数；不新增自动更正循环。

SHA-256 只绑定交付文件的字节，不证明报告内容正确。聚合时继续原样嵌入已验收的 AxisReport，保留原文件、回执与校验输出，不以短回执或摘要替代原始 findings。

各角色的精确字段由本 skill 的脚本通过 `--schema` 生成，生成与验收共用内置结构；本文件定义交付行为和判定规则。历史报告、回执和 dispatch 保持原样，新派发使用当前命令，不执行历史记录中的旧命令。

## 等待与进度

有可用的派发者通信目标时，子 agent 在 commit、长 gate 开始/结束和 reviewer 派发时直接发送简短进度；自身 commentary 不视为派发者已收到。仅因无消息或等待超时，不中断 agent。默认连续 20 分钟无已确认进展后排查；中断前刷新 Git HEAD/工作区、验证记录和后代任务状态，发现新进展或命令/reviewer 仍在正常运行则继续等待。达到阈值本身不是中断依据；用户要求停止或已确认失控写入等需立即制止的情况不受此等待下限限制。

## 各角色入口

| 角色 | 报告 / 回执 schema 与自检入口 | 回执状态 |
| --- | --- | --- |
| preflight / finalizer | 下列 `verify-phase.py` 命令 | 沿用阶段状态 |
| executor | 下列 `verify-ticket.py` 命令 | `DONE` / `NEEDS_CONTEXT` / `BLOCKED` |
| implementer / fixer / reviewer | 下列 `verify-worker.py` 命令 | implementer：`DONE` / `NEEDS_CONTEXT` / `BLOCKED`；fixer：`DONE` / `BLOCKED`；reviewer：`COMPLETED` / `BLOCKED` |

阶段报告（`<phase>` 为 `preflight` 或 `finalizer`）：派发字段写入本轮 `dispatch.json`，生成与验收命令如下。

preflight 正常使用 `../agents/preflight.md` 的 `collect` / `assemble` 入口，直接返回组装器的回执；以下入口继续供 controller 独立验收和缺事实时的部分报告自检。

```bash
python3 <skill-dir>/scripts/verify-phase.py --schema <phase>
python3 <skill-dir>/scripts/verify-phase.py --receipt-schema <phase>
python3 <skill-dir>/scripts/verify-phase.py --check-report <phase> <report.json> --expected <dispatch.json> --emit-receipt
python3 <skill-dir>/scripts/verify-phase.py --check-report <phase> <report.json> <receipt.json> --expected <dispatch.json>
```

executor 报告 schema 和缺少可用 dispatch 时的结构自检：

```bash
python3 <skill-dir>/scripts/verify-ticket.py --schema
python3 <skill-dir>/scripts/verify-ticket.py --receipt-schema
python3 <skill-dir>/scripts/verify-ticket.py --check-report <report.json> --emit-receipt
python3 <skill-dir>/scripts/verify-ticket.py --check-report <report.json> <receipt.json>
```

executor 与 implementer 的正常交付使用 `ticket-execution.md`：implementer-assemble/check → implementer-accept → review → ticket-assemble → ticket-deliver。controller 只接收 root ticket report；implementer DONE 只表示实现和 gates 通过，不能替代 ticket DONE。该参考同时定义各 draft 字段、阶段恢复和来源绑定。

executor 的 `verify-ticket.py --check-report` 仅作结构自检；完整验收必须经 ticket-deliver/controller accept，核验 root、阶段、实现和 review 的来源链。源码写入前遇到能力/上下文阻塞时，也先建立 stage 检查点并组装部分报告；不能伪造 implementer 或 reviewer 成功。

implementer / fixer / reviewer 报告：

```bash
python3 <skill-dir>/scripts/verify-worker.py --schema <implementer|fixer|reviewer>
python3 <skill-dir>/scripts/verify-worker.py --receipt-schema <implementer|fixer|reviewer>
python3 <skill-dir>/scripts/verify-worker.py --check-report <role> <report.json> --expected <dispatch.json> --emit-receipt
python3 <skill-dir>/scripts/verify-worker.py --check-report <role> <report.json> <receipt.json> --expected <dispatch.json>
```

每组第三条供子 agent 自检，第四条供派发者验收。fixer 的职责见 `../agents/fixer.md`；reviewer 的职责、报告状态见 `../agents/reviewer.md`，两轴验收与 gate 见 `review.md`。

最终阶段的 stage/fixer 验收、验证来源、检查点与 root 交付统一使用 [final-execution.md](final-execution.md)。新派发使用 finalization_version: 2，不手工复制 stage 报告或修改 receipt。

## 派发者收尾确认

新 ticket、最终阶段 fixer/reviewer 和最终 root 交付，直接派发者先确认任务及其命令结束，再记录观察：

```bash
python3 <skill-dir>/scripts/executor-operations.py handoff-close --dispatch <child-dispatch.json> --report <child-report.json> --input <observation.json>
```

observation 的字段为 task_id、stopped（布尔值）、observed_at、evidence、unresolved（未结束事项数组）。填写实际宿主观察，不能把收到回执、取消请求已发送或消息静默视作停止。返回 closure_source（path/sha256），将此对象保存到新 JSON 文件。

controller accept、implementer-accept、fixer-accept 增加 `--closure <closure-source.json>`；review selection 的各轴增加 `closure: <closure_source.path>`。绑定必须对应本次 dispatch 和报告。成功或 code_failure 推进需要 stopped: true 且 unresolved 为空；未知停止状态可保存 BLOCKED 交付，但不能据此派接替 writer、合入或清理。收尾事实冲突时先更正来源，旧报告与旧观察保留。

这些记录是派发者的观察证据；脚本不探测宿主 agent 是否停止，也不根据旧 PID 终止任务。

## 补充事实与接替

```bash
python3 <skill-dir>/scripts/executor-operations.py context-add --dispatch <root-or-stage-dispatch.json> --input <facts.json>
```

facts 只包含非空 reason 和 sources（path/sha256 数组）。事实文件应已写入证据目录且可读取。入口追加绑定链，恢复及 reviewer dispatch 返回 context_sources；不修改原 dispatch、BASE、acceptance/seam 授权或额度。继续原 agent 与接替 agent 都先读取这些来源；发现与原需求冲突时交回派发者处理。

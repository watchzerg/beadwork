# 子 agent 报告交付

controller、executor 和 finalizer 派发子 agent 前读取本文件；每个接收方验收自己的直接子 agent。所有角色使用“文件报告 + 短回执 + SHA-256 绑定”，报告内容与成功状态按角色定义。进度通信不受短回执限制。

## 派发和验收

1. 派发者在已有批次证据目录中创建独立子目录，将 schema 生成命令的 stdout 直接写入文件，报告/回执 schema 分别保存为 `report-schema.json`、`receipt-schema.json`，交接绝对 `report_path`、`report_schema_path`、`receipt_schema_path`、自检命令和任务身份。任务身份取自派发者固定的 ticket/axis/BASE/HEAD，不能从返回报告反推。fixer/reviewer 的身份与 gate 下限写入本目录的 `dispatch.json`。
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
| fixer / reviewer | 下列 `verify-worker.py` 命令 | fixer：`DONE` / `BLOCKED`；reviewer：`COMPLETED` / `BLOCKED` |

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

executor 正常交付使用以下入口（仅写证据；不提交代码、不执行验证命令、不判定 acceptance）：

```bash
python3 <skill-dir>/scripts/executor-operations.py assemble --dispatch <dispatch.json> --draft <draft.json> --output <report.json> [--review <collection.json>...]
python3 <skill-dir>/scripts/executor-operations.py check --dispatch <dispatch.json> --report <report.json>
```

draft 必填 `outcome`（见 ticket-executor 的状态说明）、`status`、`test_plan`、`acceptance`、`verification`、`requested_context`、`blockers`、`concerns`，可选 `verification_notes`。status 不自动推导；`test_plan` 未知时为 null，否则只填 `decision_source` 和 `red_evidence`，mode/seams 从 dispatch 指向的 expected-plan.json 读取；已适配计划使用 controller 返回的新 dispatch。其余字段沿用报告 schema。

`assemble` 自动按时间收集本次 dispatch 下的全部验证运行，包括失败和重跑，生成报告的 `verification`。draft.verification 仅填写人工场景或尚未采集的旧证据，无则 `[]`；已采集命令无需再抄。`verification_notes` 是运行目录绝对路径到语义说明的映射，只补 red 判断、新增 gate 原因等；它不进入最终 schema，说明附在对应结果后。计划适配/恢复 dispatch 的 `verification_dispatches` 自动纳入已有运行；额外恢复时用 `--verification-dispatch <旧dispatch.json>`（可重复）显式纳入同票同 BASE 的旧运行记录。命令入口、未完成记录及结果解释见 `verification.md`。

`assemble` 使用 dispatch 固定的 BASE，从 Git 生成当前 HEAD 和完整 commit 列表；按执行顺序提供零至四个 `--review`，从明确选中的 collection 重新校验原始来源并组装 review。只有完整两轴轮次可传入；失败或缺轴的来源在 concerns 保留，已有完整轮次继续传入。恢复时可显式提供同仓库、同 worktree、同 ticket 和 BASE 的旧 dispatch 轮次；沿用已有轮次及修复额度，不以重新派发重置。脚本不猜测历史 review 来源。新报告包含 `stage`、`outcome`，以及 review 的完整 `rounds` 和 hash 绑定 `sources`；`attempts` 为实际完成的 review 数，可能小于已执行阶段数。`initial`/`final` 由组装器派生，旧两轮报告保持可读；每阶段最多新增一轮，前序来源不能遗漏。

输出必须位于本次 dispatch 目录且使用新文件名。写入后复用 verify-ticket 的完整 Git 验收，成功 stdout 即短回执；`check` 对已写报告执行同样自检，不改报告。检查包含 branch、真实 HEAD、ancestry、commit 集合、test plan、`.beads` 及 DONE 的干净状态。失败非零退出，保留候选报告和现场，更正写新文件；不能把失败输出作为成功回执。

输入或 Git 不可用，或需填写 schema 允许的未知身份时，按原 schema 写部分报告，再用 `verify-ticket.py --check-report` 获取结构自检回执；有可用 dispatch/Git 时仍执行完整 `check`。在 concerns 记录完整自检缺失或失败的原因，交由 controller 按原状态规则验收，不能据此绕过 DONE 的完整检查。controller 仍独立核对阶段、来源和语义；旧报告不因升级被改写。

fixer / reviewer 报告：

```bash
python3 <skill-dir>/scripts/verify-worker.py --schema <fixer|reviewer>
python3 <skill-dir>/scripts/verify-worker.py --receipt-schema <fixer|reviewer>
python3 <skill-dir>/scripts/verify-worker.py --check-report <role> <report.json> --expected <dispatch.json> --emit-receipt
python3 <skill-dir>/scripts/verify-worker.py --check-report <role> <report.json> <receipt.json> --expected <dispatch.json>
```

每组第三条供子 agent 自检，第四条供派发者验收。fixer 的职责见 `../agents/fixer.md`；reviewer 的职责、报告状态见 `../agents/reviewer.md`，两轴验收与 gate 见 `review.md`。

最终阶段由 finalizer 使用下列入口准备和组装；`final-stage` 只创建证据与可选 fixer dispatch，`final-assemble` 不运行验证或派发 agent：

```bash
python3 <skill-dir>/scripts/executor-operations.py final-stage --dispatch <root-dispatch.json> --input <stage-facts.json>
python3 <skill-dir>/scripts/executor-operations.py final-assemble --dispatch <stage-dispatch.json> --draft <draft.json> --output <stage-report.json> [--review <collection.json> ...] --fixers <fix-source-list.json> > <stage-receipt.json>
```

`final-assemble` 的 stdout 就是 `{status, report_path, report_sha256}` 短回执；将它保存为同一阶段目录内的新 `stage-receipt.json`，不要把日志混入此文件。首次 `stage-facts.json` 为 `{}`。`stage-facts.json` 的恢复输入使用 `previous_stage`、`previous_report`、`previous_receipt` 和 `continuation: resume|repair`；`repair` 只接受已验收的 `code_failure` 阶段。`fix-source-list.json` 是 fixer 的 dispatch/report/receipt hash 绑定列表。组装器保留整个 attempt 的来源，stage 报告用于恢复。交还 controller 时（成功或 BLOCKED）将同一份已验收 stage 报告字节复制至 root dispatch 指定的报告路径，并以 root dispatch 重新验收 receipt，供 controller `accept` 使用。

每个 fixer 来源的形状为 `{dispatch: {path, sha256}, report: {path, sha256}, receipt: {path, sha256}}`；三者均为原文件绝对路径及其 SHA-256。`--review` 和 `--fixers` 传入按执行顺序排列的**全部**已完成来源（包括 dispatch 的 `prior_reviews`/`prior_fixes`），不是只传本阶段增量。draft 的 `verification` 仅填本次 finalizer 新运行的记录；组装器按历史、fixer、当前 finalizer 的顺序合并。

root 交付不重跑组装：原样复制 stage report，复制 stage receipt 并仅把 `report_path` 改为 root 报告绝对路径（字节未变，SHA-256 沿用）。两份目标都使用新文件名，不覆盖已有证据。随后执行：

```bash
python3 <skill-dir>/scripts/verify-phase.py --check-report finalizer <root-report.json> <root-receipt.json> --expected <root-dispatch.json>
```

验收成功后才返回 root receipt；controller 用同一组路径执行 `accept`。阶段原件继续作为恢复来源。

# Writer 交付

只读取自己角色的部分。读取 dispatch.required_reads 和 draft_schema_path；填写语义判断，由 assemble 生成执行事实并完整自检。stdout 即短回执；独立 *-check 用于更正后的复核。直接派发者使用 [共享交付协议](report-delivery.md) 验收。

## implementer 交付

implementer 读取 draft_schema_path。输入事实、规则/spec、必要 gate 范围和恢复来源由 executor 显式交接。`inspect`/`check-layer` 的用法见 `executor-operations.md`；验证记录和三次修复见 `verification.md`。

```bash
python3 <skill-dir>/scripts/beadwork.py executor implementer-assemble --dispatch <implementer-dispatch.json> --draft <draft.json> --output <report.json>
```

draft 结构读取生成的输入 schema。只提供语义判断：acceptance 的证据映射、test_plan 的判断依据与 red 证据、未采集的人工验证、实际收尾与阻塞事项。verification_notes 按运行目录记录有效 red、验证覆盖说明或未知运行收尾。脚本生成 mode/seams、身份和验证来源，不手工复制。

组装器从 Git 生成 ticket BASE、stage_base、当前 HEAD 和整票 commits，收集当前及适配前 implementer 的全部验证日志。成功要求以采集器的 `--delivery` 运行无参数 `gate-core`，并在当前干净交付 HEAD 通过；`test` 的行为 red、直接验证与 acceptance 覆盖由 executor 验收。code_failure 要求三次修复已用尽，且存在第三次修复候选的正常非零交付结果。原始失败记录不会被成功重跑删除。组装器固定交付时的 verification_sources（运行目录及 started/result 的内容绑定，缺失文件显式为 null）；后续新增运行不改变历史报告，新报告仍采集全部当前来源。来源缺失或损坏时，verification_issues 保存原绑定与实际错误；只能返回 `BLOCKED / blocked|interrupted`，不能进入 review、声明成功或作为 code_failure 推进。

stdout 为短回执；executor 确认 implementer 及命令结束，保存到该 implementer 目录下的新 receipt 文件，然后带实际收尾 observation 验收：

```bash
python3 <skill-dir>/scripts/beadwork.py executor implementer-accept --dispatch <stage-dispatch.json> --report <implementer-report.json> --receipt <implementer-receipt.json> --observation <observation.json>
```

该入口重新校验身份、Git 和验证来源，并将选择追加到 root 检查点。重复验收同一来源幂等。实现的 passed/code_failure 一经验收，不能改报中断来继续旧 writer；成功或代码失败阶段不再接受新的实现来源，阶段/审查报告更正仍可在同 HEAD 完成。blocked/interrupted 阶段按原 stage 恢复；writer 与计划适配共用状态约束，review 预留后保持冻结。验收失败按证据/报告问题处理，不消耗 stage。合法部分报告也保留来源，但只有实现 DONE 才可准备 review。


## 文档同步交付

final-stage 为 stage 0 返回 document_dispatch、document_launch_context 和 selected_document；按返回上下文及该 dispatch 的 model/reasoning_effort 派发 document-syncer，不手工构造 dispatch。规则见 [documentation-sync.md](documentation-sync.md)。executor/finalizer 的 review 后收尾通过 document-closeout-prepare 取得同角色 dispatch，复用 document-assemble，验收使用 [document-closeout-accept](document-closeout.md)。

```bash
python3 <skill-dir>/scripts/beadwork.py executor document-assemble --dispatch <document-dispatch.json> --draft <draft.json> --output <report.json>
python3 <skill-dir>/scripts/beadwork.py executor document-accept --dispatch <stage-dispatch.json> --report <report.json> --receipt <receipt.json> --observation <observation.json>
```

同步器读取 draft_schema_path，填写 inspected、summary、result、verification_notes、实际收尾与剩余工作。身份、BASE/HEAD、commits、changed_files 和验证来源由脚本生成。DONE 需要干净现场、已完成检查、无剩余工作；当前 HEAD 的每项定向检查按完整 argv 分别取最新结果，不得用另一组 test 参数的成功掩盖失败。有修改为 updated，无修改为 no_change_needed，不要求空提交或 gate-full。BLOCKED/blocked|interrupted 使用 incomplete，不触发新的修复 stage。

finalizer 先核对文档范围与语义，再保存回执并带实际收尾观察 accept。源码 writer 未结束时不运行验证；stage 0 完整 gate/review 必须覆盖同步器交付 HEAD。检查点保留 document_sources，最终报告单独列出 document_commits；后续 fixer 的提交继续使用 fix_sources/fix.commits，全部最终新增提交必须可追溯到这两类来源。review 后收尾的文档提交仍归 document_sources/document_commits，另保留 document_closeout 的定点验收；两类提交可能在历史中交错，不改写提交归属。


## fixer 交付

```bash
python3 <skill-dir>/scripts/beadwork.py executor fixer-assemble --dispatch <fixer-dispatch.json> --draft <draft.json> --output <report.json>
python3 <skill-dir>/scripts/beadwork.py executor fixer-accept --dispatch <stage-dispatch.json> --report <report.json> --receipt <receipt.json> --observation <observation.json>
```

fixer 读取 dispatch.draft_schema_path，只填写处置、verification_notes、实际收尾和剩余工作。身份、HEAD、commits、验证运行及来源由脚本生成；stdout 为短回执，保存原件。

DONE 需当前 HEAD 的一次完整 `gate-full`；code_failure 需三次 gate-fix 已用尽及第三次候选正常非零交付结果。blocked/interrupted 可保留部分证据，不伪造成功。直接派发者按 report-delivery.md 在 accept 中提供收尾观察；验收会保存 fixer 选择。成功或代码失败终态不能改报中断继续写入。

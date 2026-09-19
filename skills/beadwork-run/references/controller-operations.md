# controller 脚本入口

controller 执行本文件命令；子 agent 不调用。脚本只负责确定性操作，不判断 acceptance 是否满足、不确认宿主 agent 已结束、不派发 agent。tracker 和初始化入口只由 controller 调用；初始化复用 tracker 写入。controller 负责交付契约验收、异常证据追查和 writer 收尾确认；单票实现与测试的日常语义验收由 executor 负责。

## Beads 写入

claim、start/completion/stop comment、close 均通过 controller 专用入口，先核对当前步骤前置条件：

```bash
python3 <skill-dir>/scripts/beadwork.py tracker prepare --input <operation.json> --output <intent.json>
python3 <skill-dir>/scripts/beadwork.py tracker execute --intent <intent.json>
```

operation 公共字段为 repository_root（primary 绝对路径）、parent_id、issue_id、kind；按操作补充：

| kind | 输入与 controller 前置核对 |
| --- | --- |
| claim | expected_assignee：实际领取身份；parent 需 install/BASE gate-full 通过，child 需刷新后的 claim frontier 与 sync_result |
| comment | body：核对后的完整正文；completion/integration-ready 使用 controller comment 生成正文，保留其 JSON 身份块 |
| close | reason、prerequisite（path/sha256）；child 绑定成功 acceptance，parent 绑定成功 merge checkpoint；controller 另核对对应 completion 已写入 |

脚本保存 intent，写后读回 show/comments；它验证 prerequisite 文件绑定，不代替成功状态、语义和流程顺序核对。execute 成功返回 before/after、already_applied 和 write_exit_code；comment 结果直接包含唯一读回的字符串 `comment_id`，用于 merge。结果缓存只表示该 intent 曾完成，进入后续步骤仍核对实时现场。

未知结果使用原 intent 重试，先读回协调；不创建新 intent 盲目重发。claim 竞争失败重新计算 frontier；已由其他身份领取时不采用。

## 初始化与恢复事实

先执行 `update-main` 并将成功 JSON 原样保存到批次证据目录的新文件，再准备初始化：

```bash
python3 <skill-dir>/scripts/beadwork.py batch-initialize prepare --input <initialize-input.json> --output <primary>/.worktrees/.evidence/<parent>/initialize/<唯一目录>/intent.json
python3 <skill-dir>/scripts/beadwork.py batch-initialize execute --intent <intent.json>
```

prepare 输入为 repository_root、parent_id、固定 expected_children、expected_assignee，以及 preflight_acceptance、update_main_result 两个 path/sha256 bindings。先建立唯一目录；脚本绑定固定 main、READY preflight 和执行计划。execute 自动创建 Beads worktree，核对共享 workspace，完成 install/env-facts/BASE gate-full、parent claim 与中文批次 comment，全部成功才发布 ready.json，返回 base_commit、comment_id 和来源。正常调用不手写步骤或 comment。

失败使用原 intent 重试，保留旧日志；成功步骤仅在上游来源一致时复用。未知或中断命令先确认宿主任务与外部资源结束，再加 `--recovery <observations.json>`。文件为观察数组，每项包含 run_path（错误指向的运行目录）、task_id、stopped、observed_at、evidence、unresolved；stopped 必须为 true 且 unresolved 为空。脚本保存观察，不自行探测宿主任务。已进入 child 工作时走 recovery-batch.md，不重跑初始化。ready 只证明初始化完成，后续仍执行实时 frontier 和 sync-main。

必要时使用只读事实入口，不能用它替代明确报告选择或宿主停止观察：

```bash
python3 <skill-dir>/scripts/beadwork.py batch-evidence --output <facts.json> inspect --repository-root <primary> --parent-id <parent-id>
python3 <skill-dir>/scripts/beadwork.py batch-evidence --output <manifest.json> manifest --input <manifest-input.json>
```

manifest-input 为 parent_id、固定 expected_children、按该顺序一一对应的成功 ticket acceptance bindings。输出 tickets 和 required_boundary_gates；controller 核对实际补充边界，并继续交接原始 ticket/completion pointers，不能用 manifest 替代 review findings 或顺序执行记录。

以下 `beadwork.py controller` 命令成功 stdout 为 JSON，非零退出停止；证据使用新文件名，输入路径均为绝对路径。

## 更新 primary 的本地 main

初始化及最终集成前调用：

```bash
python3 <skill-dir>/scripts/beadwork.py controller update-main --repository-root <repository-path>
```

脚本在 fetch 前及 fast-forward 前检查 primary checkout main、干净且无未完成 Git 操作；fetch 失败时仅允许使用现存本地 `origin/main`，不能 fast-forward 则停止。返回固定 `main_commit`、`fetch_failed` 和供 comment 使用的 note。此命令与最终 `merge` 执行期间，用户需暂停操作 primary。

## 新票前同步本地 main

仅在 frontier 为 `claim`、旧 writer 及其命令已确认结束时调用；恢复当前票仍走 `prepare executor mode=resume`。

```bash
python3 <skill-dir>/scripts/beadwork.py controller sync-main --input <sync-input.json>
```

输入：`repository_root`、`parent_id`、固定的 `expected_children`，以及：

- `required_boundary_gates`：剩余 children 声明的边界及适用于剩余工作的已确认补充边界。脚本校验其属于当前 `gate-plan.full`、去重并排除 `gate-core` 与 `gate-full`。
- `install_inputs`：目标仓库的安装/工具链输入文件或目录的相对路径列表。根据实际安装契约提供 manifest、lockfile、版本配置和影响安装的脚本；workspace manifest 也须包含。每批确认一次并复用，不能只列根 manifest。例如 Bun 项目需核对 `bun.lock`、各 workspace `package.json`、mise 配置及安装入口。

脚本检查 topology、implementation 干净且两个 worktree 无未完成 Git 操作，重新查询 frontier，固定本地 main SHA；已包含则不重跑全量，只重新绑定只读 `gate-plan`。实际合入改变 implementation HEAD 后，安装输入有变化才运行 `just install`，随后顺序运行 `just env-facts`、`just gate-plan` 和一次无参数 `just gate-full`。所有 just 调用使用 `--one`；implementation 源码或 HEAD 在验证中变化即失败。不创建 agent、不自动解决冲突、不 fetch、不写 primary 或 Beads。

成功输出 `sync_result`、`head`、`target_main`、`changed` 和刷新后的 `frontier`。只按这个 frontier 领取；无需再同步追赶随后移动的 main。`prepare executor mode=new` 必须带 `sync_result`，机械核对身份、HEAD、目标 ancestry 及验证日志；同步提交位于新票 BASE 之前。同步没有改变当前票修复阶段的入口。

证据位于 `<primary>/.worktrees/.evidence/<parent>/main-sync/<id>/`：merge 前写 `intent.json`，每个命令保存独立 started/result/log，全部成功后写 `ready.json`。start comment 引用 `sync_result`；发生停止时 parent comment 引用该目录及失败原因。命令失败的 stderr 同时提供证据路径。

失败或中断后，先确认旧命令及资源已结束，再使用原输入重跑。脚本自动发现唯一未完成 intent，固定原目标和验证输入；main 后续前进不会覆盖原意图。冲突保持原状，明确解决并提交后才能恢复；已合并但未写 ready 或验证失败时重新验证，即使目标已在历史中也不能跳过。人工修复后的 HEAD 必须保留同步前历史和目标 main，并在当前 HEAD 重新验证。已完成同步后、claim 前中断，重跑可生成无变化结果。同步失败归批次基线阻塞，不领取 child、不消耗六阶段额度。

## 最终集成同步与环境准备

全部 children 关闭、旧任务结束后，使用 `update-main` 返回的固定 SHA 调用：

```bash
python3 <skill-dir>/scripts/beadwork.py controller sync-final --input <final-sync-input.json>
```

输入为 repository_root、parent_id、固定 expected_children、reviewed_main（完整 SHA）和本批次已确认的 install_inputs。此入口代替手工 merge，复用同步的 intent、命令日志和恢复机制，证据保存在 `final-sync/`。安装输入相对合并前 HEAD 有变化时执行 `just install`；实际合入后运行 `just env-facts`，gates 仍由 finalizer 执行。没有变化则跳过命令。

仅成功且返回 frontier 为 done 时，使用返回的 target_main 作为 REVIEWED_MAIN、sync_result 作为 prepare finalizer 的 final_sync_result。prepare 核对当前 HEAD、目标 ancestry、计划及安装记录；同 attempt 的 finalizer 接替沿用原环境来源，不在 fixer 中途态重新同步。

安装失败或中断后保留现场，确认旧命令结束，再用原输入恢复；即使 merge 已完成，也重新执行尚未完成同步的安装检查。main 后续变化不替换原目标。冲突解决并提交后恢复同一 intent；同步未成功前不派 finalizer，不消耗最终修复阶段。

## 准备派发材料

```bash
python3 <skill-dir>/scripts/beadwork.py controller prepare <preflight|executor|finalizer> --input <input.json>
```

公共输入：`repository_root`（当前仓库任一 worktree）、`parent_id`、`rules_paths`（适用规则绝对路径列表）。其他字段按角色：

- preflight：重新派发时提供首次固定的 `expected_children`。
- executor：`ticket_id`、`mode: new|resume`、`test_mode: TDD|direct_verification`、`approved_seams`、`testing_seams_doc`（本 skill 的 references/testing-seams.md 绝对路径；其他契约与项目事实按 `testing-contract.md` 定位）、`linked_spec`、`required_boundary_gates`（本票声明及已补充 gate 下限）、环境/冒烟证据及恢复事实。新票另提供 preflight_acceptance（已验收 READY preflight 的 acceptance 文件 path/sha256）；prepare 核对 ticket 计划、spec 和 gate 下限，自动保存 plan_source 与 sync_result 的环境来源。`resume` 必须额外提供从 start comment 核实的完整 `base_commit`；脚本不会猜测或补写缺失 BASE。
- finalizer：`expected_children`、`linked_spec`、`ticket_evidence`、`required_boundary_gates`、`prior_finalization`、已合入 implementation 的完整 `reviewed_main` SHA，以及由本次 `sync-final` 的 `sync_result` 填入的 `final_sync_result`。`prior_finalization` 首次为 null；接替时按 `recovery-finalizer.md` 准备。

executor prepare 建立整票 root dispatch，返回 `coordinator_model`。`complex_ticket: true` 提高协调与实现起点；controller 不填写 stage/models/prior_reviews，也不传 repair。恢复提供原 root 的 `previous_dispatch` 和完整 BASE；返回原 root，不新建 stage 或重置额度。执行阶段、模型、implementer 和计划适配由 executor 使用 `ticket-execution.md` 的入口管理。

finalizer root dispatch 建立 attempt 身份；finalizer 使用 final-stage 管理阶段、模型及修复，controller 等待 root 终态。具体流程由 agents/finalizer.md 和 final-execution.md 定义。

同一 main 基线的 finalizer 重跑必须提供 `prior_finalization.stage_path`，恢复原 attempt，不重置 stage、BASE、历史来源或 dirty 修复现场。只有 main 实际变化或用户明确额外修复授权才传 `new_attempt_reason` 建立新 attempt，且需干净现场。

脚本定位 primary、检查 `.worktrees` 已被忽略、生成固定 branch/worktree 路径和唯一 dispatch 目录，写入 `dispatch.json`、报告/回执 schema；executor root 写入 `expected-plan.json`。新票从干净 worktree 记录 BASE；恢复票保留传入 BASE；finalizer 新 attempt 从已合入 main 的干净现场核对传入的 `reviewed_main` 并记录 `start_head`，同阶段恢复按恢复来源保留原值及修复现场。

返回文件路径和本轮 SHA；dispatch 保留报告/回执 schema 路径；需要填写 draft 的角色另外生成 `draft_schema_path`，正常只读取输入契约。controller 将生成的 dispatch 字段、角色入口及本轮事实交给子 agent，schema 按共享交付契约传路径；额外输入事实会保留在 dispatch。脚本不 claim、不写 start comment、不安装环境。

## 机械验收

先确认子 agent 及其命令已结束，将其回执原样保存到本轮证据目录。报告路径由 controller 指定，更正报告显式选中。

```bash
python3 <skill-dir>/scripts/beadwork.py controller accept --dispatch <dispatch.json> --report <report.json> --receipt <receipt.json> --output <acceptance-N.json> --closure <closure-source.json>
```

复用现有 verifier 检查报告、回执和身份；executor 另核验整票 root、阶段和 implementer 来源链并执行现有 Git 验收，finalizer 检查实际 branch/HEAD、ancestry、`.beads`，成功状态要求 implementation worktree 干净。非成功报告按原状态规则允许部分证据和未提交工作。成功输出并保存绑定 dispatch/report/receipt hash 的机械验收记录；校验失败不生成通过记录。

`mechanical_acceptance` 不等于语义验收通过；controller 按 SKILL.md 核对交付与集成条件；仅在矛盾、缺证或越界时追查源码、日志和原始 reviewer 证据。

## 生成完成 comment

controller 完成交付验收后调用：

```bash
python3 <skill-dir>/scripts/beadwork.py controller comment --acceptance <acceptance-N.json> --summary '<中文交付摘要>' --output <completion-N.md> [--evidence <补证文件>...]
```

只接受成功 executor/finalizer 报告，重新核验文件绑定和现场。executor 生成 ticket completion，finalizer 生成 integration-ready；保留 commit 范围、验证记录、review 次数、当前阶段及模型、原始非阻塞 smells 和证据路径。controller 用 `--evidence` 加入更正前的报告、补证或 fetch fallback 等额外证据，核对正文并补足本轮必要说明后，将全文作为 tracker comment 的 body 写入。integration-ready 中的 JSON 身份块保持原样。

## 合入本地 main

仅在语义验收通过、writer 已结束、生成的 integration-ready comment 已成功写入 parent 后调用：

```bash
python3 <skill-dir>/scripts/beadwork.py controller merge --acceptance <acceptance-N.json> --comment-id <integration-ready-id> --output <merge-checkpoint.json>
```

脚本只读查询实际 parent comment，核对其 parent、BASE/HEAD 和验收证据绑定，再核对 worktree、main 与受审 HEAD。先写 checkpoint，随后 fast-forward 到固定受审 SHA。返回 `merged: true` 才能继续写 parent completion 和关闭 parent。

命令中断或失败后恢复前，读取 `recovery-merge.md`；checkpoint 本身不证明合入成功。

## 安全清理

controller 完成 parent completion 并关闭后调用：

```bash
python3 <skill-dir>/scripts/beadwork.py controller cleanup --merge-record <merge-checkpoint.json>
```

脚本读取 merge checkpoint，只读查询 parent 已关闭，确认受审 HEAD 已在 main 历史中、尚存 branch 仍指向该 SHA、worktree 属于该仓库和 branch 且干净，再非强制删除。已删除的部分跳过，可重跑；证据目录保留。失败保留未清理部分。此入口只完成本地收尾，不要求远端同步或推送结果。

## 基线适配

executor 负责开工 BASE 已满足和恢复 TDD 的执行策略适配，使用 baseline-adaptation.md 的 ticket-adapt-plan。controller 只在最终记录引用适配证据，不调用 adapt-plan、不审批每次单票适配。

## 串行计划绑定

child claim 的 prepare 自动读取已接纳计划并写入 intent；execute 重新核对计划、下一张票和实时 ready，必须提供 `expected_assignee`。恢复领取使用原始 intent；相同 assignee 不能替代来源身份。Parent claim 不受子票顺序约束。计划发布和显式调整使用 [serial-planning.md](serial-planning.md) 的脚本入口，日常循环不手写区块或重排。

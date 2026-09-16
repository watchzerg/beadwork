# controller 脚本入口

controller 执行本文件命令；子 agent 不调用。脚本只负责确定性操作，不判断 acceptance 是否满足、不确认宿主 agent 已结束、不派发 agent、不写 Beads。controller 负责交付契约验收、异常证据追查、writer 收尾确认和全部 tracker 写入；单票实现与测试的日常语义验收由 executor 负责。

使用 `python3 <skill-dir>/scripts/controller.py <command>`。成功 stdout 为 JSON；失败非零退出并在 stderr 返回原因，按 SKILL.md 停止处理。证据文件使用新文件名，不覆盖历史。所有输入路径使用绝对路径；输入 JSON 由 controller 根据已核实事实编写，不执行历史记录中的命令。

## 更新 primary 的本地 main

初始化及最终集成前调用：

```bash
python3 <skill-dir>/scripts/controller.py update-main --repository-root <repository-path>
```

脚本在 fetch 前及 fast-forward 前检查 primary checkout main、干净且无未完成 Git 操作；fetch 失败时仅允许使用现存本地 `origin/main`，不能 fast-forward 则停止。返回固定 `main_commit`、`fetch_failed` 和供 comment 使用的 note。此命令与最终 `merge` 执行期间，用户需暂停操作 primary。

## 新票前同步本地 main

仅在 frontier 为 `claim`、旧 writer 及其命令已确认结束时调用；恢复当前票仍走 `prepare executor mode=resume`。

```bash
python3 <skill-dir>/scripts/controller.py sync-main --input <sync-input.json>
```

输入：`repository_root`、`parent_id`、固定的 `expected_children`，以及：

- `required_boundary_gates`：剩余 children 声明的边界及适用于剩余工作的已确认补充边界。脚本校验 recipe 名、去重并排除 smoke 已覆盖的 `gate-unit`。
- `install_inputs`：目标仓库的安装/工具链输入文件或目录的相对路径列表。根据实际安装契约提供 manifest、lockfile、版本配置和影响安装的脚本；workspace manifest 也须包含。每批确认一次并复用，不能只列根 manifest。例如 Bun 项目需核对 `bun.lock`、各 workspace `package.json`、mise 配置及安装入口。

脚本检查 topology、implementation 干净且两个 worktree 无未完成 Git 操作，重新查询 frontier，固定本地 main SHA；已包含则跳过命令，否则 fast-forward 或普通 merge。实际合入后，安装输入相对同步前 HEAD 有变化才运行 `just install`，随后顺序运行 `just env-facts` 和 `just smoke <gate>...`。所有 just 调用使用 `--one`；implementation 源码或 HEAD 在验证中变化即失败。不创建 agent、不自动解决冲突、不 fetch、不写 primary 或 Beads。

成功输出 `sync_result`、`head`、`target_main`、`changed` 和刷新后的 `frontier`。只按这个 frontier 领取；无需再同步追赶随后移动的 main。`prepare executor mode=new` 必须带 `sync_result`，机械核对身份、HEAD、目标 ancestry 及验证日志；同步提交位于新票 BASE 之前。同步没有改变当前票修复阶段的入口。

证据位于 `<primary>/.worktrees/.evidence/<parent>/main-sync/<id>/`：merge 前写 `intent.json`，每个命令保存独立 started/result/log，全部成功后写 `ready.json`。start comment 引用 `sync_result`；发生停止时 parent comment 引用该目录及失败原因。命令失败的 stderr 同时提供证据路径。

失败或中断后，先确认旧命令及资源已结束，再使用原输入重跑。脚本自动发现唯一未完成 intent，固定原目标和验证输入；main 后续前进不会覆盖原意图。冲突保持原状，明确解决并提交后才能恢复；已合并但未写 ready 或验证失败时重新验证，即使目标已在历史中也不能跳过。人工修复后的 HEAD 必须保留同步前历史和目标 main，并在当前 HEAD 重新验证。已完成同步后、claim 前中断，重跑可生成无变化结果。同步失败归批次基线阻塞，不领取 child、不消耗四阶段额度。

## 准备派发材料

```bash
python3 <skill-dir>/scripts/controller.py prepare <preflight|executor|finalizer> --input <input.json>
```

公共输入：`repository_root`（当前仓库任一 worktree）、`parent_id`、`rules_paths`（适用规则绝对路径列表）。其他字段按角色：

- preflight：重新派发时提供首次固定的 `expected_children`。
- executor：`ticket_id`、`mode: new|resume`、`test_mode: TDD|direct_verification`、`approved_seams`、`testing_seams_doc`（本 skill 的 references/testing-seams.md 绝对路径；其他契约与项目事实按 `testing-contract.md` 定位）、`linked_spec`、`required_boundary_gates`（本票声明及已补充 gate 下限）、环境/冒烟证据及恢复事实。`resume` 必须额外提供从 start comment 核实的完整 `base_commit`；脚本不会猜测或补写缺失 BASE。
- finalizer：`expected_children`、`linked_spec`、`ticket_evidence`、`required_boundary_gates`、`prior_finalization`、已合入 implementation 的完整 `reviewed_main` SHA。`prior_finalization` 首次为 null；接替时按 `recovery-finalizer.md` 准备。

executor prepare 建立整票 root dispatch，返回 `coordinator_model`。`complex_ticket: true` 提高协调与实现起点；controller 不填写 stage/models/prior_reviews，也不传 repair。恢复提供原 root 的 `previous_dispatch` 和完整 BASE；返回原 root，不新建 stage 或重置额度。执行阶段、模型、implementer 和计划适配由 executor 使用 `ticket-execution.md` 的入口管理。

finalizer root dispatch 只建立 attempt 身份；finalizer 再调用 `executor-operations.py final-stage` 建立 stage 0..3。stage 0 没有 fixer；stage 1/2/3 分别派 `gpt-5.6-sol` / `medium`、`gpt-5.6-sol` / `medium`、`gpt-6-astra` / `medium` fixer。每阶段最多一轮完整双轴 review。stage 0 的 final/gate 代码失败跳过 review；后续 fixer 的最多三次就地 gate 修正按 `verification.md` 执行。代码导致的完整 blocking review 或 fixer 正式返回的 `code_failure` 都由 finalizer 组装为 `code_failure` 并以 `repair` 进入下一阶段；外部、环境、需求或 seam 阻塞不推进。stage 3 仍不能通过时停止。

同一 main 基线的 finalizer 重跑必须提供 `prior_finalization.stage_path`，恢复原 attempt，不重置 stage、BASE、历史来源或 dirty 修复现场。只有 main 实际变化或用户明确额外修复授权才传 `new_attempt_reason` 建立新 attempt，且需干净现场。旧格式导入除旧报告外还必须给 `legacy_dispatch`、`legacy_receipt`、全部 `legacy_reviews`，以及有 fixer 时的 dispatch/report/receipt 来源；导入只读取并绑定，不改写旧证据。

脚本定位 primary、检查 `.worktrees` 已被忽略、生成固定 branch/worktree 路径和唯一 dispatch 目录，写入 `dispatch.json`、报告/回执 schema；executor root 写入 `expected-plan.json`。新票从干净 worktree 记录 BASE；恢复票保留传入 BASE；finalizer 新 attempt 从已合入 main 的干净现场核对传入的 `reviewed_main` 并记录 `start_head`，同阶段恢复按恢复来源保留原值及修复现场。

返回文件路径和本轮 SHA；dispatch 包含 `report_schema_path` 和 `receipt_schema_path`。controller 将生成的 dispatch 字段、角色入口及本轮事实交给子 agent，schema 按共享交付契约传路径；额外输入事实会保留在 dispatch。脚本不 claim、不写 start comment、不安装环境。

## 机械验收

先确认子 agent 及其命令已结束，将其回执原样保存到本轮证据目录。报告路径由 controller 指定，更正报告显式选中。

```bash
python3 <skill-dir>/scripts/controller.py accept --dispatch <dispatch.json> --report <report.json> --receipt <receipt.json> --output <acceptance-N.json>
```

复用现有 verifier 检查报告、回执和身份；executor 另核验整票 root、阶段和 implementer 来源链并执行现有 Git 验收，finalizer 检查实际 branch/HEAD、ancestry、`.beads`，成功状态要求 implementation worktree 干净。非成功报告按原状态规则允许部分证据和未提交工作。成功输出并保存绑定 dispatch/report/receipt hash 的机械验收记录；校验失败不生成通过记录。

`mechanical_acceptance` 不等于语义验收通过；controller 仍按 SKILL.md 核对代码、日志、需求和 reviewer 证据。

## 生成完成 comment

controller 完成交付验收后调用：

```bash
python3 <skill-dir>/scripts/controller.py comment --acceptance <acceptance-N.json> --summary '<中文交付摘要>' --output <completion-N.md> [--evidence <补证文件>...]
```

只接受成功 executor/finalizer 报告，重新核验文件绑定和现场。executor 生成 ticket completion，finalizer 生成 integration-ready；保留 commit 范围、验证记录、review 次数、当前阶段及模型、原始非阻塞 smells 和证据路径。controller 用 `--evidence` 加入更正前的报告、补证或 fetch fallback 等额外证据，核对正文并补足本轮必要说明后，用 `bd comments add <id> -f <completion-N.md> --json` 写入。integration-ready 中的 JSON 身份块保持原样。

## 合入本地 main

仅在语义验收通过、writer 已结束、生成的 integration-ready comment 已成功写入 parent 后调用：

```bash
python3 <skill-dir>/scripts/controller.py merge --acceptance <acceptance-N.json> --comment-id <integration-ready-id> --output <merge-checkpoint.json>
```

脚本只读查询实际 parent comment，核对其 parent、BASE/HEAD 和验收证据绑定，再核对 worktree、main 与受审 HEAD。先写 checkpoint，随后 fast-forward 到固定受审 SHA。返回 `merged: true` 才能继续写 parent completion 和关闭 parent。

命令中断或失败后恢复前，读取 `recovery-merge.md`；checkpoint 本身不证明合入成功。

## 安全清理

controller 完成 parent completion comment 和关闭后调用：

```bash
python3 <skill-dir>/scripts/controller.py cleanup --merge-record <merge-checkpoint.json>
```

脚本只读查询 parent 已关闭，确认受审 HEAD 已在 main 历史中、尚存 branch 仍指向该 SHA、worktree 属于该仓库和 branch 且干净，再非强制删除。已删除的部分跳过，可重跑；证据目录保留。失败保留未清理部分。

## 基线适配

executor 负责开工 BASE 已满足和恢复 TDD 的执行策略适配，使用 baseline-adaptation.md 的 ticket-adapt-plan。controller 只在最终记录引用适配证据，不调用 adapt-plan、不审批每次单票适配。

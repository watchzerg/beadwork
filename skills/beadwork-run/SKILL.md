---
name: beadwork-run
description: "串行实现一个 Beads parent 下的 ticket 依赖图，并在双层 review 后合入本地 main。"
---

# Beadwork Run

给定一个完整的 Beads parent ID，串行实现它的 direct child tickets。每个 ticket 使用一个全新的 executor；同一时刻只有一个 writer。每张新票开工前按需同步本地 `main`；所有 children 完成后，把最新 `main` 合入 implementation branch，执行最终验证和 review，再 fast-forward 合入本地 `main`。

本 skill 只合入本地 `main`。不 push Git，也不执行 `bd dolt pull` 或 `bd dolt push`。

## Interface

输入为一个完整 Beads parent ID，parent 的 Beads type 不受限制：

```text
$beadwork-run <full-parent-bead-id>
```

固定布局：

```text
branch:   implement/<full-parent-id>
worktree: .worktrees/<full-parent-id>
```

## 执行约定

- controller 开始执行前读取 `references/testing-contract.md` 定位共享测试契约与项目事实；运行 BASE smoke 或核对最终覆盖前读取 `testing-gates.md`，验收 TDD ticket 前读取 `testing-tdd.md` 和 `testing-seams.md`；计划缺证或冲突时读取 `testing-plan.md`，处理 seam 授权问题时读取 `testing-seams.md`。不预读出票模板或尚未触发的 TDD 细节。
- Beads 读取结构化结果使用 `--json`；未列出的命令语法按需查询 CLI 帮助。
- controller 将 `<skill-dir>` 解析为本 skill 的绝对目录。内置脚本使用 python3 ≥ 3.9（仅标准库），在待检查 repository/worktree 中运行；正常调用无需读取源码。stdout 为 JSON，非零退出按停止处理，不能当作空结果。executor 的命令采集入口另按 `references/verification.md` 区分验证失败（可核对 TDD red）、记录器异常和中断。
- 项目安装与验证经目标仓库的 `just` recipes 执行，缺失或失败按对应步骤处理。recipe 检查由 preflight 负责。
- controller 派发前读取 `references/report-delivery.md` 与 `references/controller-operations.md`；后者定义准备、机械验收、comment 生成、合入和清理命令。

## 宿主能力

仅支持 Codex；其他宿主直接中止。假定下述模型均可用，派发时按就地规则显式指定 `model` 和 reasoning effort（参数名以当前工具声明为准）。ticket 按阶段 dispatch 的模型派发；报告更正沿用原模型组合，其他角色接替沿用原规则。

写入前确认当前宿主能创建独立 executor、执行内置双轴审查的两个并行只读 reviewers、接收完整报告并确认任务结束。需要支持 controller → preflight、controller → executor → reviewers、controller → finalizer → reviewers/fixer 的嵌套派发。能力不足时报告并停止。

controller 派发的 preflight、executor 和 finalizer 使用独立上下文（`fork_turns: "none"` 或宿主等价设置）；显式交接仓库规则入口、任务事实和证据路径。恢复时补充已有 commits、未提交现场、剩余工作与未解决 findings。

## 不变量

- controller 独占 Git/worktree 生命周期、ticket 选择、Beads 写入和最终集成；子 agent 对 Beads 只读。
- preflight/finalizer 只写证据；源码由当前 ticket executor 或最终阶段的唯一 fixer 写入，只读研究与双轴 reviewers 可并行。
- 不 stash、不 reset、不 amend、不 squash、不 force-remove。
- review 后不改写已 review 的 commit。
- 旧 writer 及其写入任务未确认停止时，不派发接替 writer，不恢复、还原、合并或清理其现场。

## 1. 读取事实并执行 preflight

controller 先确认宿主能力，解析 skill 和规则的绝对路径，按 controller 脚本入口执行 `prepare preflight`。使用返回的 primary、固定 branch/worktree 和证据目录，不预读 ticket/spec 正文。

preflight 默认 `gpt-5.6-terra` / `medium`；机械复查可用同模型 `low`，复杂恢复现场核对可用 `gpt-5.6-sol` / `medium`。

派发全新 preflight agent，交接 `prepare preflight` 生成的 dispatch 字段，并要求子 agent 先读取 `<skill-dir>/agents/preflight.md`。

按 controller 脚本的 `accept` 入口验收。阶段报告缺少可查询事实时，补齐再派发；接替沿用已有现场与已用轮次。`READY` 后使用报告的首次 `expected_children` 固定本批次范围，逐票 test mode/seams 用于 3.3 派发；boundary gates 用于 BASE smoke。controller 核对报告来源与结论一致，不重复全文读取所有 tickets/spec；缺证或冲突时只打开相关来源。

进入第 2 节前重新确认 `.beads` 无 diff，branch/worktree 的存在性、checkout 与未提交状态符合报告及恢复规则；状态变化时停止，不按旧建议继续。claim 仍是原子操作；后续 `graph.py next` 刷新并检查 children 集合。preflight 的 `READY` 不替代 install、BASE smoke 或 claim。

`BLOCKED` 不推进流程。工具链缺失时 controller 按 recipe 输出安装声明版本，再派新 preflight 复查；已获得首次 children 集合时将其作为 `expected_children` 一并传入，不重置范围。其他缺事实、冲突或失败沿用停止处理，不自动补写 ticket。

全部 direct children 已关闭时，先读取 `references/recovery-post-merge.md`，决定进入最终集成还是补全关闭/清理。

## 2. 创建或恢复 implementation worktree

已有 branch/worktree 或 preflight 建议恢复时，读取 `references/recovery-batch.md`；仅新批次执行以下初始化步骤。

1. 按 controller 入口执行 `update-main`；失败停止。
2. 将返回的 `main_commit` 作为初始化基线；`fetch_failed` 为 true 时把返回的 note 写入批次 comment。
3. 从更新后的 `main` 创建：

```bash
bd worktree create .worktrees/<parent-id> --branch implement/<parent-id>
```

4. 在新 worktree 中运行 `bd worktree info --json` 和 `bd where`，确认它属于当前仓库并共享 primary `.beads` workspace。
5. 在 implementation worktree 运行 `just install`；失败时停止。
6. BASE gate 冒烟：运行 `just env-facts` 和 `just smoke <boundary-gate>...`，boundary gates 为未关闭 children 的 `Boundary gates` 字段所列 recipe 的去重集合（`none` 不作为参数）。冒烟失败时保留现场并停止，报告失败命令与环境缺项；修复基线或补齐环境后重跑，通过前不派发 executor。
7. 使用 `bd update <parent-id> --claim --json` 领取 parent。
8. 给 parent 添加一条中文批次 comment，记录 branch、worktree、批次基线完整 HEAD SHA、`just env-facts` 输出与冒烟通过的命令和结果；写入成功后才能领取 child。

## 3. 串行 ticket 循环

### 3.1 选择 ticket

每轮调用只读脚本，传入 preflight 记录的完整 children ID 集合（逐个参数，不是逗号拼接）：

```bash
python3 <skill-dir>/scripts/graph.py next <parent-id> <expected-child-id>...
```

脚本刷新 children、比较批次范围、检查 labels 和状态，并沿用 `bd ready` 的依赖判断及默认 priority 顺序。按 `next` 处理：

- `resume`：恢复返回的 `ticket_id`。
- `claim`：确认旧 writer 及命令已结束，按 `references/controller-operations.md` 的 `sync-main` 入口同步本地 main 并验证基线。只处理本次固定 SHA，不 fetch。成功后按返回的刷新 frontier 处理；仍为 `claim` 才原子领取，竞争失败重新计算。同步失败执行停止记录，不领取新票、不消耗 ticket 修复阶段。
- `done`：所有 direct children 已关闭，进入第 4 节。
- `blocked`：按返回的 reason 和 IDs/unfinished 列表执行“停止记录”，不得进入最终集成。`reason: no_ready` 时可用 `bd ready --parent <parent-id> --explain` 获取依赖阻塞原因。

`resume`（包括中断接续和代码修复）保留原 BASE，不同步 main。用户可在 primary 编辑、暂存和提交；新提交由下一张新票吸收。executor/fixer 的源码写入仍限于 implementation worktree。

领取仍由 controller 执行，脚本不写 Beads：

```bash
bd update <ticket-id> --claim --json
```

### 3.2 建立恢复点

新 ticket 领取成功后，按 controller 脚本入口执行 `prepare executor`（`mode: new`，传入同步返回的 `sync_result`），脚本核对同步证据绑定当前 HEAD 后保存 dispatch、BASE 和证据路径。随后给 ticket 添加 start comment，记录 parent、branch、worktree、完整 BASE SHA 和 `sync_result` 路径；写入成功才派发 executor。

恢复 `in_progress` ticket 时，先读取 `references/recovery-ticket.md`，核实 BASE 后执行 `prepare executor`（`mode: resume`）。

### 3.3 派发 executor
每票最多四阶段：首次实现和三次修复。`prepare executor` 返回 `stage`（0..3）及 `models`；按 `models.executor` 显式派发全新 executor。模型矩阵由 `scripts/controller.py` 的 `STAGE_MODELS` 定义，准备命令直接输出可用配置，不为派发读取源码。跨模块状态、持久恢复或并发控制票传 `complex_ticket: true`；同一根因未收敛或契约分歧可按 controller 入口提前升级相关角色并注明理由。提高模型不消耗阶段，后续不降档。

每个 executor 只完成当前阶段的实现/修复、验证和至多一轮双轴 review，然后交还 controller。交付 gate 代码失败允许当前 writer 按 `references/verification.md` 使用最多三次就地修正机会；额度耗尽后交付候选仍有代码失败才结束当前阶段；TDD 的预期 red 属于正常实现。中断接续尚未完成的阶段，代码失败进入下一阶段；自动代码修复最多四阶段，每阶段的就地 gate 修正另按验证契约计数。

交接 3.2 生成的 dispatch 字段，要求 executor 先读取 `<skill-dir>/agents/ticket-executor.md`。controller 补齐 linked spec、已验证环境与冒烟证据、恢复事实及实际进度通信目标（若有）；续票环境事实来自批次与最近 completion comment。schema 按共享契约传路径。

开工基线已满足原计划行为、executor 请求适配模式时，读取 `references/baseline-adaptation.md`，由 controller 核准并记录执行计划，同一 executor 继续，不消耗阶段。

不复制 ticket 正文；executor 自行查询当前 ticket 和代码。按共享交付契约等待任务结束后验收。

### 3.4 验收 executor 结果

按共享交付契约保存原始回执，执行 controller 脚本的 `accept`，将机械验收记录保存在本轮证据目录。失败执行停止记录。

controller 按本票 mode 加载对应测试契约，核对实际验证覆盖、TDD 行为 red 与 seam 授权范围（机械字段校验不能替代）；另核对 acceptance 与实际代码、验证日志及原始 reviewer 证据的语义一致性，确认全部 commits 属于当前 ticket。确认 agent 误写 primary 时保留现场并停止，不自动还原。

需要补证时，controller 以 append-only 方式写 `acceptance-evidence-N.json`：`{"report_path": ..., "report_sha256": ..., "sources": [{"source": ..., "evidence": ...}]}`；补证不替代 executor 报告或 `PASS`。报告更正按共享交付契约处理，completion comment 引用原始、更正与补证文件。

处理 executor 状态：

- `DONE`：完成上述验收后进入 3.5，保留非阻塞 smells。
- `NEEDS_CONTEXT`：读取 `references/recovery-needs-context.md` 补齐事实并恢复。
- `BLOCKED`：读取 `references/recovery-blocked.md`。`outcome: code_failure` 且 `stage < 3` 时，核实失败为本票可修复代码问题，保留 `in_progress`，记录本阶段证据；确认旧 writer 已结束后，以 `continuation: repair` 准备下一阶段并回到 3.3。阶段 3 仍失败或存在外部阻塞时停止。机械验收失败按原规则停止，不进入代码修复。

### 3.5 完成 ticket

验收成功后：

1. 执行 controller 脚本的 `comment` 生成中文 completion，提供交付摘要和补证路径；核对生成的 test mode、seams、commits、验证、review、原始 smells 与证据后写入 ticket。
2. 用明确 reason 关闭 ticket：

```bash
bd close <ticket-id> --reason "<完成内容与验证摘要>" --json
```

3. 回到 3.1，重新计算 frontier。


## 4. 最终集成与 review

### 4.1 controller 准备现场

1. 用 `graph.py next` 和固定 children 集合重新确认结果为 `done`；范围变化或未全部关闭即停止。
2. 执行 controller 的 `update-main`；返回的 fetch fallback note 写入最终 `integration-ready` comment。
3. 使用返回的 `main_commit` 作为完整 `REVIEWED_MAIN` SHA，在 implementation worktree 将该 SHA merge 进当前 branch。冲突由 controller 加载 `resolving-merge-conflicts` 组织解决。
4. 确认所有先前 writer 及命令已结束，准备 finalizer 输入。

### 4.2 派发 finalizer

finalizer 默认 `gpt-5.6-terra` / `medium`；复杂证据整合可用 `gpt-5.6-sol` / `medium`。

执行 `prepare finalizer`，传入已合入的 `reviewed_main: REVIEWED_MAIN`，交接生成的 dispatch 字段，要求子 agent 先读取 `<skill-dir>/agents/finalizer.md`。controller 提供 ticket 证据和 completion pointers，汇总全部实际验证边界作为 `required_boundary_gates` 下限（脚本去重并排除 `final` 已覆盖的 `gate-unit` / `gate-full`），并交接实际进度通信目标（若有）。

`prior_finalization` 首次为 `null`；接替或重新运行最终集成时，先读取 `references/recovery-finalizer.md`。

finalizer 按自身指令在同一 attempt 中完成 stage 0 初次最终验证及最多三次代码修复（stage 1..3）。每阶段至多一轮双轴 review；stage 0 的 final/gate 代码失败跳过 review 并消耗当前阶段；stage 1..3 的 fixer 可按 `references/verification.md` 使用最多三次就地 gate 修正机会，额度耗尽后交付候选仍有代码失败才结束阶段；代码导致的完整 blocking review 或 fixer 的 `code_failure` 同样推进下一阶段。中断保留原阶段 BASE、已有 commits/dirty 现场和来源；不另设无进展计数。stage 3 未通过、或遇到环境/spec/seam 等非代码阻塞时停止。最终交付（包括 `BLOCKED`）的 stage report 按 finalizer 指令复制到 root dispatch 报告路径后，controller 才按共享交付契约执行 `accept`。

### 4.3 controller 验收

`READY_TO_MERGE` 才能进入第 5 节。除机械校验外，核对：

- gates 覆盖所有 ticket 声明及已验收报告中的实际验证边界，新增 gate 有来源；验证确在交付 HEAD 上通过。
- 报告与原始 reviewer 证据语义一致，smells 原样保留。
- fixer 的改动只处理本批次阻塞及相关问题，fix commits 均被最终验证和 review 覆盖，所有命令及子任务已结束。

通过后复用实测验证与 review，不重复运行 gates 或再开一轮 review。`BLOCKED` 按停止处理，parent 停止 comment 引用本次 dispatch、报告和证据路径；根因不明时读取 `references/recovery-diagnosis.md`。

## 5. 合入本地 main

最终 review 与语义验收通过后：

1. 执行 controller 脚本的 `comment` 生成 integration-ready，补充必要的 fetch fallback 记录，核对证据后写入 parent；写入失败停止。
2. 使用实际 comment ID 执行 `merge`，checkpoint 留在本轮证据目录。脚本复查 BASE/HEAD、干净状态与 comment 身份，再 fast-forward；仅 primary dirty 时恢复干净后重试，复用原验收；main 已移动时重新执行第 4 节。命令中断或失败后恢复前，读取 `references/recovery-merge.md`。
3. 仅 `merged: true` 后继续；`REVIEWED_HEAD` 使用脚本返回的 `reviewed_head`。

4. 给 parent 添加中文 completion comment，只记录已合入的 `REVIEWED_HEAD` 和对应 `integration-ready` comment 的 ID；完整验证、review 和 smells 证据通过该引用读取，不再复制。已有对应 completion comment 则复用。
5. 关闭 parent，并在中文 reason 中概括 children、验证和最终 review：

```bash
bd close <parent-id> --reason "<批次完成摘要>" --json
```

## 6. 安全清理

parent 关闭后，执行 controller 脚本的 `cleanup`，传入本次 merge checkpoint。脚本验证合入 ancestry、branch/HEAD、worktree 归属及干净状态后非强制清理，保留证据目录；已删除部分可重跑，失败停止。

历史批次缺少 checkpoint 时，读取 `references/recovery-legacy-cleanup.md`。

## 停止处理

前述检查失败或执行契约不满足时，保留现场，不继续领取 ticket，也不合入或清理。恢复执行先核实停止原因已解除和旧写入任务已结束，并保留既有证据。

### 停止记录

parent 已领取之后发生的实际批次停止（含 ticket 修复额度耗尽或外部阻塞、frontier 阻塞、最终 review 阻塞、状态不一致），controller 都必须先给 parent 添加一条中文 comment，至少记录：当前停止的流程原因、已完成进度、已确定的技术判断与剩余不确定性、推荐下一步及依据、恢复证据入口。只有用户决定会改变产品行为、范围或风险时才提出选择；不把可继续核对的技术问题包装成产品选择，也不因此越过修复额度继续实现。ticket 级 `BLOCKED` 的详情在该 child 的 comment，parent comment 只留指针。preflight 阶段（parent 尚未领取）的失败直接向用户报告即可。按 3.4 自动进入下一阶段或接续中断阶段时，只记录 child 的阶段证据，不写 parent 停止记录。

## 最终报告

向用户报告：

- parent ID 和关闭状态
- 按执行顺序列出的 ticket IDs 与 commit ranges
- 每票和最终验证命令的实际结果
- 每票和最终 review 结论
- 所有记录到 ticket 或 parent 的非阻塞 smells
- 本地 `main` 的最终 SHA
- worktree/branch 是否已清理
- 保留的证据目录路径（`<primary>/.worktrees/.evidence/<parent-id>/`，供审计，不随 worktree 清理删除）
- 明确说明 Git 和 Dolt 都没有 push

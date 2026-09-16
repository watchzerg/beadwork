---
name: beadwork-run
description: "串行实现一个 Beads parent 下的 ticket 依赖图，并在双层 review 后合入本地 main。"
---

# Beadwork Run

给定一个完整的 Beads parent ID，串行实现它的 direct child tickets。每个 ticket 使用一个全新的 executor 协调整票；其每个 stage 派发全新 implementer，同一时刻只有一个 writer。每张新票开工前按需同步本地 `main`；所有 children 完成后，把最新 `main` 合入 implementation branch，执行最终验证和 review，再 fast-forward 合入本地 `main`。

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

- controller 开始执行前读取 `references/testing-contract.md` 定位共享测试契约与项目事实；运行 BASE smoke 或核对最终覆盖前读取 `testing-gates.md`，遇到 TDD 交付矛盾需追查时读取 `testing-tdd.md` 和 `testing-seams.md`；计划缺证或冲突时读取 `testing-plan.md`，处理 seam 授权问题时读取 `testing-seams.md`。不预读出票模板或尚未触发的 TDD 细节。
- Beads 读取结构化结果使用 `--json`；未列出的命令语法按需查询 CLI 帮助。
- controller 将 `<skill-dir>` 解析为本 skill 的绝对目录。内置脚本使用 python3 ≥ 3.9（仅标准库），在待检查 repository/worktree 中运行；正常调用无需读取源码。stdout 为 JSON，非零退出按停止处理，不能当作空结果。executor 的命令采集入口另按 `references/verification.md` 区分验证失败（可核对 TDD red）、记录器异常和中断。
- 项目安装与验证经目标仓库的 `just` recipes 执行，recipe 检查由 preflight 负责。Beads 的 claim/comment/close 统一使用 controller-operations.md 的 tracker intent/读回入口。
- controller 派发前读取 `references/report-delivery.md` 与 `references/controller-operations.md`；后者定义准备、机械验收、comment 生成、合入和清理命令。

## 宿主能力

仅支持 Codex；其他宿主直接中止。假定下述模型均可用，派发时按就地规则显式指定 `model` 和 reasoning effort（参数名以当前工具声明为准）。ticket 按阶段 dispatch 的模型派发；报告更正沿用原模型组合，其他角色接替沿用原规则。

写入前确认当前宿主能创建独立 executor、执行内置双轴审查的两个并行只读 reviewers、接收完整报告并确认任务结束。需要支持 controller → preflight、controller → executor → implementer/reviewers、controller → finalizer → reviewers/fixer 的嵌套派发。能力不足时报告并停止。

controller 派发的 preflight、executor 和 finalizer 使用独立上下文（`fork_turns: "none"` 或宿主等价设置）；显式交接仓库规则入口、任务事实和证据路径。恢复时补充已有 commits、未提交现场、剩余工作与未解决 findings。

## 不变量

- controller 独占 Git/worktree 生命周期、ticket 选择、Beads 写入和最终集成；子 agent 对 Beads 只读。
- preflight/finalizer 只写证据；源码由当前 ticket implementer 或最终阶段的唯一 fixer 写入，只读研究与双轴 reviewers 可并行。
- 不 stash、不 reset、不 amend、不 squash、不 force-remove。
- review 后不改写已 review 的 commit。
- 旧 writer 及其写入任务未确认停止时，不派发接替 writer，不恢复、还原、合并或清理其现场。

## 1. 读取事实并执行 preflight

controller 先确认宿主能力，解析 skill 和规则的绝对路径，按 controller 脚本入口执行 `prepare preflight`。使用返回的 primary、固定 branch/worktree 和证据目录，不预读 ticket/spec 正文。

preflight 默认 `gpt-5.6-terra` / `medium`；复杂恢复现场核对可用 `gpt-5.6-sol` / `medium`。

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
7. 使用 tracker claim 领取 parent。
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

`resume`（包括中断接续和代码修复）保留原 BASE，不同步 main。用户可在 primary 编辑、暂存和提交；新提交由下一张新票吸收。implementer/fixer 的源码写入仍限于 implementation worktree。

领取由 controller 使用 tracker claim 执行；成功读回后才建立恢复点。

### 3.2 建立恢复点

新 ticket 领取成功后，按 controller 脚本入口执行 `prepare executor`（`mode: new`，传入同步返回的 `sync_result`），脚本核对同步证据绑定当前 HEAD 后保存 dispatch、BASE 和证据路径。随后给 ticket 添加 start comment，记录 parent、branch、worktree、完整 BASE SHA 和 `sync_result` 路径；写入成功才派发 executor。

恢复 `in_progress` ticket 时，先读取 `references/recovery-ticket.md`，核实 BASE 后执行 `prepare executor`（`mode: resume`）。

### 3.3 派发整票 executor

`prepare executor` 返回整票 root dispatch 和 `coordinator_model`；按该模型派发一个负责整张 ticket 的 executor，要求先读取 `<skill-dir>/agents/ticket-executor.md`。提供已验收 READY preflight 的 preflight_acceptance 来源绑定；交接 linked spec、已验证环境和冒烟证据、实际进度通信目标、规则与 schema 路径；不复制 ticket 正文。

executor 负责内部实现、阶段修复和双轴 review。controller 收到进度继续等待，只验收 root 最终交付；恢复沿用原 root，不重新授予额度。

### 3.4 验收 executor 结果

按共享交付契约确认 executor 及后代任务结束，保存原始回执，按 report-delivery.md 保存直接派发者的收尾观察，并带 --closure 执行 controller `accept`。脚本绑定 root、当前阶段、implementer 来源、BASE/HEAD、完整 commits、验证与原始双轴证据；失败停止，不把 implementer DONE 当成 ticket DONE。

controller 核对整票交付来源、最终状态、必要 gates 和最后 review 的 HEAD、现场与任务收尾事实；验收与报告有矛盾、缺证或越界迹象时打开相关源码/日志追查。test plan、TDD red、seams 和 acceptance 的日常语义验收由 executor 承担，不再逐 stage 重做。确认误写 primary 时保留现场并停止，不自动还原。

补证沿用 append-only `acceptance-evidence-N.json`，字段为 report_path、report_sha256 与 sources（source/evidence）；不替代原报告或 PASS。completion comment 引用原始、更正与补证来源。

- `DONE`：验收通过后进入 3.5，保留所有非阻塞 smells。
- `NEEDS_CONTEXT`：按 `recovery-needs-context.md` 补齐具体事实，恢复原 root。
- `BLOCKED`：按 `recovery-blocked.md` 保存停止与恢复入口。最终 code_failure 表示六阶段已用尽；controller 不再派下一修复阶段。中断保留原 stage、writer 现场和额度，非代码阻塞解除后恢复。

### 3.5 完成 ticket

验收成功后：

1. 执行 controller 脚本的 `comment` 生成中文 completion，提供交付摘要和补证路径；核对生成的 test mode、seams、commits、验证、review、原始 smells 与证据后写入 ticket。
2. 使用 tracker close 关闭 ticket，绑定成功 acceptance，reason 概括完成内容与验证；先确认 completion 已成功写入。

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

finalizer 自行管理最终验证、修复和 review；controller 等待 final-deliver 生成的 root 交付，包括 BLOCKED，并按共享交付契约保存收尾观察后执行 accept。中断与基线变化按 recovery-finalizer.md 区分，不自行重置 attempt。

### 4.3 controller 验收

`READY_TO_MERGE` 才能进入第 5 节。修复处置、验证覆盖和 review 的日常语义验收由 finalizer 负责；controller 除机械校验外，核对最终交付与集成条件：

- parent、固定 children 集合、`reviewed_main` 和交付来源属于本次批次。
- 最终 gate 范围包含交接的下限和 finalizer 确认的补充边界；必要验证与最后两轴 PASS 覆盖交付 HEAD，fix commits 和原始 review 证据来源完整。
- 现场满足集成条件，所有命令及子任务已结束，没有 blockers 或 remaining work，smells 已保留。

交付与现场有矛盾、缺证或越界迹象时，controller 打开相关源码、日志和原始 reviewer 证据追查；不逐 stage 重做 finalizer 的日常语义验收。

通过后复用实测验证与 review，不重复运行 gates 或再开一轮 review。`BLOCKED` 按停止处理，parent 停止 comment 引用本次 dispatch、报告和证据路径；根因不明时读取 `references/recovery-diagnosis.md`。

## 5. 合入本地 main

最终 review 与语义验收通过后：

1. 执行 controller 脚本的 `comment` 生成 integration-ready，补充必要的 fetch fallback 记录，核对证据后写入 parent；写入失败停止。
2. 使用实际 comment ID 执行 `merge`，checkpoint 留在本轮证据目录。脚本复查 BASE/HEAD、干净状态与 comment 身份，再 fast-forward；仅 primary dirty 时恢复干净后重试，复用原验收；main 已移动时重新执行第 4 节。命令中断或失败后恢复前，读取 `references/recovery-merge.md`。
3. 仅 `merged: true` 后继续；`REVIEWED_HEAD` 使用脚本返回的 `reviewed_head`。

4. 给 parent 添加中文 completion comment，只记录已合入的 `REVIEWED_HEAD` 和对应 `integration-ready` comment 的 ID；完整验证、review 和 smells 证据通过该引用读取，不再复制。已有对应 completion comment 则复用。
5. 确认 completion 已写入后，使用 tracker close 关闭 parent，绑定成功 merge checkpoint；reason 概括 children、验证和最终 review。

## 6. 安全清理

parent 关闭后，执行 controller 脚本的 `cleanup`，传入本次 merge checkpoint。脚本验证合入 ancestry、branch/HEAD、worktree 归属及干净状态后非强制清理，保留证据目录；已删除部分可重跑，失败停止。

历史批次缺少 checkpoint 时，读取 `references/recovery-legacy-cleanup.md`。

## 停止处理

前述检查失败或执行契约不满足时，保留现场，不继续领取 ticket，也不合入或清理。恢复执行先核实停止原因已解除和旧写入任务已结束，并保留既有证据。

### 停止记录

parent 已领取之后发生的实际批次停止（含 ticket 修复额度耗尽或外部阻塞、frontier 阻塞、最终 review 阻塞、状态不一致），controller 都必须先给 parent 添加一条中文 comment，至少记录：当前停止的流程原因、已完成进度、已确定的技术判断与剩余不确定性、推荐下一步及依据、恢复证据入口。只有用户决定会改变产品行为、范围或风险时才提出选择；不把可继续核对的技术问题包装成产品选择，也不因此越过修复额度继续实现。ticket 级 `BLOCKED` 的详情在该 child 的 comment，parent comment 只留指针。preflight 阶段（parent 尚未领取）的失败直接向用户报告即可。executor 内部自动推进 stage 时，只追加单票检查点并发送进度，不写 parent 停止记录。实际交还 controller 并停止批次时才写停止记录。

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

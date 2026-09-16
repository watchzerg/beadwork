# Ticket Implementer

你负责一张已领取 ticket 的当前 stage，实现代码并完成交付 gates。你是 implementation worktree 中当前唯一源码 writer；executor 协调整张 ticket、验收实现并组织双轴 review。你的成功仅表示可以进入独立 review，不表示 ticket 完成。

先读取 `../references/report-delivery.md` 和 `../references/ticket-execution.md` 的 implementer 交付部分。输入以 implementer dispatch 为准：ticket/parent、原始 `base_commit`、当前 `stage`/`stage_base`、模型、执行计划、approved seams、验证下限、规则/spec 来源及报告/schema 路径。恢复时另读 executor 交接的先前实现报告、dirty 现场和未解决 findings。

## 权限

- 源码、测试和必要文档只写指定 implementation worktree；只提交当前 ticket 的内容。
- 不创建/删除 branch/worktree，不 merge/rebase/reset/stash/amend/squash/push；Beads 只读。
- 不派发子 agent；不组织 review；不自行推进 stage、选择新模型或修改需求/seam 授权。
- 同 stage 的 gate-fix 留在当前上下文完成，必要时报告进度，不逐次等待 executor 批准。
- 计划适配交 executor 核准；等待期间暂停依赖该决定的修改。获得新 implementer dispatch 后，同一 agent 继续，保留已有工作与额度。

## 1. 建立上下文

确认能写入 `report_path` 并执行 implementer 完整自检；能力不足时在写入前返回 `BLOCKED`。依赖 skill 使用当前宿主的加载方式，读取当前步骤适用的引用文件。

读取 `../references/executor-operations.md`，执行 `inspect` 并读取返回的 ticket、comments、parent 和完整 description 文件。检查失败时保留证据，按缺事实或现场冲突返回对应状态；上游正文仍缺内容时返回 `NEEDS_CONTEXT`。Beads 需要刷新时仅使用 `bd show <id> --json` 和 `bd comments <id> --json`。

然后读取：

- `rules_paths`；按 `../references/testing-contract.md` 定位并读取 `testing-plan.md`、`testing-gates.md`，TDD 模式另读 `testing_seams_doc` 和 `testing-tdd.md`
- linked spec（若提供）
- repository 的 `CONTEXT.md` 和相关 ADR
- ticket 涉及区域的现有实现、测试和项目约定

`inspect` 检查 worktree、branch、BASE ancestry、ticket 状态和新票现场。

修复阶段先读取前阶段报告和 `prior_reviews`，归纳 blocking findings 破坏的不变量并修复共同根因；检查同一状态或资源交接涉及的调用方与直接相关分支。验证原失败被排除，同时保留正常完成或恢复能力。范围限于本票及修复直接影响的路径；复用已有覆盖，缺覆盖时才补测试，新增回归未实测 red 时注明构造依据。

如果是恢复执行，先检查现有未提交改动和 `base_commit..HEAD`，把它们视为本 ticket 的既有工作；executor 提供了已完成层清单时，先核对 `git log --oneline <base_commit>..HEAD` 与清单一致，不一致即报告。不要重做已经正确完成的部分。

## 2. 执行 test plan

输入模式使用原 Test plan 或 executor 明确交接的执行计划调整。Expected red 在开工 BASE 已满足、需要补覆盖或无提交完成时读取 `../references/baseline-adaptation.md`；部分已有的票对剩余行为保持 TDD。

- **TDD**：每个 `approved_seams` ID 必须解析到 linked spec（或作为 spec 的 parent）中 `Status: approved` 的 seam。加载并遵循 `tdd` 时，传入 seam ID、定义及“已在 spec 阶段由用户确认”；不要再次询问同一 seam。seam 变更边界按 `testing_seams_doc`、red 证据按 `testing-tdd.md` 执行；需要重新确认 seam 时返回 `BLOCKED`；报告记录实测命令、运行基线与断言失败原因，使用最小可加载骨架时附骨架差异和复现方式。
- **Direct verification**：ticket 必须给出 reason 和具体 verification。不要调用 `tdd`；执行声明的验证和项目 gates，不为制造 red 而新增 tautological test。

仅 TDD 模式使用 `tdd` 完成 red → green；其提及的后续 review 由上层 executor 承担，不自行派发 reviewer。

按 `testing-plan.md` 核对两种模式的必填字段，包括 `Boundary gates`。test plan 缺失、冲突或引用无效时返回 `BLOCKED`，不要自行改写 ticket。

## 3. 分层实现与验证

首次运行验证前读取 `../references/verification.md`。下列 `just` 验证命令通过该采集入口执行；实际 recipe 和参数仍按项目测试契约选择。

1. 从当前代码修复根因，实现 ticket 的全部 acceptance criteria。`complex_ticket` 涉及跨模块状态、持久恢复或并发控制时，先确定关键状态或资源由谁持有、何时交接、什么证据允许释放；不强制新增文档。
2. TDD 模式按 approved seam 做 red → green vertical slices；direct-verification 模式执行 ticket 声明的检查。两种模式都先按 `testing-gates.md` 运行最窄相关验证；direct verification 没有相关行为测试时执行声明的直接验证。
3. 处理 changed path 的真实边界：可见错误、数据完整性、资源清理、secret exposure 和 destructive operation。
4. 删除被 clean cutover 取代的旧代码、旧调用方和过时说明；不保留未要求的兼容层。
5. 编辑前读取目标上下文，编辑后核验实际 diff；匹配失败或结果不确定时，检查现场并重读后再修改，保留已有正确工作。
6. 按可独立验证的增量分层实现（小票可单层）；通过 typecheck 和相关验证所必需的生产代码、调用方及测试迁移放在同一层。每层依次完成 `just fmt <本层仍存在且适用的文件...>`（无适用文件时跳过）、diff 核对、实测 `just typecheck` 和覆盖本层的相关验证（不能以零匹配测试代替）、显式暂存，再按 `executor-operations.md` 执行 `check-layer`。确认本层可独立验证且机械检查通过后立即 commit，遵循第 4 节。验证后再修改源码时重跑受影响的验证。基线出现意外改动时保留现场，返回 `BLOCKED` 并报告路径与 diff 证据。
   有通信能力时向 executor 在层完成或阻塞时报告简短进度；最终报告包含完整验证和恢复信息。
7. 实现完成后运行：

```bash
just gate-unit
```

8. 运行 Test plan 声明的 boundary gates，并按实际影响补齐覆盖 changed boundary 的 `gate-*` recipe；选择规则见 `testing-gates.md`，实际范围以 justfile 及其调用脚本为准。新增 gate 的原因写入该次运行的 `verification_notes`；命令与退出事实由组装入口收集，供 executor 收集最终验证范围。

项目安装由 controller 负责；验证经仓库 `just` recipes 执行。多个验证 gate 默认串行运行；只有仓库契约明确保证资源隔离时才并行，recipe 内部的并行由 recipe 自己负责。交付所需验证必须通过；TDD red 的原始失败和后续重跑记录全部保留。

实现完成后的交付验证使用 `verification.md` 的 `--delivery`：代码失败时按该文件申请就地 gate 修正，每阶段最多三次，当前 implementer 集中修正、完成定向验证并提交，再验证修正候选。额度耗尽后交付候选仍有代码失败则返回 `BLOCKED / code_failure`；通过才向 executor 交付。开发中的 TDD red 和定向验证不消耗机会；环境或工具阻塞沿用 `outcome: blocked`。review 后的代码修复仍进入下一阶段。

## 4. 提交约束

本节约束第 3 节的分层提交和修复阶段的独立 fix commit，不要求分层提交之外再创建一次 implementation commit，也不为满足步骤创建空提交。

只提交当前 ticket 的代码、测试和必要文档。不得提交 `.beads` 文件或无关改动。

每次提交前执行 `check-layer`；commit message 必须包含完整 `ticket_id`、交付范围与验证状态。提交后核对实际完整 SHA 和提交内容。修复阶段有代码变化时创建独立 fix commit；验证要求同第 3 节。

不得假设 ticket 只有一个 commit；review range 始终使用 executor 提供的 `base_commit`。


## 5. 实现交付

使用 `ticket-execution.md` 的 `implementer-assemble` / `implementer-check`，由脚本生成 Git 身份、完整 commits 和验证记录；报告不能携带 review 或宣称整票完成。实际采集的失败、修复和成功记录全部保留。

- `DONE / passed`：本 stage 实现与必要 gates 完成，现场干净，acceptance 与 test plan 有证据，源码写入和命令已停止。
- `BLOCKED / code_failure`：三次 gate-fix 后交付候选仍有代码失败；不是开发中的预期 red。
- `BLOCKED / blocked`：环境、工具、需求、seam、证据或能力阻塞。
- `BLOCKED / interrupted`：预算或会话中断，保留已有 commits、dirty 现场、剩余工作和证据；不把代码失败改报中断。
- `NEEDS_CONTEXT / blocked`：缺少上层可以补齐的具体事实，在 requested_context 中列明。

收尾自己启动的命令，报告实际 `stopped_tasks`。无法确认停止时如实填 false 并说明；executor 不得因此派接替 writer。未完成代码保留现场，不为交付而提交未达到分层完成标准的内容。最终返回组装器生成的短回执。

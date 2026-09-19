# Beadwork 按阶段执行 gate 的改造方案

日期：2026-09-19。状态：已实施；本文保留历史方案与验收范围。

本文记录本轮已实施的设计决策与验收范围；实际运行契约以 skill 源码、共享测试契约和目标项目接入文档为准。

## 1. 目标、范围与实施规模

采用以下执行策略：开工做快速基线检查，实现过程中做定向行为验证，子票交付运行快速基础 gate 和相关的常规边界 gate，昂贵边界的完整回归集中到批次最终验收。

目标是减少完整 suite 的重复执行，同时保留本票行为证据和最终候选上的完整验证。正常无修复、无额外交付候选的批次，工作流只在 finalize 执行一次 `gate-full`。

本次实施范围仅为 Beadwork：

- 目标项目 gate 接口的声明、解析和调度规则。
- 初始化、票间同步、implementer 交付和最终验收之间的验证职责。
- 验证来源、报告验收、completion 说明及相应测试。
- skill 角色指令、共享测试契约和目标项目接入文档。

不修改 Grok、x-media-saver 或其他消费项目；不研究它们的测试内部实现；不顺带重构 Beadwork 自身维护用的根 `justfile`。消费项目在后续各自的 session 中按新接口接入。

用户已明确没有正在进行的 flow。直接切换新契约，不保留旧 `gate-plan` 格式、旧运行现场的续跑支持、双模式、迁移脚本、兼容参数或降级回退。历史证据原样保留，不扫描、修改或删除。

**规模判断：可在一个新的、专门实施此方案的 session 内完成。** 虽然涉及多个模块，但改动围绕一个小型声明和两个调度规则展开，不需要新工作流引擎。第 9 节列出 7 个顺序 task；它们不是 7 个 session。应在一个 session 中完成契约、调用方、测试和文档的一致切换，不把半成品当作可用版本交付。

## 2. 当前行为与优化依据

当前源码的主要事实：

| 位置 | 当前行为 | 本次处理 |
| --- | --- | --- |
| `agents/preflight.md`、`scripts/preflight_operations.py` | 只读检查工具链、recipes、计划与票据；不执行产品测试 | 保持 |
| `scripts/batch_initialize.py` | 新 worktree 执行 `install`、`env-facts`、`gate-full` | 全量改为快速基线 |
| `scripts/main_sync.py` | 新票前真正合入 main、改变 HEAD 后运行全量；没有变化只读计划 | 有变化时改为快速基线 |
| `agents/implementer.md`、`scripts/implementer_reports.py` | 本票交付必须完整运行 core 和全部必要边界 | 按计划区分本票必跑与最终完整回归 |
| `agents/ticket-executor.md` | 验收已有证据，不重复跑同 HEAD 的 gates | 保持并明确延期语义 |
| `scripts/final_verification.py`、`references/final-execution.md` | 最终干净候选必须有一次完整成功的 `gate-full` | 保持 |

当前 `gate-plan` 只能表达 `core` 和 `full`。`required_boundary_gates` 同时表达影响范围和本票完整运行义务，无法声明“本票先证明相关行为，完整慢回归由 parent 最终验收承担”。

用户提供的 Grok 耗时为：core 1.22 秒、artifact 9.96 秒、database 35.58 秒、browser 231.91 秒、system 175.47 秒、full 约 454.13 秒。它们仅用于收益估算，未在本轮重新测量。

- 两次固定全量约 15 分 08 秒。
- 开工全量换为 core，每个新批次约省 7 分 33 秒。
- browser 与 system 合计占全量耗时约 89.7%；重复完整慢回归是下一项主要成本。
- 若两张票都声明 browser 和 system，当前固定 gate 成本约 28 分 45 秒；新策略的基础部分约为 7 分 38 秒，再加本票定向验证和相关常规边界 gate。此估算不包含安装、推理、review、失败重试及外部环境开销。

## 3. 新的项目 gate 契约

### 3.1 保留现有 recipe，增加一个调度字段

目标项目继续提供 `gate-plan`、`gate-core`、`gate-full` 和实际存在的 `gate-<boundary>`。保留 `check-toolchain`、`install`、`env-facts`、`typecheck`、`test [ARGS...]`、`fmt [FILES...]` 等配套接口。

`gate-plan` 严格输出以下三个字段：

```json
{
  "core": "gate-core",
  "full": [
    "gate-core",
    "gate-artifact",
    "gate-database",
    "gate-browser",
    "gate-system"
  ],
  "defer_to_final": [
    "gate-browser",
    "gate-system"
  ]
}
```

此示例说明接口，不表示已审查或修改 Grok 的实际测试。没有昂贵边界的项目显式输出 `"defer_to_final": []`。

字段规则：

1. 对象必须恰有 `core`、`full`、`defer_to_final`，不接受缺省字段或额外字段。
2. `core` 固定为 `gate-core`，并且是 `full` 成员。
3. `full` 是非空、唯一、有序的真实 gate 列表；沿用现有 recipe 存在性、未登记 gate 和保留入口检查。
4. `defer_to_final` 是唯一的字符串列表，可以为空；每项必须属于 `full` 中的非 core 边界。
5. `gate-plan`、`gate-full` 和 `gate-core` 均不能出现在 `defer_to_final` 中。
6. `full` 决定实际运行顺序；`defer_to_final` 仅表达集合，不独立决定执行顺序。
7. `gate-plan` 保持只读，不安装、不测试、不探测数据库或浏览器服务。
8. `gate-full` 始终执行完整 `full`，不得因为 `defer_to_final` 而跳过任何成员。

不增加 `gate-medium`、`gate-heavy` 或 `gate-smoke` 聚合入口，不建立重复的成员清单，也不把聚合 gate 与其子 gates 同时登记为独立 full 成员。

### 3.2 轻、中、重的统一职责

| 层次 | 契约职责 | 调度方式 |
| --- | --- | --- |
| 轻：`gate-core` | 静态检查及快速隔离基础回归；不启动真实数据库或浏览器服务 | 快速基线和每票交付必跑 |
| 常规边界：未列入 `defer_to_final` 的非 core gate | 可按票支付成本的独立边界完整 suite | 仅在本票涉及该边界时完整执行 |
| 昂贵边界：列入 `defer_to_final` 的 gate | 完整运行成本高的独立 suite | 完整回归默认延后；相关行为仍需本票验证 |
| 全量：`gate-full` | 项目的完整回归集合 | 最终交付候选执行 |

分类由项目声明，不按 database、browser 等名称硬编码，也不根据运行耗时动态跳过。项目可根据实测成本调整分类；Beadwork 不维护每台机器的耗时阈值、风险评分或历史性能数据库。

项目需说明 `test` 支持哪些 suite、路径或场景筛选。定向测试必须实际收集相关用例，零匹配不能表示通过。完整 gate 继续拒绝筛选参数。某边界不能收窄时，执行必要的完整边界 gate，不自动扩大成整个 `gate-full`。

### 3.3 单一纯函数计算默认义务

在现有 `gate_plan.py` 中集中解析、schema 和选择逻辑，不新增调度框架。令：

- `B` 为当前 ticket 累计的 `required_boundary_gates`。
- `D` 为候选计划的 `defer_to_final`。
- `R` 为本票默认完整 gate 义务。

```text
R = {gate-core} ∪ (B − D)
延期的完整边界 = B ∩ D
最终义务 = 一次完整 gate-full
```

输出列表统一按 `full` 的顺序排列。选择前检查 `B` 全部属于已登记的非 core 边界，不静默忽略未知名称。

解析、preflight schema、验收和 completion 生成应复用这份定义及选择函数，不在各角色提示词或多个 validator 中各写一份集合算法。

## 4. 各阶段执行顺序

| 阶段 | 新的执行规则 |
| --- | --- |
| preflight | 保持只读，验证新计划结构和 ticket Test plan；不运行产品 gate |
| 批次初始化 | worktree/workspace 检查 → `install` → `env-facts` → `gate-plan` → `gate-core` → parent claim/comment → ready |
| 新票同步，没有合入变化 | 保持只读 `gate-plan` 绑定；不运行 core 或 full |
| 新票同步，HEAD 因合入改变 | 按安装输入变化决定 `install` → `env-facts` → `gate-plan` → `gate-core` |
| 恢复当前票 | 保留 BASE、现场、阶段额度和既有验证；不重新初始化或同步 main |
| implementer 开发 | 本层 `typecheck` 与最窄相关行为验证；TDD 按实际模式执行 red/green |
| implementer 提交交付候选 | 干净 HEAD 上执行 `R`；必要的提前完整边界验证按第 5 节处理 |
| executor / reviewers | 检查实测来源、行为和覆盖，不为验收再次执行同候选 gates |
| 最终同步 | 保持按需安装及环境准备，gates 由 finalizer 执行 |
| finalizer stage 0 | 最终干净候选执行一次完整 `gate-full`，通过后 review |
| fixer | 定向修复并提交，再对新最终候选执行完整 `gate-full` |
| controller 最终验收与合入 | 复用已验收最终证据，不额外运行 gate |

初始化新增的 `gate-plan` 必须从安装后的 implementation worktree 读取并机械校验，保留实际输出与来源。不能只把运行成功但结构无效的 JSON 当成计划通过。依赖现有步骤记录和来源绑定实现，不新增缓存系统。

初始化 comment 改为“依赖与环境准备完成，快速基线 gate-core 通过”；不再写“BASE 全量通过”。同步结果及其校验使用新命令序列，不能只修改执行端而让 ready 验收仍等待 `gate-full`。

已有的恢复规则继续作用于新命令序列：同一初始化 intent 的有效成功步骤可复用，上游重新执行后下游必须重新验证；未知或中断的进程先确认收尾，再追加尝试。这里保留的是新流程的恢复能力，不是历史格式兼容。

## 5. 本票行为验证与提前运行边界

### 5.1 延后完整 suite，不延后本票验收依据

`Boundary gates` 继续声明本票影响及最终覆盖义务。列入 `defer_to_final` 的边界仍必须出现在 ticket、dispatch、checkpoint 和最终累计范围中。

本票要证明其 acceptance criteria：

- TDD 模式保留相关行为的 red/green 和 approved seam 约束。
- Direct verification 模式执行已声明的具体检查或场景。
- 修改真实数据库事务、浏览器恢复、跨进程交接等行为时，选择实际能观察该行为的验证。隔离测试能证明的范围与真实边界测试能证明的范围分别记录。
- 对应定向测试无法运行或未覆盖目标行为时，不能仅凭 core 通过关闭该票。
- 如果目标行为只有完整昂贵 gate 能证明，就在本票提前执行该 gate。若它依赖后续票尚未交付的能力，应修正拆票或明确验收边界，不能伪造本票完成。
- Test plan 明确要求本票执行完整边界 gate 时，该具体要求仍需执行；项目的默认延期声明不覆盖显式验收要求。

不增加 ticket 文本字段或解析自由文本命令的新语法。具体行为验证及提前运行理由继续通过现有 Test plan、acceptance、verification 和 verification_notes 交接，由 executor 检查语义。

### 5.2 提前运行的完整交付 gate 不能失败后被忽略

定向开发验证继续使用 `test`，允许 dirty 工作区，保留正常 red/green 历史。

本票提前执行的完整边界交付验证使用现有 `--delivery`，保持干净候选及修复额度语义。除了 `R`，当前 implementer 逻辑 stage 内已尝试的完整边界 delivery gates 也必须在该 stage 最终交付 HEAD 上通过；同 stage 恢复或计划适配不能遗失这些记录。

这组额外义务直接从已绑定的运行记录推导，不新增 `force_gates`、`early_gates` 持久字段或审批流程。新增实际边界仍并入 `required_boundary_gates`，由已有累计链传播。

例如：browser 虽可默认延期，但本 stage 已运行其 delivery gate 且失败，就不能只补跑 core 后返回 DONE。修复并提交后需让 browser 在当前候选通过。提前完整运行通过后又修改候选，也需重新证明本 stage 已承担的完整交付义务。

跨 stage 的未解决失败继续由既有 findings、修复交接及验收语义处理；不能通过新 stage 或修改分类让已知问题消失。开发中的预期 red 不因此变成交付 gate 义务，也不消耗交付修复额度。

`gate-full` 不作为正常单票交付入口或子 gate 证据的隐式替代；正常票据流程不提前跑全量。最终全量仍由 finalizer/fixer 的现有入口负责。

## 6. 验证证据、计划绑定和完成语义

### 6.1 保留已有来源链，只改变本票成功条件

继续保留 HEAD、dirty 状态、命令参数、退出结果、来源 hash、验证日志、任务收尾和 append-only 历史。完整交付 gate 必须属于同一干净候选，所有用于该次成功验收的 gate 计划必须一致，并包含新字段。

本票验收以交付运行记录中绑定的候选 `gate-plan` 为准；本票必跑的 core 提供必需的计划来源。preflight 或开工 dispatch 的计划用于基线事实，不能代替已修改项目在交付时的实际计划。这样仍允许以修改测试框架为目标的 ticket 正常交付。

同一候选的成功 gate 不得混用不同 `defer_to_final` 定义。若项目 gate 定义随源码变化，应在新候选重新采集相关交付证据。历史报告只按其原来绑定的来源验证，不执行当前 checkout 的命令去重新解释历史。

`required_boundary_gates` 始终表示累计覆盖范围；成功检查改为计算本票的必跑集合，不再要求其中每个边界在每票都完整执行。不能通过删除 deferred 边界获得成功。

无需新增与 `required_boundary_gates` 平行的持久延期清单，也无需让模型填写调度结果。已运行、必跑和等待最终完整回归的摘要，由脚本从报告绑定的计划、累计边界及实测结果推导。

部分 BLOCKED 报告可能尚无有效交付计划或 core 记录。允许如实交付已有证据并注明尚不能计算成功覆盖；不得为凑摘要额外运行 gate、采用缺省计划或伪造通过。

### 6.2 Ticket DONE 与 parent 完成

Ticket DONE 的含义是：本票行为与该阶段必需验证通过，review 通过，相关昂贵边界的完整回归由 parent 最终验收承担。

Completion comment 至少明确：

- 本票要求的完整 gates 及其在交付候选上的实际结果。
- 本票定向行为验证的既有证据引用。
- 尚待 parent finalize 完整验证的边界；已经在当前候选完整通过的边界不误写成“尚未验证”。

它不改变 Beads 状态模型，不增加“半关闭”状态。Child 可以按新语义关闭；parent 只有在最终完整 `gate-full` 和 review 通过后才能完成。最终发现问题仍走现有 finalizer/fixer 机制，不重新开启所有 children。

最终累计义务仍为全部 tickets 的声明及实测补充边界。最终计划缺少某个累计边界时拒绝验收；`defer_to_final` 只影响中间调度，不削减最终覆盖。

### 6.3 最终验证与恢复保持简单

最终成功依然要求一次完整、无筛选参数、在最终干净 HEAD 上通过的 `gate-full`。不拼接不同候选或不同 full 尝试的成功片段。

- 最终失败后，完成定向诊断和必要修复，再从 `gate-full` 入口验证。
- 同一有效候选的完整成功可以按现有流程复用；更晚失败或无效验证的失效规则保持。
- 不增加跨批次结果缓存、环境指纹、按文件自动选测试或全量断点续跑。
- 不减少 review 轮次、不改模型政策、不改 gate-fix/stage 额度、不改变唯一 writer 和 Git/worktree 布局。

直接更新现有 `workflow_contract.VERSION` 为下一版，并更新当前测试构造。使用已有版本检查拒绝不匹配现场即可；不新增第二套 gate 版本机制，不实现旧版读取或迁移。

## 7. 代码与文档修改地图

下表是改动和核查入口；只有行为受影响的文件才修改，不为覆盖清单机械改动无关模块。

| 范围 | 主要文件 | 实施内容 |
| --- | --- | --- |
| 计划定义与准入 | `scripts/gate_plan.py`、`preflight_operations.py`、`phase_validation.py` | 三字段计划、共享 schema、集合规则和选择函数 |
| 批次开工 | `scripts/batch_initialize.py` | 安装后计划读取与绑定、core 基线、comment 与恢复顺序 |
| main 同步 | `scripts/main_sync.py`、`handoff.py` | 改变 HEAD 后运行 core；同步结果验收与交接一致 |
| 单票交付 | `scripts/implementer_reports.py`、`ticket_verification.py`、`run_verification.py` | 当前计划下的必跑集合、提前 delivery 义务及成功来源检查 |
| 票据传播与说明 | `scripts/ticket_execution.py`、`ticket_state.py`、`ticket_reports.py`、`controller.py`、`batch_evidence.py` | 边界完整继承、来源绑定、completion 实测与延期摘要 |
| 最终验收 | `scripts/final_verification.py`、`finalization.py`、`worker_validation.py` | 支持新计划且保留完整 full 验收；确认未丢累计边界 |
| 当前现场版本 | `scripts/workflow_contract.py` 及相应 fixtures | 单次直接切换，不添加兼容分支 |
| 角色指令 | `SKILL.md`、`agents/preflight.md`、`implementer.md`、`ticket-executor.md`、`reviewer.md`、`finalizer.md`、`fixer.md` | 新的基线、交付职责和完成语义 |
| 共享规则 | `references/testing-gates.md`、`testing-plan.md`、`testing-contract.md`、`verification.md`、`ticket-execution.md`、`controller-operations.md`、相关恢复规则 | 统一命令、延期范围、证据和恢复说明 |
| 接入说明 | `docs/project-contract.md`、`docs/ARCHITECTURE.md`，必要时 README | 新项目接口与总体职责，正文不复制完整执行协议 |

表中 `scripts/`、`agents/`、`references/` 均位于 `skills/beadwork-run/`。历史设计文档保留其历史叙述，不全仓替换所有 `gate-full` 字样；只清理现行契约中的过时要求。特别注意最终验收和维护仓库交付前的 `gate-full` 必须保留。

## 8. 测试与验收标准

### 8.1 必需回归场景

| 场景 | 期望 |
| --- | --- |
| 新计划合法，延期集合为空或非空 | 正确解析并按 full 顺序选择 |
| 缺字段、未知字段、重复 gate、不存在 recipe、非法延期成员 | 拒绝，不回退旧格式 |
| 本票涉及 database 和 browser，仅 browser 延期 | core 与 database 必跑，browser 保留最终义务 |
| 本票只涉及 deferred 边界 | 可凭 core、有效定向行为证据及 review 完成本票，不伪造完整边界成功 |
| 丢失 core 或本票常规边界的成功证据 | 拒绝 DONE |
| 提前 deferred delivery 失败后仅 core 通过 | 拒绝 DONE；该完整边界在交付 HEAD 通过后才可继续 |
| 同 stage 恢复、计划适配和修复提交 | 不遗失已承担的 delivery 义务；旧 SHA 不能替新候选背书 |
| 同候选混用不同延期计划 | 拒绝成功验收 |
| 测试框架 ticket 正常修改候选计划 | 使用候选实测计划验收，保留旧来源且不误用开工计划 |
| 新批次初始化 | 明确断言 install/env-facts/gate-plan/core 顺序，不运行 full |
| 初始化遇到无效计划、core 失败或中断 | 不 claim；新流程恢复保留来源及下游失效规则 |
| 新票 main 无变化、有代码变化、有安装输入变化 | 分别只读计划、环境/计划/core、安装/环境/计划/core |
| final-sync | 仍不运行 gates；最终 full 仅由最终角色负责 |
| 两票累计 deferred 和新发现边界 | stage、controller、finalizer 交接均不丢义务；最终 full 完整覆盖 |
| completion 说明 | 不将 deferred 未运行项写成已通过，不将已实测项写成未验证 |
| 最终只有 core、拆开的子 gates 或筛选结果 | 拒绝 READY_TO_MERGE |
| 最终完整 full 通过、失败、中断或来源损坏 | 保留现有正确验收与停止行为 |

对默认双票正常路径增加一条完整 workflow 回归：使用能记录命令的受控项目 fixture，证明初始化 core、两票按计划交付、最终一次 full，以及验收与合入没有额外 full。Fixture 的 full 应真实调用所声明的成员，以核对 deferred 边界最终仍被执行；不启动真实 Chrome 或 Docker。

语义验收无法靠脚本证明“某个定向测试足够”。相应测试应验证证据传递及拒绝明显缺证，文档明确由 executor/reviewer 检查实际行为覆盖，不增加虚假的自动覆盖证明。

### 8.2 验证安排

纯解析和集合选择使用 unit；真实文件、命令记录、CLI/schema 入口使用 integration；初始化、票间同步、交付、恢复与最终集成的产物衔接使用 workflow。新增或修改测试遵循根 AGENTS.md 的单一主 marker 规则。

任务内运行受影响的最小 suite，不因每完成一个 task 就运行一次全量。所有实现、fixtures、文档收敛后运行一次：

```sh
just gate-full
```

该门禁针对 Beadwork 源码仓库，不等同于消费项目的 `gate-full`。按失败原因修复后再做必要验证；不把本轮优化理解为取消 Beadwork 跨模块协议改动的完整门禁。

本地 fixtures 证明机械调度和证据衔接，不证明真实 Beads workspace、真实 Codex 派发或真实 Grok browser/system 测试通过。最终交付如实列明这些未验证范围，不在本实施 session 自动启动真实消费项目批次。

## 9. 单 session 实施任务

本轮已在同一 session 完成七项任务，未建立额外执行账本：

后续 review 修复了初始化及同步解析混入 stderr、初始化无效计划被复用、未落盘 delivery 结果丢失边界义务的问题。双票回归已改为串联初始化、两次票间同步、两票实现交付与 review、manifest、最终同步、finalizer 和 controller 验收的公开 CLI 路径；该回归进一步发现并修复 manifest 未读取 root 报告绑定的 stage/implementer 边界来源的问题。测试覆盖两票不同声明边界及实现时新增的补充边界，保留来源 hash 校验；Beads 状态、产品 recipes 和 agent 报告仍使用本地 fixtures，不代表真实外部验收。

| Task | 完成结果 |
| --- | --- |
| 1 | 三字段计划、严格 schema、统一选择函数和 workflow 契约 v2 已生效 |
| 2 | 初始化与改变 HEAD 的票间同步已切换为 `gate-core` 快速基线 |
| 3 | implementer 已按候选计划计算必跑集合，并保留本 stage 已尝试 delivery gate 义务 |
| 4 | 累计边界、completion 实测/延期摘要和最终 `gate-full` 验收已打通 |
| 5 | 现行 skill 角色、共享契约、恢复说明与项目接入文档已同步 |
| 6 | 解析、初始化/同步、单票延期/提前义务、completion 及默认双票命令轨迹回归已补齐 |
| 7 | diff、旧契约残留、marker 与完整 `just gate-full` 按本文要求验收；实际结果记录在本次交付说明 |

### Task 1：实现三字段计划和统一选择规则

更新 `gate_plan.py`、preflight schema/验证以及现有计划 fixtures，加入 `defer_to_final` 的严格检查和统一的本票 gate 选择函数。直接提升现有 workflow 契约版本，更新当前构造，不引入兼容入口。

验收：合法空/非空延期集合能得到正确顺序；非法计划明确失败；preflight 仍没有产品测试副作用。运行相关 unit 和 preflight/schema integration。

### Task 2：将初始化和票间同步切换为快速基线

初始化读取并绑定安装后计划，执行 core；同步有变化时执行 core，无变化和 final-sync 保持原有轻量路径。同步更新 ready 检查、初始化 comment 和恢复命令序列。

验收：命令轨迹不含开工 full；core 或计划失败不会推进 claim；失败/中断恢复不复用失效下游成功。运行 batch/main-sync 相关 workflow。

### Task 3：修改 implementer 成功验收

以候选计划计算本票必跑集合，保留全部边界下限；从当前 stage 的 delivery 记录推导额外完整 gate 义务。统一计划、HEAD、结果与来源校验，保留 dirty 开发验证和部分 BLOCKED 报告。

验收：core 加常规边界即可满足机械 gate 条件；deferred 未运行不自动失败；缺必跑项、提前运行失败、混用计划和旧候选证据都不能通过。运行相关 unit、run-verification integration、ticket/gate-repair workflow。

### Task 4：打通累计边界、completion 和最终验收

核对 stage、root、controller 和 finalizer 的全部交接，保证延期边界仍在累计范围。Completion 从绑定来源生成“已实测／待最终完整回归”说明，不新增持久延期账本。最终继续以完整 full 验收。

验收：两个 ticket 的不同边界能累计到 parent；补充边界不会丢失；最终缺边界、缺 full 或来源损坏时拒绝；child 与 parent 的完成语义不混淆。运行 controller/finalization 相关 workflow。

### Task 5：更新现行 skill 和项目接入文档

同步第 7 节涉及的角色、共享规则和恢复说明。明确 core 基线、定向行为证据、默认延期、必要提前运行、失败处理和最终完整验证。提供新计划 JSON 示例及消费项目改造要求。

验收：现行规则不再要求 BASE full 或每票全部完整边界；最终 full 仍要求执行；没有新增模型机械抄写义务、兼容说明或多套策略开关。运行文档检查及必要的 CLI 契约测试。

### Task 6：完成双票工作流与契约回归

补齐第 8 节的关键矩阵，优先扩展现有测试和 fixtures。增加一个默认双票路径的命令轨迹验收，证明重边界完整回归在 finalize 执行，既未在中间重复，也未从最终 full 消失。

验收：相关 integration/workflow 通过；新三字段计划在公开 CLI 与独立分发环境中均可用；不通过新增大型 fixture 框架来验证少量调度规则。

### Task 7：完整验证和交付说明

核对 diff、现行引用、测试 marker 和旧契约残留；运行 Beadwork `just gate-full`。在交付说明中记录实际验证结果、默认双票命令计数及未做的真实外部验收。

验收：实现、测试和文档一致；没有用户未要求的消费项目变更或 Git/Beads 发布。更新本文状态及 task 完成情况，不另建重复的执行账本。若没有进一步明确授权，不自动 commit、push 或创建 Beads tickets。

## 10. 消费项目后续接入要求

Beadwork 实施完成后，尚未输出三字段计划的消费项目会在 preflight 明确失败。这是本次直接切换的预期结果；应先完成该项目接入，再启动新的 Beadwork 批次。

每个消费项目在自己的 session 中完成：

1. 按实际成本和验证能力设置 `defer_to_final`；不根据 recipe 名字自动分类。
2. 确认 core 只包含快速隔离验证，常规边界是独立完整 suite，full 仍一次完整执行全部成员。
3. 提供并记录真实可用的定向 `test` 入口；验证相关测试被收集、零匹配失败及失败退出码传播。
4. 更新本项目 AGENTS.md/Test plan 指引，使其符合新的子票与 parent 完成语义；显式全量要求只保留在实际需要的位置。
5. 用项目自己的验证证明新入口有效，记录实际耗时与收集范围。不要把本方案中的 Grok 示例当成已完成的测试归类审查。

本节是后续项目接入说明，不属于第 9 节 Beadwork 实施 session 的修改范围。

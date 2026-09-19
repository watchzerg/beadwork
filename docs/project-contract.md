# 目标项目接入契约

本文是现有或新项目接入 `beadwork-run` 的规范性入口，面向负责建立项目工具链、测试边界和工作流接口的维护者。Beadwork 源码仓库的维护规则见根目录 [AGENTS.md](../AGENTS.md)；执行期间的角色协议由 skill 自带的 `references/` 维护。目标项目不需要采用 Beadwork 源码仓库的语言或工具链。

接入可以分步完成，但只有满足本文全部阶段的项目才能运行完整 `beadwork-run`。仅完成测试与验证契约，表示项目已有可复用的验证接口，不表示 Beads、Git/worktree 或 ticket graph 已经就绪。本文的“接入阶段”表示项目接入成熟度，不是工作流内部的 ticket stage 或 final stage。

## 接入阶段

| 阶段 | 目标 | 完成后的能力 |
| --- | --- | --- |
| 1. 测试与验证 | 提供稳定、可定向、可完整执行的 just 接口 | 可供人工或其他 agent 统一调用，但尚不能单独运行 `beadwork-run` |
| 2. 本地发现与 Git/worktree | 安装 skill 入口并满足隔离实现和本地集成要求 | Codex 可从项目发现 skill，工作流可建立 implementation worktree |
| 3. Beads 与 ticket graph | 提供 tracker、parent/children、依赖、执行顺序和 Test plan | 工作流具备可执行输入 |
| 4. 完整接入验收 | 联合检查前三阶段以及项目自身完整 gate | 可以启动新的 `beadwork-run` 批次 |

## 阶段 1：测试与验证契约

### justfile 接口

目标项目提供下列入口。当前 preflight 的必需名称清单见 [preflight_operations.py](../skills/beadwork-run/scripts/preflight_operations.py) 的 `RECIPES`；具体调用方式见 skill 内的执行指令。

| Recipe | 职责与调用约定 |
| --- | --- |
| `check-toolchain` | 检查项目声明的工具链；缺失或不符合要求时明确失败 |
| `install` | 按项目锁定输入安装依赖，可重复执行 |
| `typecheck` | 执行项目权威类型检查或等价静态检查 |
| `test [ARGS...]` | 运行相关测试；支持项目明确声明的 suite、路径、node ID、名称或场景筛选 |
| `gate-plan` | 无参数、只读输出严格三字段 JSON：`core`、有序 `full` 和 `defer_to_final`；不安装依赖、运行测试或探测外部服务 |
| `gate-core` | 无参数执行静态检查及快速隔离的基础回归；必须是 `full` 成员 |
| `gate-full` | 无参数按 `gate-plan.full` 的顺序逐项完整执行，每项一次、首错停止 |
| `env-facts` | 输出用于检查与交接的环境事实，不输出凭据 |
| `fmt [FILES...]` | 格式化指定文件；遵循项目自己的参数约定 |
| `gate-<boundary>` | 按项目的真实 suite 提供额外边界验证，由 Test plan 引用 |

这些是行为接口，不要求使用某个具体 test runner、formatter、编程语言或固定 gate 名称。项目应先盘点真实测试、依赖和故障边界；没有独立 suite 时不创建空 gate，也不为模仿其他项目而虚构 database、browser 等分类。

所有声明的入口都必须传播真实失败：测试零匹配、未收集、导入失败、依赖缺失、环境准备失败、空命令或占位 recipe 不能代表通过。完整 gate 均拒绝筛选参数；收窄验证只走 `test`。项目源码、justfile 及其调用脚本是实际命令、收集范围和运行环境的事实来源。

### `gate-plan` schema

`gate-plan` 输出一个且仅一个 JSON object，对象必须恰好包含：

- `core`：固定为 `gate-core`，且必须属于 `full`。
- `full`：非空、唯一、有序的真实完整 gate 列表；顺序也是 `gate-full` 的执行顺序。
- `defer_to_final`：唯一、可为空的列表；每项必须是 `full` 中的非 core boundary gate。

除保留入口 `gate-plan`、`gate-full` 外，每个实际存在的 `gate-*` recipe 都必须在 `full` 中登记且只出现一次。`gate-plan`、`gate-full` 和 `gate-core` 不能出现在 `defer_to_final` 中。

以下仅为结构示例，不是要求所有项目照搬这些边界：

```json
{
  "core": "gate-core",
  "full": ["gate-core", "gate-database", "gate-browser"],
  "defer_to_final": ["gate-browser"]
}
```

没有独立 boundary suite 的项目可以只声明 `full=["gate-core"]` 和空的 `defer_to_final`。是否延期某个 boundary 应依据项目的实测成本、定向验证能力和风险作出决定，不能仅按 gate 名称或是否使用 Docker、浏览器等工具自动分类。

### 调度与验证语义

- 初始化和 main 改变后的同步运行 `gate-core`；main 无变化时只读绑定 `gate-plan`。
- 单票始终运行 `gate-core`，并完整运行本票涉及且未列入 `defer_to_final` 的 boundary gates。
- deferred boundary 仍是本票影响范围和最终覆盖义务。本票必须提供能实际观察目标行为的定向证据；只有完整 boundary gate 能证明时，仍需在本票提前执行它。
- `gate-full` 始终执行 `full` 的所有成员，不因 `defer_to_final` 跳过任何 gate。
- parent finalize 在最终干净候选上执行一次无筛选参数的完整 `gate-full`。

更细的 Test plan、TDD、boundary 选择和证据规则由随 skill 分发的共享契约维护：

- [testing-seams.md](../skills/beadwork-run/references/testing-seams.md)：spec 中的 seam 定义和变更授权。
- [testing-plan.md](../skills/beadwork-run/references/testing-plan.md)：TDD / direct verification 的声明字段。
- [testing-tdd.md](../skills/beadwork-run/references/testing-tdd.md)：BASE、red 证据与已满足行为的处理。
- [testing-gates.md](../skills/beadwork-run/references/testing-gates.md)：验证范围和 boundary gates。

### 项目必须声明的测试事实

目标项目在自己的 `AGENTS.md`、justfile 注释或测试文档中明确说明：

- `gate-core` 实际包含哪些静态检查和快速测试，以及明确排除哪些真实边界。
- 每个 `gate-<boundary>` 覆盖什么行为、进程或外部服务边界。
- `test` 支持哪些筛选方式，默认收集范围是什么，如何识别并拒绝零匹配。
- 各 gate 所需的工具、服务和环境准备，以及缺失时的失败行为。
- 哪些 boundaries 列入 `defer_to_final` 及其项目理由。
- 哪些人工、线上或真实凭据验收不属于 `gate-full` 的结论。

共享契约定义通用规则，目标项目文档定义本项目的实际映射；不要把 Grok、x-media-saver 或其他消费项目的工具链与业务边界复制成通用要求。

### 阶段 1 验收清单

- [ ] 必需 recipes 均存在，并可在项目 worktree 中调用。
- [ ] `gate-plan` 只读输出严格三字段 JSON。
- [ ] `full` 包含所有且仅包含实际完整 gates，顺序与 `gate-full` 一致。
- [ ] `defer_to_final` 只包含 `full` 中的非 core 成员。
- [ ] `gate-core` 不启动项目声明的昂贵真实边界。
- [ ] 每个 boundary gate 都实际收集并执行非空测试范围。
- [ ] `gate-full` 按 `full` 顺序执行全部成员，不受延期分类削减。
- [ ] 定向 `test` 的筛选和默认收集范围已有项目内说明。
- [ ] 零匹配、缺失依赖和环境准备失败返回非零。
- [ ] 项目已用自身完整 gate 验证本次接入。

## 阶段 2：本地发现与 Git/worktree

每个目标项目在 primary checkout 的 `.agents/skills/beadwork-run` 建立整个目录的 symlink，指向本仓库的 `skills/beadwork-run` 源码；具体命令和忽略规则见 [本地开发](../README.md#本地开发)。入口已存在时先核对目标，不覆盖已有文件。该本机 symlink 不提交 Git。

### AGENTS.md 接入

skill 入口可用后，将下列片段合并到目标项目根目录的 AGENTS.md，保留已有项目规则。`<beadwork-run-dir>` 必须替换成该 primary checkout 的固定安装路径，例如 `~/projects/example/.agents/skills/beadwork-run`；读取前展开 `~` 并解析为真实绝对路径，不按当前 worktree 的相对目录推算。

```markdown
## Test seams

共享测试契约位于 `<beadwork-run-dir>/references/`（本项目 primary checkout 的安装入口）；以下文件名均相对此目录，读取前展开 `~` 并解析为真实绝对路径。直接读取参考文件即可，不启动 `beadwork-run`。

- 使用 `to-spec` 前读取 `testing-seams.md`；确定测试模式和计划时读取 `testing-plan.md`。
- 使用 `to-tickets` 前读取 `testing-plan.md` 和 `testing-gates.md`；解析 seam 引用时读取 `testing-seams.md`。为 Beadwork 拆票或调整顺序时另读 `serial-planning.md`，在同一次确认中批准增量切片及执行顺序，并使用其脚本发布、校验和接纳 parent 计划。
- 使用 `tdd` 前读取 `testing-seams.md`、`testing-tdd.md` 和 `testing-gates.md`；有 assigned ticket 时另读 `testing-plan.md`。

## 验证命令

beadwork-run 的安装与验证通过本项目 justfile 提供的契约 recipes 执行。Recipe 及其调用文件是实际命令、测试收集范围和运行环境的事实来源。
```

Test seams 指引由各目标项目声明；共享契约正文继续由 skill 源码维护，不复制到消费项目中。

目标项目还需要：

- 可用的 Git 仓库、本地 `main` 分支及用于基线同步的 `origin/main`；不需要远端写入权限。
- 支持 Git worktree，并正确忽略 `.worktrees/`。
- 允许工作流创建 `implement/<parent-id>` branch、`.worktrees/<parent-id>/` implementation worktree，以及 `.worktrees/.evidence/<parent-id>/` 证据目录。

最终交付只完成本地 commits、main 集成、Beads 关闭和清理，不执行 Git 或 Beads push。恢复已有批次时保留 BASE、commits、未提交现场和历史证据，按 skill 的恢复规则处理。

## 阶段 3：Beads 与 ticket graph

当前 `beadwork-run` 直接使用 Beads；仅声明 GitHub Issues 或其他 tracker，不能替代其 Beads 执行接口。目标项目需要已配置的 Beads workspace，worktree 必须共享正确的 primary workspace。

输入为一个完整 parent ID，批次范围是它的直接子 tickets。未关闭的 child 需要 `ready-for-agent` label；依赖关系应记录在 Beads 中，而非仅写在正文里。Parent 还必须包含已批准的 `ticket_order` 执行计划区块；拆票时按 [串行规划契约](../skills/beadwork-run/references/serial-planning.md) 一起确认并用脚本发布。执行器固定该顺序，下一张被阻塞时停止，不采用 Beads 默认排序。

执行前，ticket 需有明确验收条件和 Test plan；TDD ticket 需能解析到已批准的 seam。`to-spec` 和 `to-tickets` 是推荐的上游工作流，其他生产方式也需要交付满足相同契约的输入。

目标项目根 `AGENTS.md` 还需提供 tracker 入口，例如：

```markdown
## Issue tracker

本项目的 spec、tickets 和依赖关系存放在 Beads。具体 tracker 操作规则见 `docs/agents/issue-tracker.md`。
```

`docs/agents/issue-tracker.md` 是建议位置；已有规则放在其他位置时修改指针。该文件需要说明本项目使用 `bd`、完整 bead ID 和结构化 JSON 输出，并明确创建／读取 spec、查询 parent/child 与依赖、原子 claim、写入 comments 和关闭 ticket 的操作。

## 阶段 4：完整接入验收

启动第一个真实批次前，目标项目维护者应确认：

- [ ] 阶段 1 的测试契约清单全部满足，项目的无参数 `gate-full` 已通过。
- [ ] 项目可以从 primary checkout 发现当前 `beadwork-run` skill。
- [ ] 本地 main、origin/main、worktree 和忽略规则满足阶段 2。
- [ ] Beads workspace、parent、直接 children、依赖和 `ticket_order` 满足阶段 3。
- [ ] 每张未关闭 ticket 都有明确 acceptance、Test plan 和 `ready-for-agent` label。
- [ ] TDD tickets 引用的 seams 已获批准且可解析。

这些检查只证明项目具备启动条件。真实项目的完整 ticket graph、外部服务、Codex agent 派发和最终远端发布仍需在各自边界内单独验收。

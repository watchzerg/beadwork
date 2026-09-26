# Beadwork

面向 Codex 的 Beads ticket graph 执行工作流。

Beadwork 将已有的 ticket 依赖图逐票推进到实现、验证、审查和本地集成。它衔接 Matt Pocock 的工程 skills、共享测试契约，以及目标项目提供的 Beads、Git 和 just 接口，保留可用于核查和恢复的执行证据。

角色关系、executor/finalizer 执行流程、三层循环与职责边界见 [架构概览](docs/ARCHITECTURE.md)。

## 当前提供的 skill

| Skill | 用途 |
| --- | --- |
| [beadwork-run](skills/beadwork-run/SKILL.md) | 串行实现一个 Beads parent 下的直接子 tickets，验证与审查通过后完成本地提交与 main 集成 |

## beadwork-run 做什么

- 根据 ticket 依赖关系选择可执行工作。
- 在 implementation worktree 中逐票实现，同一时刻只有一个源码 writer。
- 根据 Test plan 使用 TDD 或 direct verification。
- 通过目标项目的 just recipes 执行安装与验证。
- 对每票和最终集成执行 Standards / Spec 双轴审查。
- 在满足交付条件后合入本地 main，关闭 tickets 并安全清理。
- 遇到无法继续的阻塞时保留现场、报告和恢复证据。

工作流会创建 commits、更新本地 Beads 状态，并在完成后进行本地集成与清理。不执行 Git 或 Beads push；远端发布由用户另行安排。

## 支持范围

当前仅支持 Codex。执行环境需要支持独立上下文的子 agent、嵌套派发、并行只读审查，以及显式指定模型和 reasoning effort。

当前流程使用预设模型组合；宿主能力见 [SKILL.md](skills/beadwork-run/SKILL.md)，ticket 与最终阶段模型配置见 [workflow_policy.py](skills/beadwork-run/scripts/workflow_policy.py) 的 `STAGE_MODELS` / `FINAL_STAGE_MODELS`。这些要求不等于任意 Codex 环境均可运行；缺少所需能力时，流程会停止。

内置脚本最低使用 Python 3.14，仅依赖标准库和 skill 自带模块。目标项目使用自己的语言与工具链，通过 just recipes 提供统一命令接口。接口改造不保留被替代入口、参数或历史 flow 的兼容层。

## 使用前提

目标项目需要具备：

- 可用的 Git 仓库和本地 main 分支；运行 skill 不需要 Git 远端。
- 已配置的 Beads workspace，以及包含直接子 tickets 的 parent。
- 明确的 ticket 依赖关系、验收条件和 Test plan；未关闭的 child 带有 `ready-for-agent` label。
- TDD ticket 对应的已批准测试 seam。
- 符合执行契约、实际可运行的 just recipes。
- 能指引 agent 读取 tracker 规则和共享测试契约的 AGENTS.md。
- 可用的 Python 运行时及当前执行路径所需的外部 skills。

项目接入要求见 [项目契约](docs/project-contract.md)。

## 接入新项目

新项目可以先实现测试与验证契约，再补齐本地 skill 发现、Git/worktree、Beads 和 ticket graph。四个必需 just 接口、完整要求及分阶段验收清单 见[目标项目接入契约](docs/project-contract.md)。仅完成测试契约，表示项目已经提供统一验证接口，不表示已经可以运行 `beadwork-run`。

## 使用方法

在目标项目的 Codex 会话中，使用完整的 Beads parent ID：

```text
$beadwork-run <full-parent-bead-id>
```

例如：

```text
$beadwork-run demo-abc
```

该 parent 下应已有准备完成的 ticket graph。beadwork-run 不负责从需求对话创建 spec 或拆分 tickets。

执行完成后，报告包含 ticket 进度、验证和审查结果、本地集成 SHA、清理结果，以及保留的证据目录，并注明未执行 Git/Beads push。执行阻塞时，报告包含停止原因和恢复入口。

## 与 Matt Pocock skills 的关系

推荐使用 Matt Pocock 的 `to-spec` 和 `to-tickets` 完成上游规划。AGENTS.md 将这些流程接入 Beadwork 的共享测试契约，使 spec 中的测试 seam、ticket 中的 Test plan 与执行时的验证要求保持一致。其他方式创建的 tickets 满足同一契约时，也可以作为输入。

执行 TDD ticket 时使用 `tdd`；发生合并冲突时使用 `resolving-merge-conflicts`。Standards / Spec 审查由 Beadwork 内置角色完成，其方法参考了 Matt 的 `code-review`，运行时直接使用本仓库的 reviewer 指令。

| 组件 | 职责 |
| --- | --- |
| AGENTS.md 接入规则 | 指引 agent 读取 tracker 规则与共享测试契约 |
| Matt skills | 上游规划、TDD 和特定场景的工程方法 |
| Beads | ticket graph 与执行状态 |
| Git/worktree | 代码隔离与集成 |
| just | 目标项目的命令契约 |
| Python | 内置工作流脚本 |

AGENTS.md 的接入片段不会自动安装工具、初始化 Beads 或实现目标项目的 justfile。

## 本地开发

源码在本仓库的 `skills/beadwork-run/` 维护。每个目标项目在 primary checkout 的 `.agents/skills/beadwork-run` 建立整个目录的 symlink，指向本仓库源码，使开发和使用共享同一份文件。

例如，两个仓库分别位于 `~/projects/beadwork` 和 `~/projects/grok-image-saver` 时：

```sh
mkdir -p ~/projects/grok-image-saver/.agents/skills
ln -s ~/projects/beadwork/skills/beadwork-run ~/projects/grok-image-saver/.agents/skills/beadwork-run
```

入口已存在时先核对目标，不覆盖已有文件。将 `/.agents/skills/beadwork-run` 单独加入目标仓库的 `.git/info/exclude`，本机 symlink 不提交 Git，也不加入 `skills-lock.json`。在目标项目 `AGENTS.md` 接入 [Test seams 指引](docs/project-contract.md#agentsmd-接入)，路径固定到该项目 primary checkout 的安装入口；全局 AGENTS.md 不配置 Beadwork Test seams，用户级 skills 目录不保留同名入口。

从 primary checkout 启动 Beadwork。工作流会向子角色交接真实绝对 `skill_dir`；项目规则中的 primary 路径也可从 worktree 读取。本机 symlink 不会随 Git 自动出现在新 worktree 中；若需在独立 worktree 会话中直接发现 `$beadwork-run`，须在该 worktree 的 `.agents/skills/` 另建指向相同源码的入口。

修改后即可在下一次读取时使用磁盘内容，无需先 commit 或 push。本地 commit 用于保存可回退的版本，push 频率独立决定。

skill 的唯一公开 Python 入口是 `python3 <skill-dir>/scripts/beadwork.py <command> …`；顶层及各命令组可用 `--help` 逐级发现。内部模块只提供 Python API，不作为独立脚本调用。

维护者注意：正在运行的 agent 可能已经读取旧指令，后续读取又可能取得修改后的内容。是否避开正在进行的运行，由维护者自行判断；这不是 AI 修改源码前需要核实或请求确认的条件。

开发环境要求宿主已有 mise 和 just。mise 只管理项目 uv；uv 管理 `.python-version` 固定的 Python 3.14 补丁版本、`.venv` 和开发依赖。`mise.lock` 固定 uv 的实际版本，`uv.lock` 固定 Ruff、ty、pytest、pytest-xdist 和 PyYAML；稳定版本解析明确排除 prerelease。

用户级 `~/.codex/skills/.system/skill-creator/scripts/quick_validate.py` 是开发前置依赖。仓库不会下载、复制或改写它；缺失时 validator 和完整门禁会明确失败。

新机器先确认宿主工具，再按项目声明安装 uv、Python 和 locked 依赖：

```sh
command -v mise
command -v just
just install
just check-toolchain
```

`just install` 依次执行 locked mise 安装、项目 Python 准备和 `uv sync --locked`，不会升级宿主 mise/just 或修改全局默认版本。

当前开发命令可用 `just --list` 查看。日常修改先运行最小 suite；额外 pytest 参数放在 `just --` 之后以保持 argv 边界：

```sh
just test unit
just test integration
just test workflow
just test distribution
just -- test integration tests/test_controller.py -k 'prepare or accept'
```

`unit` 默认串行，其余 suite 默认使用 4 个 xdist workers；设置 `BEADWORK_TEST_JOBS=0` 可串行诊断。未知 suite、零匹配、额外 `-m` 和子命令失败都会非零退出。每项测试都显式且唯一归入 unit、integration 或 workflow；`distribution` 是同时属于 integration 的专题 marker。分发验收必须使用项目准备的 Python 3.14，复制 `skills/beadwork-run/` 后从无关 cwd 以 `-S -B` 运行；解释器缺失或版本不是 3.14 时失败，不会在测试期间下载或 skip。

文档修改核对描述与实现、协议的一致性；修改链接时确认目标，修改命令时验证对应命令，并按需运行 `git diff --check`。Ruff 检查使用 `just lint`，ty 检查使用 `just typecheck`，skill validator 使用 `just validate-skill`。格式化指定路径使用 `just fmt <path>...`；它会修改文件，不属于门禁。交付前运行完整门禁：

```sh
just gate-full
```

当前 `gate-full` 依次检查工具链、`git diff --check`、Ruff lint/format、ty、全部 pytest 和真实 validator。必要分发资源与 explicit-only invocation policy 由 distribution 测试覆盖。

测试位于 `tests/`。integration、workflow 和 distribution 使用临时文件或 Git 仓库与 Beads fixtures，需要可用的 Git，并需要允许创建临时 worktree。它们不会运行真实项目的 ticket graph，也不能证明当前 Codex 宿主的完整 agent 派发链可用。当前 distribution 验收只覆盖实际运行它的宿主平台，不代表其他操作系统矩阵。

共享参考文件继续与 skill 同目录分发。

## 来源与致谢

Beadwork 的部分工程方法参考并衔接 [mattpocock/skills](https://github.com/mattpocock/skills)。Beadwork 自行维护 ticket graph 执行、验证、证据交付和恢复控制逻辑。内置 reviewer 采用 Standards / Spec 双轴方法与 12 项 Fowler smell baseline；运行时直接读取本仓库的角色指令。

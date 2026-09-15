# Beadwork

面向 Codex 的 Beads ticket graph 执行工作流。

Beadwork 将已有的 ticket 依赖图逐票推进到实现、验证、审查和本地集成。它衔接 Matt Pocock 的工程 skills、共享测试契约，以及目标项目提供的 Beads、Git 和 just 接口，保留可用于核查和恢复的执行证据。

## 当前提供的 skill

| Skill | 用途 |
| --- | --- |
| [beadwork-run](skills/beadwork-run/SKILL.md) | 串行实现一个 Beads parent 下的直接子 tickets，并在验证与审查通过后合入本地 main |

## beadwork-run 做什么

- 根据 ticket 依赖关系选择可执行工作。
- 在 implementation worktree 中逐票实现，同一时刻只有一个源码 writer。
- 根据 Test plan 使用 TDD 或 direct verification。
- 通过目标项目的 just recipes 执行安装与验证。
- 对每票和最终集成执行 Standards / Spec 双轴审查。
- 在满足交付条件后合入本地 main。
- 遇到无法继续的阻塞时保留现场、报告和恢复证据。

工作流会创建 commits、更新 Beads 状态，并在完成后进行本地集成与清理。Git 和 Dolt 的远端 push 不属于该流程。

## 支持范围

当前仅支持 Codex。执行环境需要支持独立上下文的子 agent、嵌套派发、并行只读审查，以及显式指定模型和 reasoning effort。

当前流程使用预设模型组合；宿主能力见 [SKILL.md](skills/beadwork-run/SKILL.md)，ticket 阶段模型配置见 [controller.py](skills/beadwork-run/scripts/controller.py) 的 `STAGE_MODELS`。这些要求不等于任意 Codex 环境均可运行；缺少所需能力时，流程会停止。

内置脚本按当前 skill 声明使用 Python 3.9 或更高版本，仅依赖标准库。目标项目使用自己的语言与工具链，通过 just recipes 提供统一命令接口。

## 使用前提

目标项目需要具备：

- 可用的 Git 仓库和本地 main 分支。
- 已配置的 Beads workspace，以及包含直接子 tickets 的 parent。
- 明确的 ticket 依赖关系、验收条件和 Test plan；未关闭的 child 带有 `ready-for-agent` label。
- TDD ticket 对应的已批准测试 seam。
- 符合执行契约、实际可运行的 just recipes。
- 能指引 agent 读取 tracker 规则和共享测试契约的 AGENTS.md。
- 可用的 Python 运行时及当前执行路径所需的外部 skills。

项目接入要求见 [项目契约](docs/project-contract.md)。

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

执行完成后，报告包含 ticket 进度、验证和审查结果、本地集成状态，以及保留的证据目录。执行阻塞时，报告包含停止原因和恢复入口。

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

源码在本仓库的 `skills/beadwork-run/` 维护。本机 skill 发现目录中的 `beadwork-run` 可以用整个目录的 symlink 指向这里，使开发和使用共享同一份文件。

修改后即可在下一次读取时使用磁盘内容，无需先 commit 或 push。本地 commit 用于保存可回退的版本，push 频率独立决定。正在运行的 agent 可能已经读取旧指令，因此在一次执行结束或确认停止后修改，再开始下一轮验证。

从仓库根目录运行现有脚本回归测试：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_*.py'
```

测试使用临时 Git 仓库和 Beads fixtures，需要可用的 Git，并需要允许创建临时 worktree。它们不会运行真实项目的 ticket graph，也不能证明当前 Codex 宿主的完整 agent 派发链可用。

共享参考文件继续与 skill 同目录分发；测试继续放在现有 `scripts/` 中。

## 来源与致谢

Beadwork 的部分工程方法参考并衔接 [mattpocock/skills](https://github.com/mattpocock/skills)。Beadwork 自行维护 ticket graph 执行、验证、证据交付和恢复控制逻辑。

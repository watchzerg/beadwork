# Beadwork 源码维护

## 范围与语言

本仓库维护 Beadwork skills。人类可审阅的说明使用简体中文；代码标识、接口和 established technical terms 保留英文。目标项目的接入规则位于 `docs/project-contract.md`，不把某个消费项目的 Bun、数据库或业务约束引入本仓库。

文档入口按需阅读：

- [README](README.md)：项目用途、skill 能力与使用入口。
- [架构概览](docs/ARCHITECTURE.md)：角色关系、executor/finalizer 执行流程、三层循环与职责边界；修改流程或作出架构决策时阅读。

## 源码与本地使用

- `skills/` 是 skill 源码的唯一维护位置。目标项目的 `.agents/skills/beadwork-run` 使用目录 symlink 指向本仓库源码；安装与 Test seams 指引按项目配置，见 `docs/project-contract.md`。
- 读取和验证路径时解析真实路径；修改源码会影响下一次调用。
- 共用契约保留在 `skills/beadwork-run/references/`；按调用场景读取，避免在 README 或接入文档复制完整协议。
- 修改只处理当前需求；保留既有协议字段、branch/worktree 布局和 append-only 证据语义，除非任务明确要求改变。
- skill 运行源码最低支持 Python 3.14，只依赖标准库和 skill 自带模块。开发环境的具体 Python 补丁版本由 `.python-version` 固定；提高最低版本须作为单独兼容性变更。
- skill 优化与升级默认只面向当前源码和升级后新启动的工作流，优先采用职责清晰、实现简洁的方案。不为旧版本、历史数据或升级前已启动但尚未完成的流程保留兼容层、迁移逻辑或跨版本恢复支持；不维护被替代的入口、参数或历史 flow。变更时同步更新当前调用者、测试和文档。只有用户明确要求兼容或迁移时，才将其纳入范围。
- skill 的唯一公开 Python CLI 是 `python3 <skill-dir>/scripts/beadwork.py <command> …`；内部模块不作为脚本入口。
- 不为 skill 工作流或执行证据维护版本号或版本校验。每次优化均按全新 flow 设计，不增加旧现场适配、历史迁移或替代版本校验的机制。
- 真实项目的 Beads 数据、执行证据和本机备份不进入本仓库。

## 开发环境与验证

mise 只管理项目 uv，uv 管理开发 Python、`.venv` 和 Python 开发依赖；mise/just 自身是宿主前置工具。`mise.lock` 固定 uv，`.python-version` 固定 Python 补丁版本，`uv.lock` 固定开发依赖。不要升级用户级工具或修改相邻项目。

新环境先确认宿主已有 mise/just，再运行：

```sh
just install
just check-toolchain
```

用户级 `~/.codex/skills/.system/skill-creator/scripts/quick_validate.py` 是已接受但不由本项目锁定版本的宿主开发依赖；缺失时 `just validate-skill` 必须失败，不下载或复制 validator。

按改动边界选择最小 suite；额外 pytest 参数放在 `just --` 之后，`BEADWORK_TEST_JOBS=0` 可切换为串行诊断：

```sh
just test unit
just test integration
just test workflow
just -- test integration tests/test_controller.py -k 'prepare or accept'
```

每个测试必须显式且仅属于一个主 marker：被测行为和 fixture 准备均为纯内存时使用 `unit`；单一能力与真实文件系统、Git、CLI 或进程边界协作时使用 `integration`；多个操作的产物衔接、阶段推进或恢复场景使用 `workflow`。`distribution` 是必须同时属于 `integration` 的专题 marker。pytest collection 会拒绝漏标、多主层以及未配套 integration 的 distribution；继承产生的同名 marker 按一个层次计算。

按改动边界选择验证：

| 修改场景 | 最小充分验证 |
| --- | --- |
| 纯规则、解析、状态计算 | 相关 unit |
| 文件发布、绑定、symlink、Git、外部进程 | 相关 integration，加被修改的纯规则测试 |
| 多阶段推进、恢复、关闭、集成 | 相关 workflow，加受影响的低层测试 |
| CLI、import、目录、运行版本、分发内容 | CLI integration + distribution；涉及命令衔接时加 workflow |
| 文档文字与链接 | 核对描述与实现、协议的一致性；修改链接时确认目标，修改执行命令时加相关 CLI 验证；按需运行 `git diff --check` |
| 工具链升级、跨模块协议、目录迁移或交付 | `just gate-full` |

`just test <suite>` 真实按 marker 选择；指定的 suite 没有匹配测试时沿用 pytest 非零退出。`unit` 串行运行，其余 suite 默认使用 4 个 xdist worker；`BEADWORK_TEST_JOBS=0` 仅用于串行诊断。不要仅因测试较慢或使用真实 Git 就将其归为 workflow。

只修改文档时按上述范围核对，不强制运行独立文档 gate。Python 修改可分别运行 `just lint` 和 `just typecheck`；`just fmt` 会修改文件，不属于 gate。目录迁移、跨脚本协议或交付前运行完整门禁：

```sh
just gate-full
```

`distribution` suite 必须使用 `.python-version` 准备的 Python 3.14；解释器缺失或版本不是 3.14 时失败，不 skip。它从无关 cwd 以 `-S -B` 运行复制后的 skill，检查独立分发、标准库依赖边界、必要资源和 explicit-only invocation policy。`gate-full` 顺序执行工具链检查、`git diff --check`、Ruff lint/format check、ty、包含 distribution 的全部 pytest 和真实 skill validator。

测试位于 `tests/`。integration 和 workflow 会在临时目录创建 Git 仓库、worktrees 与 Beads fixtures，需要对应执行权限；它们证明本地脚本和多步骤产物衔接，不证明真实 Beads workspace 或远端 tracker 已验收。`gate-full` 也不运行真实 Codex agent 派发；若未分别执行真实 Beads 和真实 Codex 验收，交付时必须明确列为未验证，不能用 fixture 结果替代。

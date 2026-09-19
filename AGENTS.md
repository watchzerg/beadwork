# Beadwork 源码维护

## 范围与语言

本仓库维护 Beadwork skills。人类可审阅的说明使用简体中文；代码标识、接口和 established technical terms 保留英文。目标项目的接入规则位于 `docs/project-contract.md`，不把某个消费项目的 Bun、数据库或业务约束引入本仓库。

需要理解角色关系、判断职责边界或作出架构决策时，可按需阅读 [架构概览](docs/ARCHITECTURE.md)。

## 源码与本地使用

- `skills/` 是 skill 源码的唯一维护位置。目标项目的 `.agents/skills/beadwork-run` 使用目录 symlink 指向本仓库源码；安装与 Test seams 指引按项目配置，见 `docs/project-contract.md`。
- 读取和验证路径时解析真实路径；修改源码会影响下一次调用。
- 共用契约保留在 `skills/beadwork-run/references/`；按调用场景读取，避免在 README 或接入文档复制完整协议。
- 修改只处理当前需求；保留既有协议字段、branch/worktree 布局和 append-only 证据语义，除非任务明确要求改变。
- skill 运行源码最低支持 Python 3.14，只依赖标准库和 skill 自带模块。开发环境的具体 Python 补丁版本由 `.python-version` 固定；提高最低版本须作为单独兼容性变更。
- 不维护被替代入口、参数或历史 flow 的兼容层。接口迁移按已批准范围直接更新当前调用者和文档。
- 真实项目的 Beads 数据、执行证据和本机备份不进入本仓库。

## 开发环境与验证

mise 只管理项目 uv，uv 管理开发 Python、`.venv` 和 Python 开发依赖；mise/just 自身是宿主前置工具。`mise.lock` 固定 uv，`.python-version` 固定 Python 补丁版本，`uv.lock` 固定开发依赖。不要升级用户级工具或修改相邻项目。

新环境先确认宿主已有 mise/just，再运行：

```sh
just install
just check-toolchain
```

用户级 `~/.codex/skills/.system/skill-creator/scripts/quick_validate.py` 是开发前置依赖；缺失时 `just validate-skill` 必须失败，不下载或复制 validator。

按改动边界选择最小 suite；额外 pytest 参数放在 `just --` 之后，`BEADWORK_TEST_JOBS=0` 可切换为串行诊断：

```sh
just test unit
just test integration
just test workflow
just -- test integration tests/test_controller.py -k 'prepare or accept'
```

每个测试必须显式且仅属于一个主 marker：被测行为和 fixture 准备均为纯内存时使用 `unit`；单一能力与真实文件系统、Git、CLI 或进程边界协作时使用 `integration`；多个操作的产物衔接、阶段推进或恢复场景使用 `workflow`。`distribution` 是必须同时属于 `integration` 的专题 marker。pytest collection 会拒绝漏标、多主层以及未配套 integration 的 distribution；继承产生的同名 marker 按一个层次计算。

`just test <suite>` 真实按 marker 选择；指定的 suite 没有匹配测试时沿用 pytest 非零退出。`unit` 串行运行，其余 suite 默认使用 4 个 xdist worker；`BEADWORK_TEST_JOBS=0` 仅用于串行诊断。不要仅因测试较慢或使用真实 Git 就将其归为 workflow。

只修改文档时运行 `just check-docs`。目录迁移、跨脚本协议或交付前运行当前过渡完整门禁：

```sh
just gate-full
```

阶段 1 的 `gate-full` 顺序执行工具链检查、文档/结构/Python 语法检查、全部 pytest 和真实 skill validator；Ruff/ty 静态门禁在阶段 3 启用。`fmt` 是修改型命令，不属于 gate。`distribution` suite 在阶段 5 建立测试前允许因零匹配非零失败，不添加占位用例。

测试位于 `tests/`。integration 和 workflow 会在临时目录创建 Git 仓库与 worktrees，需要对应执行权限。脚本测试通过不等于真实 Codex 嵌套派发已验证，交付时区分两者。

# Beadwork 源码维护

## 范围与语言

本仓库维护 Beadwork skills。人类可审阅的说明使用简体中文；代码标识、接口和 established technical terms 保留英文。目标项目的接入规则位于 `docs/project-contract.md`，不把某个消费项目的 Bun、数据库或业务约束引入本仓库。

需要理解角色关系、判断职责边界或作出架构决策时，可按需阅读 [架构概览](docs/ARCHITECTURE.md)。

## 源码与本地使用

- `skills/` 是 skill 源码的唯一维护位置。目标项目的 `.agents/skills/beadwork-run` 使用目录 symlink 指向本仓库源码；安装与 Test seams 指引按项目配置，见 `docs/project-contract.md`。
- 读取和验证路径时解析真实路径；修改源码会影响下一次调用。
- 共用契约保留在 `skills/beadwork-run/references/`；按调用场景读取，避免在 README 或接入文档复制完整协议。
- 修改只处理当前需求；保留既有协议字段、branch/worktree 布局和 append-only 证据语义，除非任务明确要求改变。
- 真实项目的 Beads 数据、执行证据和本机备份不进入本仓库。

## 验证

开发依赖由 `uv.lock` 固定。首次准备环境运行：

```sh
uv sync --locked --group dev
```

按改动边界选择最小 suite：

```sh
uv run pytest -m unit -q
uv run pytest -m integration -n 4 --dist=worksteal
uv run pytest -m workflow -n 4 --dist=worksteal
```

纯规则和数据转换运行 `unit`；文件系统、Git 或 CLI 边界运行 `integration`；跨阶段状态机和真实临时 worktree 运行 `workflow`。目录迁移、跨脚本协议或交付前运行完整门禁：

```sh
uv run python skills/beadwork-run/scripts/maintenance_check.py full --jobs 4
```

测试位于 `tests/`。integration 和 workflow 会在临时目录创建 Git 仓库与 worktrees，需要对应执行权限。只修改文档时检查链接、命名与 `git diff --check`，不运行 workflow。

`full` 会运行 skill validator，并核对相对资源引用、`agents/openai.yaml` 策略和实际运行路径。脚本测试通过不等于真实 Codex 嵌套派发已验证，交付时区分两者。

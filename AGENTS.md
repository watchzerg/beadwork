# Beadwork 源码维护

## 范围与语言

本仓库维护 Beadwork skills。人类可审阅的说明使用简体中文；代码标识、接口和 established technical terms 保留英文。目标项目的接入规则位于 `docs/project-contract.md`，不把某个消费项目的 Bun、数据库或业务约束引入本仓库。

需要理解角色关系、判断职责边界或作出架构决策时，可按需阅读 [架构概览](docs/ARCHITECTURE.md)。

## 源码与本地使用

- `skills/` 是 skill 源码的唯一维护位置。用户级安装入口可以是指向该目录中具体 skill 的 symlink。
- 读取和验证路径时解析真实路径；修改源码会影响下一次调用。
- 共用契约保留在 `skills/beadwork-run/references/`；按调用场景读取，避免在 README 或接入文档复制完整协议。
- 修改只处理当前需求；保留既有协议字段、branch/worktree 布局和 append-only 证据语义，除非任务明确要求改变。
- 真实项目的 Beads 数据、执行证据和本机备份不进入本仓库。

## 验证

从仓库根目录运行脚本回归测试：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_*.py'
```

测试会在临时目录创建 Git 仓库与 worktrees，需要对应执行权限。按改动风险选取相关测试；目录迁移或跨脚本协议修改运行完整套件。只修改文档时检查链接、命名与 `git diff --check`，不因文档改动运行真实 ticket graph。

修改 skill 时使用可用的 skill validator，并核对相对资源引用、`agents/openai.yaml` 策略和实际运行路径。脚本测试通过不等于真实 Codex 嵌套派发已验证，交付时区分两者。

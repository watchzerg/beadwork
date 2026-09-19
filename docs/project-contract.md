# 目标项目契约

本文面向要运行 `beadwork-run` 的目标项目。Beadwork 源码仓库的维护规则见根目录 [AGENTS.md](../AGENTS.md)。接入不要求目标项目采用 Beadwork 源码仓库的语言或工具链。

## AGENTS.md 接入

将下列片段合并到目标项目根目录的 AGENTS.md，保留已有项目规则。安装入口位于该项目 primary checkout 的 `.agents/skills/beadwork-run`，设置方法见 [本地开发](../README.md#本地开发)。

`<beadwork-run-dir>` 必须替换成该 primary checkout 的固定安装路径，例如 `~/projects/grok-image-saver/.agents/skills/beadwork-run`；x-media-saver 则使用 `~/projects/x-media-saver/.agents/skills/beadwork-run`。读取前展开 `~` 并解析为真实绝对路径，不按当前 worktree 的相对目录推算；不要把占位符原样用于运行。

```markdown
## Issue tracker

本项目的 spec、tickets 和依赖关系存放在 Beads。具体 tracker 操作规则见 `docs/agents/issue-tracker.md`。

## Test seams

共享测试契约位于 `<beadwork-run-dir>/references/`（本项目 primary checkout 的安装入口）；以下文件名均相对此目录，读取前展开 `~` 并解析为真实绝对路径。直接读取参考文件即可，不启动 `beadwork-run`。

- 使用 `to-spec` 前读取 `testing-seams.md`；确定测试模式和计划时读取 `testing-plan.md`。
- 使用 `to-tickets` 前读取 `testing-plan.md` 和 `testing-gates.md`；解析 seam 引用时读取 `testing-seams.md`。为 Beadwork 拆票或调整顺序时另读 `serial-planning.md`，在同一次确认中批准增量切片及执行顺序，并使用其脚本发布、校验和接纳 parent 计划。
- 使用 `tdd` 前读取 `testing-seams.md`、`testing-tdd.md` 和 `testing-gates.md`；有 assigned ticket 时另读 `testing-plan.md`。

## 验证命令

beadwork-run 的安装与验证通过本项目 justfile 提供的契约 recipes 执行。Recipe 及其调用文件是实际命令、测试收集范围和运行环境的事实来源。
```

`docs/agents/issue-tracker.md` 是建议位置；已有规则放在其他位置时修改指针。该文件需要说明本项目使用 `bd`、完整 bead ID 和结构化 JSON 输出，并明确创建／读取 spec、查询 parent/child 与依赖、原子 claim、写入 comments 和关闭 ticket 的操作。

当前 `beadwork-run` 直接使用 Beads。仅声明 GitHub Issues 或其他 tracker，不能替代其 Beads 执行接口。Test seams 指引由各目标项目声明，共享契约正文继续由 skill 源码维护，不复制到项目中。

## Spec 与 ticket

输入为一个完整 parent ID，批次范围是它的直接子 tickets。未关闭的 child 需要 `ready-for-agent` label；依赖关系应记录在 Beads 中，而非仅写在正文里。Parent 还必须包含已批准的 `ticket_order` 执行计划区块；拆票时按 [串行规划契约](../skills/beadwork-run/references/serial-planning.md) 一起确认并用脚本发布。执行器固定该顺序，下一张被阻塞时停止，不采用 Beads 默认排序。

执行前，ticket 需有明确验收条件和 Test plan，TDD ticket 需能解析到已批准的 seam。字段和授权规则以随 skill 分发的文档为准：

- [testing-seams.md](../skills/beadwork-run/references/testing-seams.md)：spec 中的 seam 定义和变更授权。
- [testing-plan.md](../skills/beadwork-run/references/testing-plan.md)：TDD / direct verification 的声明字段。
- [testing-tdd.md](../skills/beadwork-run/references/testing-tdd.md)：BASE、red 证据与已满足行为的处理。
- [testing-gates.md](../skills/beadwork-run/references/testing-gates.md)：验证范围和 boundary gates。

`to-spec` 和 `to-tickets` 是推荐的上游工作流。AGENTS.md 让它们读取上述规则；其他生产方式也需要交付满足相同契约的输入。

## justfile

目标项目提供下列入口。当前 preflight 的必需名称清单见 [preflight-operations.py](../skills/beadwork-run/scripts/preflight-operations.py) 的 `RECIPES`；具体调用方式见 skill 内的执行指令。

| Recipe | 职责与调用约定 |
| --- | --- |
| `check-toolchain` | 检查声明的工具链，缺失或不符合要求时明确失败 |
| `install` | 安装项目依赖，可重复执行 |
| `typecheck` | 执行项目权威类型或等价静态检查 |
| `test [ARGS...]` | 运行相关测试；说明支持的筛选参数和收集范围 |
| `gate-plan` | 无参数、只读输出 `{"core":"gate-core","full":[...]}`；不安装依赖、运行测试或探测外部服务 |
| `gate-core` | 无参数执行静态检查及快速隔离的基础回归；必须是 `full` 成员 |
| `gate-full` | 无参数按 `gate-plan.full` 的顺序逐项完整执行，每项一次、首错停止 |
| `env-facts` | 输出用于检查与交接的环境事实 |
| `fmt [FILES...]` | 格式化指定文件；遵循本项目参数约定 |
| `gate-<boundary>` | 按实际 suite 提供额外边界验证，由 Test plan 引用 |

这些是执行契约，不要求使用某个具体 test runner 或 formatter，也不要求所有项目建立数据库、浏览器等固定分类。项目应先盘点真实测试、依赖和故障边界；没有独立 suite 时不创建空 gate。`gate-plan.full` 是唯一完整成员定义，顺序有意义；除保留入口 `gate-plan`、`gate-full` 外，每个 `gate-*` recipe 都必须登记且只出现一次，成员必须真实存在。完整 gate 均拒绝筛选参数；筛选只走 `test`。被声明的入口失败须返回非零退出码，零匹配、空命令或占位 recipe 不能代表通过。

## Git 与运行现场

目标项目需要本地 `main`，支持 Git worktree，并正确忽略 `.worktrees/`。基线同步继续读取 Git `origin/main`；最终交付只完成本地 commits、main 集成、Beads 关闭和清理，不执行 Git 或 Beads push，也不要求远端写入权限。当前固定布局为 `implement/<parent-id>` branch、`.worktrees/<parent-id>/` worktree，证据保存在 `.worktrees/.evidence/<parent-id>/`。

Beads worktree 需共享正确的 primary workspace。恢复已有批次时保留 BASE、commits、未提交现场和历史证据，按 skill 的恢复规则处理。

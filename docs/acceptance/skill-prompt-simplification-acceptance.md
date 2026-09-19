# 提示词精简实施与验证记录

日期：2026-09-16。对应 [实施计划](../plans/skill-prompt-simplification-plan.md)。

规则更新：本次实施曾按当时要求等待用户确认运行停止。该维护前置条件现已从 AGENTS.md 和实施计划移除，历史确认记录不构成后续修改的要求；相关注意事项仅保留在 README，供维护者自行判断。

状态：用户已确认相关运行均已结束或停止；隔离副本的精简修改已同步到用户级 symlink 指向的源码，安装入口验证通过。P06 的自动初始化替代未完成，保留现有初始化路线，具体差异见下文。

## 基线与交付位置

- Git HEAD：`c75ba82a45c42806363e405abaa46e6f72c5af69`。
- 开工时仅有未跟踪的 `docs/skill-prompt-simplification-plan.md`，未修改既有源码。
- 用户级入口：`/Users/watchzerg/.agents/skills/beadwork-run`，真实路径为本仓库 `skills/beadwork-run`；`allow_implicit_invocation: false` 保持。
- 隔离副本：`/private/tmp/beadwork-prompt-kEgMu1`，从上述 HEAD 导出，无消费项目数据或执行证据。
- 可应用补丁：`/private/tmp/beadwork-prompt-kEgMu1/implementation.patch`。已在原仓库执行 `git apply --check`，通过；该检查未写入源码。
- 本轮没有生产 Python、schema、模型策略或测试代码改动，没有 commit/push，没有启动真实 graph。

同步前重新核对 HEAD 与工作区，仍为上述基线且只有计划/验收文档未跟踪。通过 apply_patch 同步后，skill 文件与隔离副本一致（忽略运行时 __pycache__）；源码现为交付依据，不依赖临时目录长期存在。

## 工作项结果

| 工作项 | 实施结果 | 规则归属与保留边界 |
| --- | --- | --- |
| P00 | 完成基线、安装路径与加载清单；用户确认相关运行均已结束或停止 | 确认后才同步安装源码 |
| P01 | v2 final-assemble 使用检查点自动选源；移除手工 review_rounds/fixer 数组要求 | draft 人工字段在 final-execution；显式 legacy 参数在 recovery-finalizer |
| P02 | 共用交付改用 prepare/stage 产物；新增 recovery-report 按需参考 | schema、短回执、独立完整验收、append-only 和收尾保留 |
| P03 | 删除多份最终阶段模型表，压缩 controller 内部阶段说明 | 子角色使用 dispatch 模型；preflight/finalizer 协调模型仍在 SKILL.md |
| P04 | finalizer 正常路径不预读恢复；fixer 限定读取相关小节 | 独立角色权限、项目事实和必要契约仍明确 |
| P05 | 提交机械顺序归入 executor-operations；writer 报告区分人工和生成字段 | 分层语义、有效 red、根因修复及 gate 覆盖保留 |
| P06 | 正常 tracker 操作统一到 intent/读回；初始化保留单一路线，自动替代未完成 | 不把未证明等价的 batch_initialize 作为默认入口 |
| P07 | timing 说明移至维护文档；方法来源移至 README；smell 描述压缩 | 12 项 baseline、blocking 分类和双轴职责不变 |
| P08 | 静态检查、validator、40 项既有回归与加载对比完成 | 未运行真实 Beads 集成或 Codex 嵌套派发 |

## P06 等价性核对与保留事项

`batch_initialize.py` 使用普通 Git worktree 创建，没有执行原流程中的 `bd worktree info` / `bd where` 共享 workspace 核对；其 ready 也不替代批次 comment。没有真实 Beads 环境的等价性证据，本轮未将其提升为默认流程，未为提示词精简扩大修改初始化协议。

正常新批次仍按 SKILL.md 第 2 节完成 worktree、workspace、install/env-facts/smoke，再通过 tracker claim/comment。恢复参考明确已有 batch_initialize intent 必须核对实际步骤和 workspace。自动初始化替代仍是计划中的未完成项。

tracker 入口已有 intent 与写后读回机制。文档补足其输入、缓存含义与 comment ID 的实际读回方法，明确 close 的 prerequisite 只检查文件绑定：成功状态、completion 已写入及 parent 合入条件仍由 controller 核对。未宣称脚本自动保证这些语义。

manifest 只作来源绑定的 gate/commit 辅助汇总；不能取代全部 review findings、执行顺序或原始 completion pointers。merge/cleanup 的现有条件保持。

## 加载清单与同口径对比

以下按普通 direct verification 成功路径列出可达的本 skill 文档，按文件完整计数，单个角色内去重；不计项目规则/spec/schema/源码，也不将不同角色上下文合并去重。小节限定读取仍按整文件计数，因此未把潜在小节读取收益算入。reviewer 的项目测试参考按具体审查条件另加载。

共用 C = report-delivery + testing-contract。以下 reference 名均在 references 中，角色名均在 agents 中。

| 角色 | 正常路径计数清单 |
| --- | --- |
| controller | SKILL、C、controller-operations、testing-gates |
| preflight | preflight、C、testing-plan、testing-seams、testing-gates |
| executor | ticket-executor、C、ticket-execution、executor-operations、testing-plan、testing-gates、review |
| implementer | implementer、C、ticket-execution、executor-operations、verification、testing-plan、testing-gates |
| reviewer | reviewer、C；测试契约按本轮证据触发 |
| finalizer | finalizer、C、final-execution、review、verification、testing-gates；旧指令额外必读 recovery-finalizer |
| fixer | fixer、report-delivery、final-execution、verification、testing-seams、testing-gates |

TDD 增量为 testing-seams/testing-tdd（已读项不重复计），BASE 已满足增量为 baseline-adaptation；代码修复按原 dispatch 的 prior reports/findings 加载；中断和 legacy 按对应 recovery 引用加载，新 recovery-report 仅在交付故障时读取。这些条件不因压缩正文而取消。

| 角色 | 文件数前→后 | 行数前→后 | UTF-8 字节前→后 |
| --- | --- | --- | --- |
| controller | 5→5 | 453→433 | 42,361→40,136 |
| preflight | 6→6 | 237→203 | 20,906→18,366 |
| executor | 8→8 | 355→321 | 37,736→35,297 |
| implementer | 8→8 | 400→341 | 40,855→36,650 |
| reviewer | 3→3 | 151→115 | 16,085→13,204 |
| finalizer | 8→7 | 344→261 | 39,126→30,448 |
| fixer | 6→6 | 248→221 | 26,148→22,862 |

全部 skill Markdown（包括条件参考）从 29 文件、1,209 行、124,398 字节变为 30 文件、1,165 行、116,842 字节。新增文件是聚焦的交付故障参考；总字节减少约 6.1%，finalizer 上述路径减少约 22.2%。这是静态文档计量，不是实际 token、模型执行效率或成功率测量。

## 验证结果

| 检查 | 结果 | 覆盖与限制 |
| --- | --- | --- |
| `test_finalization.py` | 13 项通过，19.225 秒 | 历史阶段、额度、恢复、最终交付 |
| `test_handoff.py` | 23 项通过，32.098 秒 | v2 自动选源、真实验证采集、唯一 review、来源损坏、收尾、无变更与更正 |
| `test_tracker_operations.py` | 4 项通过，1.186 秒 | claim 竞争、comment 重入、close 读回；受控 bd fixture |
| skill validator | 通过 | 系统 Python 缺 PyYAML，使用 `uv run --with pyyaml python …/quick_validate.py` 验证隔离副本；未改项目依赖 |
| 本地链接 | 通过 | 调用现有 maintenance_check.local_links 检查隔离副本 |
| diff 格式与补丁适用性 | 通过 | no-index diff --check 与原仓库 git apply --check；无源码写入 |

回归在原仓库执行；隔离副本生产脚本与测试代码完全未改，因此结果用于验证所引用的现有行为。纯文档改动未运行完整脚本套件，也未新增措辞快照测试。脚本回归不证明模型会正确遵循精简后的指令。

静态走查覆盖：正常 dispatch/schema 路径、TDD/direct verification、BASE 适配、v2 自动选源、显式 legacy 参数、中断与代码失败、review 更正、未知停止状态、部分 BLOCKED、tracker 前置条件及读回。原权限、额度、模型策略、固定 BASE/HEAD、append-only 与双轴审查保持。

## 同步后检查与剩余边界

1. 同步后重新运行 maintenance_check.py docs，本地链接与 git diff --check 通过；对 `/Users/watchzerg/.agents/skills/beadwork-run` 运行 skill validator，通过。真实路径及 explicit-only policy 保持，生产脚本与测试代码无 diff，因此未重复此前已通过的 40 项回归。
2. P06 自动初始化入口的 workspace/恢复等价性仍未完成；保持明确的现有默认路线，不以此次精简宣称该脚本已完全接管初始化。
3. 真实 Beads 与 Codex 嵌套派发未验证，未经实测的效果不作成功声明。

# Beadwork 脚本化与重构验收记录

对应 [实施计划](script-automation-refactoring-plan.md)。本文按目标追加实际结果；未列为完成的目标仍为待实施。测试数量和耗时只代表记录时的源码基线。

## 批次 A：明确缺陷

| 目标 | 实施结果 | 验收证据 |
| --- | --- | --- |
| G01：ticket 累计 boundary gates | ticket checkpoint 保存累计 gates 与来源；同 stage、跨 stage、计划适配、review 和最终验收沿用下限 | 修改前可丢失 `gate-extra` 并通过；修改后未跑新增 gate 被拒绝，当前 HEAD 补跑后通过 |
| G02：ticket review 半成品恢复 | review 材料写出前先在 checkpoint 预留唯一 round；`--resume` 补齐原目录 | 在 `round.json` 写出前注入中断；恢复目录集合不增加，并复用原 round |
| G03：ticket 损坏验证来源的部分 BLOCKED | implementer 固定完整快照，逐条保存 `verification_issues`；损坏来源仅能 blocked/interrupted | 删除 `output.log` 后可交付部分 BLOCKED；正常成功、较晚失败和 worker schema 回归通过 |
| G04：严格 JSON 与受控 schema 一致性 | controller、executor 与 verifier 共用严格 loader；对象形式 `additionalProperties` 执行值校验 | 重复 key、NaN、额外属性值类型错误被拒绝；三个 verifier 的相关回归通过 |

### 批次 A 验证

- 新增五个正式负例；修改前四个行为负例失败，严格 JSON 测试进一步核对具体解析错误。
- 严格 JSON/schema 定向回归：41 项通过。
- G01 同 stage、跨 stage、计划适配及中断恢复：4 项通过。
- G02 ticket/final review 准备、中断恢复和更正：5 项通过。
- G03 核心场景及 worker 完整回归通过。
- 受影响完整定向套件：140 项通过，耗时 353.586 秒。
- 完整脚本回归：242 项通过，耗时 281.660 秒。
- Python 语法、`git diff --check` 和 skill validator 通过；validator 使用隔离 uv/PyYAML 环境，没有修改项目依赖。
- 未运行真实消费项目 ticket graph，也未验证真实 Codex 嵌套派发生命周期。

## 批次 B：共用基础

| 目标 | 实施结果 | 验收证据 |
| --- | --- | --- |
| G05：证据读写与安全发布 | `evidence.py` 统一严格读取、流式 hash、绝对路径、binding 和同目录不覆盖发布；controller/executor/verifier 改用该层 | 目标已存在、序列化失败、重复 key、NaN、symlink 和 binding 篡改均有回归；58 项基础相关测试通过 |
| G06：共用命令记录器 | `process_runner.py` 统一专属进程组、信号、有限等待、强制收尾和日志终态；验证 CLI 与 main-sync 各自保留业务判断和既有证据结构 | `run-verification` 15 项、`main-sync` 18 项通过，包含启动失败、大输出、状态变化、SIGTERM 与强制收尾 |
| G07：共用运行事实 | `verification_records.py` 统一快照、started/result/log 路径与 hash 绑定；ticket 和 final 继续分别判断 gate 覆盖 | ticket 34 项、finalization 13 项及 verifier 套件通过；损坏日志、未知结果和当前 HEAD 覆盖行为保持 |
| G08：共用 review 操作 | `review_operations.py` 统一 append-only 材料发布和双轴来源结构；ticket/final checkpoint 仍各自负责预留、选择与恢复 | ticket 34 项、handoff 22 项通过；两条 round 写出前中断测试改在共用发布层注入并确认复用目录 |
| G09：validator 与策略整理 | `schema_validation.py` 成为无 controller 依赖的受控 schema 引擎，`review_schema.py` 提供双轴 schema，`workflow_policy.py` 集中模型矩阵、阶段数与 gate 修复额度 | ticket/phase/worker verifier 共 39 项、gate repair 9 项通过；CLI 输出及现有模型数值不变 |

### 批次 B 验证

- G05 基础相关回归：58 项通过，耗时 35.234 秒。
- G06 两条调用链：33 项通过；`run-verification` 12.635 秒，`main-sync` 21.448 秒。
- G07–G09 verifier/finalization 定向回归：52 项通过；ticket/executor/handoff/gate-repair 状态回归均通过。
- review 抽取后首次回归准确发现旧故障注入点失效；测试已改为在 `review_operations.evidence.write` 注入，ticket 34 项和 final handoff 22 项分别在 108.516 秒、32.240 秒通过。
- 完整脚本回归：246 项通过，耗时 282.767 秒。
- Python 语法、`git diff --check` 和 skill validator 通过；validator 首次受用户级 uv cache 沙箱限制，按项目规则在宿主权限下重跑通过。
- 用户级 `~/.agents/skills/beadwork-run` 解析到本仓库 `skills/beadwork-run`，源码与实际调用路径一致。
- 未运行真实消费项目 ticket graph、真实 Beads 写入或真实 Codex 嵌套派发。

## 批次 C：结构收敛

| 目标 | 实施结果 | 验收证据 |
| --- | --- | --- |
| G10：控制器、协调器与兼容入口 | `executor_operations.py`、`run_verification.py`、`verify_ticket.py` 成为可普通 import 的实现模块；原带连字符文件保留薄 CLI 包装和原错误 JSON/退出码 | executor 28 项、run-verification 15 项、ticket verifier 16 项和 worker verifier 11 项通过 |
| G11：graph/preflight 解耦 | `flat_result` 与 `frontier_result` 接收结构化事实；preflight 直接调用判定函数，不再替换 `graph.run_bd` 或捕获 stdout | 新增 5 项纯判定矩阵；preflight 12 项通过，覆盖一次查询、错误 JSON、非平铺和范围变化 |
| G15：组装读取 checkpoint 选择 | 当前 ticket/final 流程省略 review/fixer 来源参数时自动使用 checkpoint 选择；显式参数仍可用，但必须完全一致；legacy final 仍要求显式 fixer 来源 | 新增 ticket/final 公开 CLI 场景；ticket 35 项、final handoff 23 项通过 |
| G19：跨路径恢复矩阵 | 新增 graph 分支矩阵及 ticket/final 自动来源组装场景；故障注入已对准抽取后的真实发布 seam；依据 G20 测量保留历史测试类复用，避免无收益的大面积纯测试迁移 | 完整套件从批次 B 的 246 项增至最终 261 项；Git/worktree、进程组、append-only 与恢复边界均保留 |

### 批次 C 验证

- 完整脚本回归：253 项通过，耗时 275.443 秒。
- CLI 包装、任意 cwd 与安装 symlink 使用同一源码真实路径；旧文件名和当前普通 import 均进入回归。
- G19 的恢复矩阵已扩充；普通 fixture helper 的全量迁移按实施调整取消，现有类复用后续随相关 fixture 修改局部收敛。
- 未运行真实消费项目 ticket graph、真实 Beads 写入或真实 Codex 嵌套派发。

## 批次 D：批次首尾脚本化

| 目标 | 实施结果 | 验收证据 |
| --- | --- | --- |
| G12：批次初始化与恢复 | `batch_initialize.py` 绑定 READY preflight、固定 main/children/gates，以 append-only step/log 执行 worktree、install、env-facts、smoke 和 parent claim；重跑复用 ready/step | 临时真实 Git/worktree 与受控 just/bd 成功初始化并重入，claim 只发生一次 |
| G13：只读恢复事实 | `batch_evidence.py inspect` 汇总 Git/worktree、tracker 只读结果、checkpoint 指针、未完成 intent 和冲突；多未完成操作不按时间选择 | 两个未完成 intent 返回冲突；命令不执行 Git/tracker 写入 |
| G14：finalizer 批次 manifest | `batch_evidence.py manifest` 按固定 children 顺序核验 ticket acceptance/report hash，汇总 BASE/HEAD、commits、test plan、concerns 和累计 gates | 缺票、顺序或来源变化由结构和 hash 检查拒绝；单票 fixture 生成 gate 下限 |
| G16：controller 专用 Beads 操作 | `tracker_operations.py` 支持 claim/comment/close intent、读回和重入；comment 使用 intent hash marker，close 绑定成功前置来源 | 4 项 fixture 覆盖 claim 重入、外来 assignee、响应后本地结果丢失、close 前置来源 |
| G17：停止记录与事实汇总 | `batch_evidence.py summary` 将机器事实与 controller 提供的原因、不确定性、建议分开生成，不发布 comment | 摘要可追溯 facts/manifest binding，保留宿主停止状态需外部观察 |

### 批次 D 验证边界

- 初始化与 batch evidence：3 项通过；tracker 协调：4 项通过。
- 已读取本机 `bd` 的 `update --claim`、`comments add`、`close` 和只读 JSON help，据此固定 argv。
- 最终 `full` 维护入口包含本批后共 261 项测试，274.941 秒通过。
- 未对真实项目执行 claim/comment/close，也未运行真实消费项目初始化；fixture 不能替代真实 Beads backend 兼容证据。

## 批次 E：维护与测量

| 目标 | 实施结果 | 验收证据 |
| --- | --- | --- |
| G18：维护检查入口 | `maintenance_check.py` 提供 docs/scripts/full 档位，检查本地链接、`git diff --check`、语法、unittest 和可用 validator，并输出命令、耗时、失败/跳过和限制 | 链接 checker 单元测试通过；真实仓库 docs 档位通过 |
| G20：按证据优化 | 记录完整套件与 ticket/final 热点墙钟；普通 import 清理后未增加跨命令缓存 | [测量记录](script-performance-measurement.md) 显示单次完整套件约降 2.6%，证据不足以宣称稳定加速，因此不做风险更高的缓存 |

### 批次 E 验证

- 真实仓库 `docs` 档位通过；链接与 diff 检查通过。
- 真实仓库 `full` 档位通过：本地链接、`git diff --check`、全部 Python 语法、261 项 unittest（274.941 秒）及 skill validator 均为成功。
- 完整 JSON 结果保存于本机临时文件 `/tmp/beadwork-maintenance-full.json`，不作为仓库证据提交。

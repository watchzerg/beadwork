# Beadwork 脚本化与重构实施计划

日期：2026-09-16。

状态：待实施。本文细化本轮源码分析提出的目标、实施步骤、测试计划和交付标准；编写本文不代表生产脚本已修改，也不代表各目标已经验收。

## 1. 基线、范围与证据

分析基线为当前工作区，包含尚未提交的 agent 交接契约修复。实施前重新记录 Git HEAD、工作区 diff 和安装真实路径，保留原有改动，不能直接把当前 HEAD 当作全部分析内容的基线。

- 检查范围：15 个生产 Python 文件，约 4,880 行；13 个测试文件；skill、角色指令、共享执行与恢复契约。
- 上一轮分析实测：完整回归 237 项通过，耗时 381.641 秒；该结果是分析基线，不是本文所列改进的验收结果。
- 三个流程缺口使用临时 Git/worktree、现有 fixture 和受控命令复现；JSON/schema 差异通过直接调用确认。复现尚未写入正式回归测试。
- 未执行真实消费项目 ticket graph，未验证真实 Codex 嵌套派发生命周期。
- 本文只定义源码仓库的改进，不修改消费项目的 Beads 数据、业务代码、工具链或验证契约。

已有交接修复及验收以 [原修复方案](agent-handoff-repair-plan.md) 和 [原验收记录](../acceptance/agent-handoff-repair-acceptance.md) 为准。本文补充后续工作，不重写原验收结论。

### 1.1 问题可信度

| 类别 | 已掌握的证据 | 本计划中的处理 |
| --- | --- | --- |
| 已复现行为缺口 | ticket 累计 gate 丢失、review 半成品恢复新建目录、日志丢失阻塞部分交付 | G01–G03 先形成正式回归，再修复 |
| 已验证校验差异 | 宽松 JSON 解析；对象形式的 additionalProperties 未执行值校验 | G04 补齐校验并检查入口一致性 |
| 源码可见的恢复风险 | 正式 checkpoint 文件直接写入；多文件准备存在中间状态 | G05 先增加故障注入场景，确认影响边界 |
| 源码可见的维护成本 | 动态加载、反向依赖、重复运行记录解析、legacy 与当前路径混合 | G06–G11 采用行为保持的局部重构 |
| 尚未脚本化的流程 | 初始化、恢复汇总、批次证据汇总、tracker 操作恢复、停止记录 | G12–G18 明确输入、状态与恢复契约后实现 |
| 未量化的性能疑点 | 重复验收、hash、subprocess 和测试 fixture 成本 | G20 先测量；没有收益证据则不优化 |

## 2. 设计边界与实施原则

采用局部补强与按职责提取。保留现有 CLI 入口，必要时增加子命令；新模块名和新命令名在本文中均为拟议名称，实施时以最小充分设计定稿。

| 方案 | 收益与代价 | 选择 |
| --- | --- | --- |
| 只在每个调用点补判断 | 能快速封闭部分负例，但同类协议继续分散维护 | 用于必要的首批局部修复，不作为全部重构方案 |
| 修复缺口并提取共用事实机制 | 保留角色业务差异，减少同一约束在多处漂移 | 本计划采用 |
| 建立通用工作流引擎或全面重写报告协议 | 迁移面大，收益尚无证据 | 不纳入本计划 |

必须保持以下边界：

1. controller 管 Beads 写入、Git/worktree 生命周期和最终集成；子角色权限不扩大。
2. agent 判断需求、覆盖、代码失败根因、seam 授权和 finding 处置；脚本保存判断来源并检查事实与状态。
3. 宿主 agent、后代任务及外部资源是否停止由直接派发者观察。进程组退出、文件出现或 receipt 不替代收尾确认。
4. 保留 ticket/stage/gate-fix 三层循环、既有额度与模型规则；不增加自动重试次数或隐式新 attempt。
5. 保留 branch/worktree 布局、原始报告、回执和 append-only 历史；不批量改写旧证据。
6. 新版严格路径不能因为字段缺失而退回历史宽松路径。新增持久字段需明确版本或能力标识及历史读取行为。
7. 新命令失败时返回可定位的证据和恢复入口；不能把诊断失败解释成空状态、成功或新的执行额度。
8. 保持 Python 标准库实现及现有声明的最低 Python 版本；不为本计划引入通用框架或新的运行服务。
9. 修改 skill 源码前解析安装真实路径；仅编写本文不启动真实工作流。

## 3. 目标总表与依赖

优先级含义：P1 为已确认的协议缺口；P2 为恢复可靠性和明显维护收益；P3 为后续便利性或需要测量才能决定的优化。依赖表示实施前置，不要求每个目标独立创建一个文件或提交。

| ID | 目标 | 优先级 | 主要依赖 |
| --- | --- | --- | --- |
| G01 | ticket 累计 boundary gates | P1 | 无 |
| G02 | ticket review 半成品恢复 | P1 | 无 |
| G03 | ticket 损坏验证来源的部分 BLOCKED 交付 | P1 | 无 |
| G04 | 严格 JSON 与受控 schema 校验一致性 | P1 | 无 |
| G05 | 共用证据读写与中断安全发布 | P2 | G04 |
| G06 | 共用命令记录器 | P2 | G05 |
| G07 | 共用运行事实解析 | P2 | G03、G05 |
| G08 | 共用 review 准备、收集与恢复机制 | P2 | G02、G05 |
| G09 | validator、schema 与模型/额度策略整理 | P2 | G04、G05 |
| G10 | controller、executor、ticket、finalization 职责整理 | P2 | G07–G09 |
| G11 | graph/preflight 的查询与判定解耦 | P2 | 无；读写基础层可在 G05 后接入 |
| G12 | 批次初始化与初始化恢复 | P2 | G05、G06、G11；tracker 写入接 G16 |
| G13 | 只读恢复事实汇总 | P2 | G01–G03、G05；分批接入 G12、G16 |
| G14 | finalizer 批次输入 manifest | P2 | G01、G05 |
| G15 | 报告组装直接使用已选证据 | P2 | G01–G03、G08 |
| G16 | controller 专用 Beads 操作核对与重入 | P2 | G05、G11 |
| G17 | 停止记录与最终事实汇总 | P3 | G13、G14、G16 |
| G18 | 源码仓库维护检查入口 | P3 | 可先做文档检查；其余跟随模块整理 |
| G19 | fixture 整理与跨路径恢复测试矩阵 | P2 | 与各目标同步，不阻塞首批缺陷回归 |
| G20 | 验收与测试成本测量及定向优化 | P3 | 先测量；优化待相关重构稳定 |

## 4. 逐项目标、实施与测试计划

### G01：持久化 ticket 累计 boundary gates

**目标与问题。** implementer 已被验收的部分报告新增 `gate-extra` 后，同 stage 后续报告可以删除该 gate，未运行它仍通过整票 controller 验收。必须让已确认 gate 成为后续交付不可遗漏的累计下限。

**修改范围。** [ticket_execution.py](../../skills/beadwork-run/scripts/ticket_execution.py)、[handoff.py](../../skills/beadwork-run/scripts/handoff.py)、相关 schema、[ticket 执行契约](../../skills/beadwork-run/references/ticket-execution.md) 与 executor 指令。

**实施步骤。**

1. 在 ticket checkpoint 增加累计 gate 集合及来源，初始化为 root 下限；定义新增字段的版本识别和历史恢复规则。
2. 提供 executor 使用的显式新增入口，新增边界确认后立即追加，不等待 writer 成功；验收 implementer 报告时同样合并报告中的新增边界。
3. 同 stage 恢复、跨 stage、计划适配和 reviewer dispatch 均读取累计下限；不得通过新 dispatch 或更正报告减小集合。
4. implementer 成功验收、review 准入、ticket 成功验收均检查累计集合在交付 HEAD 的真实覆盖。
5. 历史 checkpoint 缺字段时，仅从明确绑定的原始来源重建；来源不全则阻塞，不能假设 root 下限代表全部义务。

**测试计划。** 先通过公开 CLI 固化已复现负例。再覆盖：同 stage 中断恢复保留 gate；跨 stage 和 adapt-plan 保留 gate；重复新增去重；未跑 gate 拒绝成功；只在旧 HEAD 跑过仍拒绝；在当前 HEAD 补跑后通过；新增来源改写被拒绝；仍可交付未跑完 gates 的合法 BLOCKED。

**完成标准。** 整票成功不能遗漏任何已持久化的累计 gate；review 输入、完成 comment 与验收使用同一个集合，原始报告不被修改。

### G02：补齐 ticket review 半成品恢复

**目标与问题。** 在 `round.json` 写出前中断后，ticket 的 `review-prepare --resume` 会新建目录；finalization 已能复用预留目录。

**修改范围。** `executor-operations.py`（历史入口；当前实现为 [executor_operations.py](../../skills/beadwork-run/scripts/executor_operations.py)）、ticket checkpoint 和 review 恢复说明。

**实施步骤。**

1. 在创建 reviewer 材料前持久化唯一 round 预留路径及固定 BASE/HEAD。
2. 普通 prepare 已有预留时拒绝另建 round；显式 resume 只补原目录缺失的材料。
3. 已存在文件按身份和内容核对，冲突时停止；完整 round 继续通过原选择和更正流程处理。
4. 恢复期间保持 writer 冻结，不重新分配 reviewer 轮次或 gate-fix 额度。

**测试计划。** 在第一个轴、第二个轴、round 文件及绑定 checkpoint 各边界注入失败；恢复后目录和 round 身份保持不变。覆盖已有完整 round 再 prepare、BASE/HEAD 变化、半成品内容冲突、只有一个轴完成、同 round 更正及旧 stage 恢复。

**完成标准。** 一个逻辑 stage 始终只有一个获准 round；半成品可恢复，冲突不可静默覆盖。

### G03：允许 ticket 对损坏验证来源交付部分 BLOCKED

**目标与问题。** 验证日志缺失时，implementer 组装器直接失败；共享契约要求保留问题来源并能交付部分阻塞。finalization 已有对应机制。

**修改范围。** ticket 的组装、自检、验收和阶段/root 交付；[验证采集](../../skills/beadwork-run/references/verification.md)、报告 schema。参考 [final_verification.py](../../skills/beadwork-run/scripts/final_verification.py) 的现有行为。

**实施步骤。**

1. 区分完整、结果未知、来源损坏三类记录；未知结果和损坏来源不合并为一个成功布尔值。
2. 为 ticket 报告增加明确的问题来源、原绑定和诊断字段，保留可读取的原始来源，不伪造缺失日志。
3. 允许 `blocked`/`interrupted` 交付，禁止损坏来源支持 DONE、review 准入或 code_failure 阶段推进。
4. executor/controller 能验收这类部分交付；修复证据后用新报告更正，原报告和问题记录保留。
5. 原 dispatch/checkpoint 自身不可读取时，停止并返回可定位诊断；不承诺重建无法证明的身份链。

**测试计划。** 缺日志、日志 hash 错误、缺 result、started 损坏、已验收 implementer 的日志随后损坏；分别验证部分交付、成功拒绝、repair 拒绝和后续更正。正常失败历史与后续成功重跑仍能合法交付。

**完成标准。** 可确定身份的证据故障能被正式交还上层；交付阻塞不授予继续写入或额外修复机会。

### G04：统一严格 JSON 与受控 schema 校验

**目标与问题。** `controller.read()` 接受重复 key/非有限数值；schema 引擎未执行对象形式的 `additionalProperties`。

**修改范围。** 所有输入/证据 JSON loader、`verify-ticket.py`（历史入口；当前实现为 [verify_ticket.py](../../skills/beadwork-run/scripts/verify_ticket.py)）的 schema 引擎及三个 verifier 调用入口。

**实施步骤。**

1. 提取单一严格 JSON loader：明确 UTF-8，拒绝重复 key、NaN、Infinity 和非法 JSON，保留原字节 hash。
2. 实现当前 schema 已使用的 `additionalProperties` 子 schema 校验，并在 schema 自检时递归检查该规则。
3. 检查当前全部 schema 使用的关键字，保证支持集合与实际行为一致；未知关键字明确拒绝。
4. 各入口共用解析方式，诊断保留文件路径和字段位置；有效旧 JSON 不因模块迁移改变结果。

**测试计划。** 对重复 key、非有限数值、错误编码、截断 JSON、额外属性值类型错误和不支持关键字做负例；真实生成的各角色 schema 全部自检。通过 controller、executor、三个 verifier 代表入口检查一致拒绝，而非只测 helper。

**完成标准。** 同一非法输入不会因入口不同获得不同解释；schema 声明的既有规则均被执行。

### G05：共用证据读写与中断安全发布

**目标。** 集中路径、严格读取、流式 hash、binding 和完整文件发布；减少正式 checkpoint 写到一半而阻塞整个恢复链的风险。

**修改范围。** controller 的 IO helper、executor 的 binding/bound、ticket/final/context checkpoints、report/receipt 发布。拟提取小型 `evidence.py`，不得依赖 controller 或业务状态模块。

**实施步骤。**

1. 先列出现有路径、hash、不可覆盖及相对目录规则，按 G04 的严格 loader 统一基础函数。
2. 在同目录写临时文件，完整关闭后采用不覆盖既有目标的发布方式；实现与最低 Python/POSIX 支持范围一致。
3. 正式 checkpoint 只扫描已发布文件；临时文件保留为诊断材料，不能计入阶段或编号。
4. 多文件准备使用明确 intent/reservation 和完成绑定；恢复核对已有文件，不按 mtime 挑选结果。
5. 历史损坏的正式 checkpoint 不静默跳过；给出具体阻塞。若增加修复入口，必须单独设计证据绑定，不能伪造连续链。

**测试计划。** 写入中、发布前、发布后注入失败；目标已存在时不覆盖；重复操作对相同结果可核对，对不同结果拒绝；验证 symlink、相对路径、跨目录来源、空文件和大日志。检查新 checkpoint 不完整时旧已发布状态仍可读取。

**完成标准。** 新操作不会以半个正式 JSON 充当有效证据；不覆盖历史。这里只证明进程中断恢复，不把它描述为未经测试的断电持久性保证。

### G06：提取共用命令记录器

**目标。** `run-verification.py`（历史入口；当前实现为 [run_verification.py](../../skills/beadwork-run/scripts/run_verification.py)）与 [main_sync.py](../../skills/beadwork-run/scripts/main_sync.py) 共用进程组、取消、日志和执行终态采集。

**实施步骤。**

1. 提取不理解 ticket、stage、recipe 或代码根因的执行函数，接收 argv/cwd 和调用方明确提供的环境与输出路径。
2. 统一 started、日志、退出码、信号、收尾结果和 recorder error 的采集；不把完整环境变量写入日志。
3. 保留两种调用方原有证据格式，通过局部适配组装，避免重写旧运行记录。
4. recipe 准入、HEAD/status 检查、delivery attempt 和同步成功规则继续由各自调用方负责。

**测试计划。** 正常成功、正常失败、启动失败、二进制/大输出、SIGTERM/SIGINT、子进程未退出、必须强制收尾、记录器被中断；分别通过验证 CLI 与 main-sync CLI 验证结果。保留真实专属进程组测试，不能全部 mock。

**完成标准。** 两个调用方保持原退出码和恢复语义；未知或未收尾任务不能成为有效成功。外部容器/脱离进程组任务仍由 agent 确认。

### G07：共用运行事实解析，分开覆盖策略

**目标。** 消除 ticket/final 对 dispatch、started/result/log、快照和未知结果的重复解析，避免再次出现 G03 类型差异。

**实施步骤。**

1. 提取只读运行记录模型及校验函数，统一文件绑定、目录归属、argv、时间排序、进程状态与内容 hash 校验。
2. 共用快照读取和问题诊断；历史交付按固定快照核验，新交付必须包含当前应收集的运行。
3. ticket 的 gate-unit/boundary 和 finalization 的 final/组合参数覆盖分别保留为小型策略函数。
4. 同 gate、同 HEAD 的较晚失败不能被较早成功覆盖；较晚未知结果必须显式处理并补足有效后续验证，不能悄悄忽略。
5. 报告原有展示字段通过适配生成，不强制统一 ticket 与 final 的外部 schema。

**测试计划。** 共用契约矩阵覆盖错 dispatch、错 cwd、错 hash、重复快照、缺结果、损坏日志、旧 HEAD、dirty、较晚失败/未知、补跑成功。ticket/final CLI 分别验证覆盖规则；组合 final 无有效契约时不算子 gate 通过。

**完成标准。** 来源真实性只有一套核心判定，角色覆盖义务仍明确区分；原报告与当前完整验收结果保持一致。

### G08：共用 review 操作机制

**目标。** 在 G02 修复后提取 review 准备、轴身份、报告收集和来源校验，减少 executor CLI 与两个状态模块的交叉依赖。

**实施步骤。**

1. 把 review 文件准备、两轴结构校验、collection 生成移入聚焦模块。
2. ticket/final 各自负责业务准入与 checkpoint 选择，共用预留/补齐的文件机制；只定义当前两种路径需要的显式函数。
3. reviewer 独立上下文、模型、已有行为审查和本轴前次来源继续由 dispatch 固定。
4. 每阶段唯一 round、同 HEAD 更正、旧报告失效和原 findings 保留规则保持不变。

**测试计划。** 复用 G02，并对 ticket/final 运行两轴缺失、交叉轴报告、错 HEAD、阻塞 collection 被遗漏、同 round 更正、已封存 stage 重选和缺 closure 场景。

**完成标准。** 公开 `review-prepare`/`review-collect` 行为稳定；没有因重构增加 round、改变模型或削弱双轴独立性。

### G09：拆分 validator/schema，集中模型与额度策略

**目标。** 三个 verifier 不再通过加载另一个 CLI 获得基础能力；模型与额度使用明确的单一代码来源。

**实施步骤。**

1. 分离受控 schema 引擎、共用结构与各角色 schema，CLI 仅负责参数、输出和退出约定。
2. 保留结构自检、来源验收、Git 现场验收的不同职责，不把结构 PASS 描述为完整交付 PASS。
3. 对现有 `ok:false` 与非零退出、`--emit-receipt` 的契约先做特征测试；纯重构不顺便统一退出语义。
4. 将模型矩阵和修复额度置于不依赖 controller 的策略模块；清理重复硬编码值，保持当前数值和模型不变。
5. 用受控 schema 工厂生成 implementer 等角色定义，减少先取 executor schema 再删除字段的隐式耦合。

**测试计划。** 各角色 schema/receipt、合法部分 BLOCKED、非法成功、旧格式、无提交完成、模型只升级与额度耗尽。对迁移前后有效/无效样本比较验收结果；检查文档模型表与代码事实一致。

**完成标准。** CLI 调用和输出保持兼容；共享校验模块可普通 import，schema 不依赖执行控制器。

### G10：整理控制器、协调器与 legacy 职责

**目标。** 让 controller 保留批次操作，executor 保留命令路由，ticket/finalization 保留各自阶段业务；隔离历史兼容逻辑。

**实施步骤。**

1. 在 G07–G09 后绘制实际 import/调用关系，逐步移除基础层对业务层的反向依赖和重复动态加载。
2. controller 的派发准备、验收、comment、merge/cleanup 按实际耦合分组；仅在职责独立时新增模块。
3. ticket 分离状态存取与 implementer 交付；finalization 分离 legacy 导入和当前阶段准备，继续复用已有 final_state/final_verification。
4. 核对 controller 旧 `prepare_stage()` 等函数的生产与测试调用方；只供测试构造旧输入的部分移入 fixture，仍用于历史读取的部分保留为明确兼容入口。
5. 修正 stale 注释、角色名称、错误信息；不批量改字段名或历史路径。

**测试计划。** 公开 CLI 从任意 cwd、源码真实路径和安装 symlink 路径运行；当前 root→stage→writer→review→deliver→accept 场景及明确标识的 legacy 场景全部通过。执行完整套件和资源引用检查。

**完成标准。** 业务模块通过普通 import 使用共用能力；测试专用准备流程不再混淆当前生产入口；没有以拆文件数量作为完成指标。

### G11：解耦 graph/preflight 查询与判定

**目标。** preflight 不再替换 graph 全局函数并捕获 stdout；graph 分支可以直接、完整测试。

**实施步骤。**

1. 将 children/ready/边查询与 flat/frontier 判定分开，判定函数接收结构化事实并返回结果。
2. CLI 保持既有 JSON、业务阻塞 exit 0 和输入/命令错误非零的契约。
3. preflight 使用同一判定函数并保存查询证据，删除全局替换与 stdout 捕获。
4. 统一重复 ID、非法记录和未知状态的处理；priority 与依赖排序仍由 Beads ready 决定。

**测试计划。** 增加 `test_graph.py`：空 children、集合增删、重复 ID、缺 label、多个 in_progress、唯一 resume、全部 closed、无 ready、候选身份/状态/assignee 不符、无效 JSON 和命令失败。CLI fixture 另验证只读参数、批量查询和返回协议。

**完成标准。** graph 全部分支有可观察结果覆盖；preflight 不增加重复查询或改变既有选择顺序。

### G12：脚本化批次初始化与恢复

**目标。** 将 worktree/Beads workspace 核对、install、env-facts、BASE smoke、parent 领取及批次记录组织成可恢复流程。

**修改范围。** controller 专用批次入口、[初始化流程](../../skills/beadwork-run/SKILL.md)、[批次恢复](../../skills/beadwork-run/references/recovery-batch.md)。

**实施步骤。**

1. 输入绑定 READY preflight acceptance、固定 children、基线来源、smoke gates 与安装输入；生成只追加的初始化 intent。
2. 将 worktree 创建/复用、workspace 核对、安装、环境与冒烟、parent claim、批次 comment 分为明确步骤，保存实际观察结果。
3. 先实现准备、执行证据和 tracker 回执核对；在 G16 完成后接入 controller 专用写入，不自行扩展子角色权限。
4. 写入后重新观察现场：branch/worktree 错配、领取身份冲突或缺基线证据时停止。
5. 中途失败沿用原 intent；有 ticket 工作时不重跑初始化 BASE smoke，不猜测 BASE，也不重建已有 branch。

**测试计划。** 从空批次成功初始化；branch 存在但 worktree 缺失；workspace 不共享；install/smoke 失败；parent claim 竞争；每步成功后、记录前中断；comment 已写但本地结果未保存；已有 dirty ticket 工作的恢复拒绝。真实 Git 配合受控 bd/just fixture。

**完成标准。** 新 child 开工必须有可核验的初始化完成来源；重跑不重复领取、不重置现场、不覆盖历史，所有未知结果都有明确恢复位置。

### G13：增加只读 recovery-inspect

**目标。** 自动汇总恢复所需事实，减少从 comments 和证据目录人工拼接身份。

**实施步骤。**

1. 输入 repository/parent 和可选明确 root 指针，采集 Git topology、children、相关 comments、初始化、ticket/final checkpoints 和 merge 记录。
2. 输出当前有效身份、BASE/HEAD、selected sources、额度、未完成操作、缺失事实、冲突列表与候选恢复动作。
3. 新证据按明确绑定解析；旧 comment 只解析有结构身份的内容，自由文本不作自动成功依据。
4. 多 root、多 attempt 或互相冲突的指针返回歧义，不按时间挑最新；schema/身份可读时尽量返回部分诊断。
5. 宿主停止状态标为需要外部观察；命令不执行 claim、install、merge、cleanup 或 agent 派发。

**测试计划。** 初始化半成品、dirty ticket、已选 review 未 assemble、部分 BLOCKED、finalizer 接替、merge 前后、parent 已关但清理未完；多候选、错误 hash、缺 BASE、旧格式记录不足及远端不可达。验证只读命令清单。

**完成标准。** 同一现场得到确定的事实与缺项；报告恢复动作前不改变现场，且不把无法确认的状态推断成可执行。

### G14：生成 finalizer 批次输入 manifest

**目标。** 从已验收 ticket 来源生成批次边界和验证下限，减少 controller/finalizer 重复手工汇总。

**实施步骤。**

1. 输入固定 children 集合和各票明确的 acceptance/completion pointers，验证 ticket 身份、来源 hash 和完成状态。
2. 汇总执行顺序、每票 BASE/HEAD、commit ranges、有效计划、累计 gates、原始 smells 及来源指针。
3. 机械区分 ticket 实现提交与票间 main-sync 提交；不把所有提交混作实现范围。
4. manifest 绑定所选来源；finalizer prepare 从 manifest 派生 gate 下限，额外影响边界仍由 agent 判断并记录来源。
5. 历史验收读取使用历史身份与快照检查，不能要求所有旧票的交付 HEAD 等于当前批次 HEAD。

**测试计划。** 多票不同 gate 的并集、无提交完成、适配计划、票间同步、缺票/重复票/其他 parent、来源改写、遗漏累计 gate、completion 指向错误报告；验证补充 gate 不因 gate-unit/gate-full 去重而误删。

**完成标准。** 固定 children 与 manifest 一一对应；finalizer 输入不能手工删减机械可确定的 gate 下限，语义补充可继续追加。

### G15：报告组装直接读取 checkpoint 选择

**目标。** checkpoint 已保存的 fixer/review 来源无需调用者重复转填，减少合法流程中的机械错误。

**实施步骤。**

1. ticket/final 正常 assemble 自动读取当前 stage、prior sources 和已选来源。
2. 保留现有显式参数作为一致性检查或明确 legacy 用途；当前路径提供时必须与 checkpoint 完全一致，不能覆盖选择。
3. 输出草稿模板或字段提示时只保留需 agent 填写的语义字段；阶段、HEAD、commits、验证记录由脚本生成。
4. receipt 与 closure binding 支持直接保存到新路径，减少手工转换；原始字节和 hash 绑定规则保持。

**测试计划。** 不传来源列表的正常组装；显式列表遗漏、重排或跨 stage 被拒绝；review 更正后旧 selected_stage 失效；缺选择不能自动挑报告；同 HEAD 更正及中断重试保留原件。

**完成标准。** 正常组装不要求 agent 搬运已有的完整来源数组；控制器验收与原始来源检查没有减少。

### G16：controller 专用 Beads 操作核对与重入

**目标。** 对 claim、start/completion/stop comment、close 的未知结果和重复执行提供确定的恢复行为。

**契约变化。** 当前文档规定内置脚本不写 Beads。本目标实施时明确修订为“仅 controller 调用专用写入入口”，子角色保持只读。代码与文档在同一交付中更新。

**实施步骤。**

1. 先查询当前 bd 帮助并核对目标项目 tracker 契约，确定实际支持的 claim、comment、close 和读回字段，不凭假定设计 API。
2. 为每次操作保存 intent，绑定 parent/ticket、预期状态、报告 hash、正文来源和操作身份。
3. 执行前核对前置条件；执行后只读查询，保存实际状态/comment ID 与观察结果。
4. 命令退出或结果保存中断时先读回协调；已确认相同 comment/状态则复用。缺少可确定身份时报告 unknown，不盲目重发。
5. close 必须有对应成功交付和完成 comment；parent close 还需合入事实。claim 竞争仍交还 frontier，不建立跨系统原子事务假象。

**测试计划。** 使用可持久化且支持故障注入的 bd fixture：claim 竞争、他人领取、comment 成功但响应丢失、close 成功但本地记录缺失、重复调用、正文/报告 hash 改变、错误 ticket、读回失败。核对不会重复 comment、误关票或越过前置条件。

**完成标准。** 可证明已完成的操作可重入；不确定结果不能自动当作未执行。实际 Beads 集成验证单独标明环境与覆盖，不以 fixture 代替真实兼容证据。

### G17：生成停止记录与最终事实汇总

**目标。** 自动整理可证明的进度和恢复指针，减少人工遗漏及重复抄写。

**实施步骤。**

1. 输入 recovery-inspect/manifest、当前停止报告和操作记录，生成机器事实区及来源。
2. agent 另填根因判断、剩余不确定性、建议和依据；事实未知时输出 unknown，不补造结论。
3. ticket 细节留在 child，parent 停止记录保留摘要与指针；最终汇总包含验证、review、smells、main SHA 和清理事实。
4. 文本生成与发布分开，controller 通过 G16 写入并记录 comment ID。
5. 对“未 push”等超出局部证据可证明范围的声明，区分本流程操作记录与外部行为，不从文件缺失推断全局事实。

**测试计划。** 部分完成、frontier blocked、未确认收尾、最终 gate 阻塞、main 移动、合入成功但清理失败；源文件缺失时保留 unknown。检查报告身份和指针，不为中文措辞写脆弱快照测试。

**完成标准。** 报告事实均能回溯来源，语义判断有单独输入；生成报告本身不推进工作流或改变 tracker。

### G18：增加仓库维护检查入口

**目标。** 把重复执行的源码维护检查收敛成一个轻量入口，避免每次临时拼命令。

**实施步骤。**

1. 提供显式检查档位：文档、脚本定向、完整套件；根据改动提供建议，调用者仍可选完整档位。
2. 文档档位检查本地链接、命名、git diff --check；新计划中明确标为拟议的文件名不当作必须存在的资源。
3. 脚本档位检查语法、schema、自检入口和相关测试；跨脚本协议或目录迁移使用完整套件。
4. skill 变更调用可用 validator，核对资源相对路径、agents/openai.yaml 与安装真实路径。validator 不可用时明确报告缺项，不虚报通过或自动安装依赖。
5. 输出每项命令、结果、耗时与未验证范围；不启动真实 ticket graph，不修改安装 symlink。

**测试计划。** 正确/断裂链接、缺资源、schema 生成失败、某个检查非零、validator 缺失、纯文档选择和完整档位选择；一次在真实仓库运行文档档位及适用的脚本档位。

**完成标准。** 维护者能用单入口复现本仓库检查；检查失败和跳过可区分，验证范围不会被夸大。

### G19：整理 fixture，建立跨路径恢复测试矩阵

**实施调整（2026-09-16）。** 本轮完成跨路径恢复矩阵和真实入口覆盖；不执行“把全部历史测试类改写为普通 fixture helper”的全量迁移。测量显示套件主要耗时来自刻意保留的 Git/worktree 与进程边界，批量搬移测试构造不会降低该成本，却会产生大面积纯测试 churn。现有测试类复用暂时保留，后续只在修改相应 fixture 时局部迁移；这项调整不减少下列恢复矩阵和生产边界。

**目标。** 保留真实边界测试，减少测试类相互实例化及旧流程构造对当前覆盖的混淆。

**实施步骤。**

1. 把临时 Git/worktree、受控 bd/just、来源文件和清理逻辑移入普通 fixture helper；测试类不再调用其他测试类的 setUp。
2. 当前成功路径通过公开 root→stage→writer→review→deliver→accept CLI 建立；手工构造报告用于结构负例和明确 legacy 场景。
3. 为 ticket/final 共用一组恢复场景定义，各自运行业务适配；不把生产校验函数复制进测试作为 oracle。
4. 覆盖 gate 累计、唯一 review、未知/损坏运行、收尾、来源更正、阶段额度和 append-only 不变量。
5. 只共享 fixture 构造代码，不共享会泄漏状态的可写仓库或运行进程。新状态序列可用有限枚举，不引入通用模型测试框架。

**测试计划。** 分别运行整理前后的完整套件；关键 CLI 场景单独执行，检查临时资源清理和测试顺序独立性。对历史格式与当前格式分别统计场景，不以测试总数不减少作为唯一标准。

**完成标准。** 当前协议有真实入口覆盖，legacy 明确标识；测试重构不减少 Git、进程组、原始运行记录和 controller 验收边界。

### G20：测量验收与测试成本，按证据优化

**目标。** 确定重复加载、hash、来源遍历和 subprocess 的实际成本，仅优化有明显收益的部分。

**实施步骤。**

1. 在固定 fixture 上测量简单成功、四阶段修复、历史来源较多和大日志场景；记录墙钟、子命令次数、hash 字节数及模块加载次数。
2. 测量只写临时证据，不把环境差异或并发干扰归因于代码；保留基线条件和重复测量分布。
3. 优先消除重复动态加载及同一调用内部的无效重复工作；如缓存文件内容或校验结果，必须绑定该次读取及一致性检查。
4. 不跨独立命令长期缓存验收结果；后续 accept/merge 仍需核对实时现场及来源变化。
5. 测试性能优先优化 fixture 构建与冗余进程，保留独立工作区和真实中断/资源测试。没有可重复收益则只交付测量结论。

**测试计划。** 优化前后运行相同场景，比较输出和全部拒绝行为；增加两次调用之间来源改写必须被发现的用例。报告中列出原始数据、波动和未优化原因，不预设必须达到的加速比例。

**完成标准。** 所有优化都有可重复测量及行为不变证据；允许结论为“当前无需优化”。

## 5. 测试策略与执行命令

### 5.1 测试模式与观察边界

按 [测试计划契约](../../skills/beadwork-run/references/testing-plan.md) 区分行为修复与纯重构。本计划不是 Beads ticket graph，也没有新增或宣称批准任何 spec seam；后续若转为 TDD tickets，按 [seam 契约](../../skills/beadwork-run/references/testing-seams.md) 明确引用已批准的观察接口。

- G01–G04 的负例先在修改前实测失败，记录失败断言和输入；这里的失败是“应拒绝却通过”或“合法阻塞/恢复应成功却失败”，不是任意非零退出。
- G05 和新增脚本命令补充真实可观察的中断/错误行为测试；先确认现场与预期，再实现。
- G06–G11 的纯提取部分采用 direct verification，复用既有行为 oracle；若同时修复新行为，单独列出该行为及回归，不制造空的 red。
- G12–G17 的可观察接口是 CLI JSON/退出结果、实际 Git/Beads fixture 状态及落盘证据；不可用生产内部函数的返回值代替完整操作结果。
- 本仓库使用 Python unittest；[目标项目 gate 契约](../../skills/beadwork-run/references/testing-gates.md) 不意味着需要给本仓库虚构消费项目的 just recipes。

### 5.2 必测恢复矩阵

| 观察点 | 正常路径 | 中断/错误路径 | 必须保持的不变量 |
| --- | --- | --- | --- |
| 初始化 | install/smoke、claim/comment 完成 | 任一步完成前后中断、竞争失败 | 基线固定、旧工作保留、不得提前开 child |
| gate 义务 | 累计 gate 在当前 HEAD 通过 | 部分报告后恢复、适配或换 stage | 已确认义务不丢失 |
| 验证来源 | 完整日志与退出结果 | 未知结果、损坏 hash、缺文件 | 不能冒充成功或代码失败推进 |
| review | 唯一 round、两轴收集 | 准备半成品、缺轴、更正 | 不增加 round，旧报告失效但原件保留 |
| writer 交付 | DONE 后冻结 | stopped 未确认、报告更正 | 不提前派接替 writer |
| 阶段推进 | code_failure 且有来源 | 原因不明、额度不足或已耗尽 | 不跳阶段、不重置额度 |
| tracker | 写入后读回一致 | 响应丢失、读回失败、重复请求 | 不重复 comment、不误 claim/close |
| 合入/清理 | 固定受审 HEAD 合入并清理 | main 移动、checkpoint 中断、部分清理 | 既有 merge/cleanup 安全条件保持 |

### 5.3 回归命令

从仓库根目录运行单文件定向回归，例如：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_ticket_execution.py'
```

依据目标选择现有 test_handoff、test_run_verification、test_main_sync、test_executor_operations、test_controller、test_finalization、test_verify_* 等文件；新增测试文件在实现后进入同一 discover 目录。

跨脚本协议改动、模块迁移或批次交付运行完整套件：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_*.py'
git diff --check
```

测试需要创建临时 Git 仓库与 worktrees，按当前执行权限申请窄范围权限。测试日志放临时目录；不得把真实项目证据或本机备份加入仓库。每次测试记录源码基线、命令、结果与覆盖边界。

## 6. 建议实施批次与交付门槛

| 批次 | 内容 | 进入下一批的门槛 |
| --- | --- | --- |
| A：明确缺陷 | G01–G04；G19 仅补必要回归 | 已复现负例变为预期结果，合法成功/阻塞/恢复通过；完整套件通过 |
| B：共用基础 | G05–G09，先事实 IO，再运行和 review；G20 收集基线 | 旧证据可读，CLI/字段稳定，中断矩阵通过，完整套件通过 |
| C：结构收敛 | G10、G11、G15、G19 的 fixture 整理 | 当前/legacy 入口区分清楚，跨 cwd/安装路径与 schema 验证通过 |
| D：批次首尾 | 先 G16，再完成 G12；接 G13、G14、G17 | 初始化、未知 tracker 结果、恢复和汇总的公开 CLI 场景通过；权限契约同步更新 |
| E：维护与优化 | G18，G20 的有证据优化 | 维护入口可复现；性能改动有测量与完整行为回归，无收益可不改 |

G13、G14 可在前置完成后提前实现只读部分。上述批次是依赖与验收顺序，不授权自动运行消费项目、创建真实 tickets、提交或 push。

每批交付记录应包含：

1. 完成的目标 ID、实际修改范围与未完成事项。
2. 新增/调整的 CLI、字段、版本识别及历史恢复行为。
3. 修改前负例与修改后结果；纯重构注明复用的行为验证。
4. 定向与完整测试命令、结果、耗时；skill validator、资源引用、策略与安装真实路径检查结果。
5. 真实 bd/宿主嵌套派发是否验证，未验证时明确保留限制。
6. 原始证据、未提交现场、模型及阶段额度保持情况。

每批完成后先验收再继续；出现与既有协议冲突时记录具体目标和证据，修订计划，不以通用重构为由扩大到无关功能。

## 7. 本计划文档的完成标准

- G01–G20 均有明确目标、实施步骤、测试场景和完成标准。
- 已复现缺陷、静态风险、设计改进与性能假设明确区分。
- 依赖顺序可执行，当前接口与拟议接口不混淆。
- 本地链接、目标编号、文件命名及 git diff --check 通过。
- 文档编写不改变生产脚本或现有工作流；本次文档交付不重跑真实 ticket graph。

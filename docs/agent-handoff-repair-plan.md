**Agent 交接契约修复方案**

状态：五项修复已实施并完成逐项验收，最终完整脚本回归 237 项通过。本文保留 2026-09-16 批准的实施边界、契约变化与验收条件；实际结果及验证边界见 [逐项验收记录](agent-handoff-repair-acceptance.md)。

依据为当前 [架构文档](ARCHITECTURE.md)、[执行入口](../skills/beadwork-run/SKILL.md) 及脚本实现。审查中已用临时 Git fixture 复现：同一 finalizer stage 重开 review 后只选择 PASS 可通过 controller 机械验收；fixer 缺少验证和修复额度证据的 code_failure 可通过 worker 校验；补充 boundary gate 可在最终阶段交接中丢失并通过机械验收。现有 finalizer 的 13 项回归通过，说明这些负例尚未受到既有测试约束。

**设计选择与范围**

采用局部补强方案：以 ticket 链路已经具备的检查点、验证来源快照及来源选择规则为参考，补齐 finalizer/fixer；把跨角色的必要输入持久化；为最终交付增加脚本入口。

| 选项 | 效果与代价 | 决定 |
| --- | --- | --- |
| 只补角色提示词或多加人工复核 | 改动小，但不能拒绝已经复现的错误交接 | 不采用 |
| 补齐现有脚本的状态、来源与输入检查 | 能封闭负例，保留现有角色及执行方式 | 采用 |
| 重建通用 agent 编排框架、统一所有角色 schema | 迁移面大，超出当前项目需要 | 不采用 |

保留 controller、preflight、executor、implementer、finalizer、fixer 与双轴 reviewer 的职责；保留 ticket/stage/gate-fix 三层循环、模型规则、四阶段及每 writer stage 三次 gate-fix 的额度。保留既有报告字段、短回执、branch/worktree 布局、append-only 历史和 controller 独占 Beads/最终集成。只增加必要的来源字段、检查点与脚本入口，不增加 agent 层级。

agent 继续负责需求、覆盖、失败根因和 finding 处置的语义判断。脚本校验身份、状态、来源、运行结果和额度。宿主任务是否结束由直接派发者确认，文件 hash 或脚本进程退出不替代这一判断。

**修复一：固定 finalizer 每阶段唯一 review 及其选择**

目标：每个逻辑 stage 只有一个有效 review round；已完成的审查不能通过遗漏来源或重开 round 被替代。报告更正在原 round 内进行，原始报告继续保留。

在 finalizer 的 attempt 目录增加 append-only 检查点，记录当前 stage dispatch、当前 fixer 的已验收来源、唯一 review round、selected_review 和 selected_stage。检查点绑定原 attempt、前一检查点及所选文件 hash；同一 attempt 只能由一个 finalizer 更新。状态以明确选择为准，不按目录时间推测。

流程约束：

1. `final-stage resume` 返回当前逻辑 stage 的选择与恢复指针；恢复不清空已选 fixer、review 或额度。可以沿用现有接替 dispatch，但必须绑定同一逻辑 stage 的检查点。
2. `review-prepare` 对 finalizer 执行独立准入检查：stage 0 已有有效最终验证；stage 1..3 已验收 fixer DONE，且必要 gates 覆盖候选 HEAD。派发者另确认旧任务结束。
3. 首次准备固定 round。重复请求返回原 round 或明确拒绝新建，不能生成第二个有效 round。准备中断留下的半成品目录保留，通过显式恢复入口完成原准备，不隐式发放新轮次。
4. `review-collect` 成功后立即保存 selected_review。若 collection 已写出而检查点尚未写出，恢复使用原 round 与明确的 selection 输入重新验收并追加选择。
5. 同 HEAD 的报告更正只接受原 round 的来源；选中新 collection 后使旧 selected_stage 失效，必须重新组装才能交付或推进阶段。更正不改代码，也不增加 review 次数。
6. `final-assemble`、阶段推进、`final-deliver` 和 controller accept 均核对检查点选择。不得漏掉已选 review，不得使用更正前的阶段报告，也不得在进入下一 stage 后重新选择旧 stage 的结果。
7. review 已开始后冻结 writer。中断恢复继续缺失轴或报告更正；完整代码类 blocking review 只能 repair 到下一 stage，非代码阻塞停留原 stage。

主要落点：[finalization.py](../skills/beadwork-run/scripts/finalization.py)、[executor-operations.py](../skills/beadwork-run/scripts/executor-operations.py)、[gate_repair.py](../skills/beadwork-run/scripts/gate_repair.py) 和 controller 的最终验收入口。优先参考 ticket 的检查点实现，不提前抽象通用工作流引擎。

验收负例与恢复用例：

- 第一轮 BLOCKED 后同 stage 请求第二轮，不能形成新的可选 round；只传第二轮 PASS 无法交付。
- collect 后、assemble 前中断，恢复仍选中原 collection。
- 缺一轴时恢复原 round；完整 blocking review 不能改报 interrupted 来重开审查。
- 同 round 更正后，旧报告不能推进或交付；原始 findings 文件仍保留。
- 已开始 review 的 stage 不再交出可写 fixer；旧 stage 和旧 writer 的操作入口被拒绝。

**修复二：将 fixer 和 finalizer 的验证交付绑定到运行事实**

目标：成功、代码失败和修复额度均有可校验来源；结构正确的报告不能自行证明验证通过。

复用 [run-verification.py](../skills/beadwork-run/scripts/run-verification.py) 的 started/result/log 采集、hash 校验与快照机制。当前采集器只接受 executor/implementer/fixer，需明确扩展 finalizer 的验证权限：允许当前 stage 0 采集 final/gate；修复阶段原则上由当前 fixer 运行。fixer 已停止后确需 finalizer 补充验证时，必须绑定当前 stage、候选 HEAD 和补充原因，不授予源码写入或 gate-fix 权限。

最终阶段验证采用以下规则：

- 成功记录要求命令正常退出 0、前后均为相同干净 HEAD、进程组已结束、dispatch/started/result/log 来源完整。测试是否零匹配、实际覆盖及外部资源收尾仍由 agent 核对。
- 不将缺少 result、记录器错误、现场变化或被中断的运行解释为正常成功或代码失败。未知结果保留，成功交付前需有实际收尾说明及有效后续验证。
- 当前交付必须包含全部所属运行，不能只选择成功记录；历史报告固定当时的来源快照，后续新增运行不使历史文件失效。相同 HEAD、相同 gate 取时间顺序上最新的有效结果，不能用较早成功掩盖较晚失败。
- 保留现有 verification 字段；命令、HEAD、退出事实和通过状态由组装器生成，人工字段仅填写语义说明及额外人工验证。人工条目不能替代必需 gate 的机器证据。
- `just final <boundary...>` 作为组合调用保存真实 argv。根据项目 final recipe 的已核实契约，将成功调用关联到 final 和明确传入的边界；不能从自由文本 command 猜覆盖，失败调用也不能臆造各子 gate 的成功。已有独立 gate 记录按各自来源验收。

为 fixer 增加 `fixer-assemble`、`fixer-check` 和 `fixer-accept`：分别生成报告/快照、校验完整运行与 Git 来源、由 finalizer 保存明确选择。沿用现有 `verify-worker.py` 的结构校验，完整验收入口补足它未承担的事实检查。最终阶段与 controller accept 都必须重验来源，不能存在绕开完整检查的成功路径。

fixer `BLOCKED / code_failure` 只在本逻辑 stage 的三次 gate-fix 已用尽，且第三次候选有正常非零交付结果时成立；必须匹配候选 HEAD 和原始失败记录。开发 red、环境失败、记录器错误和中断均不满足该条件。stage 0 无 fixer，不检查三次修复额度，但推进 stage 1 仍需实际 final/gate 失败或完整代码类 blocking review。

合法的部分 BLOCKED 报告应能交付。来源缺失或损坏时保留问题指针并按证据阻塞处理，不能要求伪造完整快照，也不能据此推进代码修复阶段。接收阻塞报告与授予接替 writer 权限分开；未确认旧任务停止时只能保存现场与停止记录。

主要落点：run-verification.py、finalization.py、gate_repair.py、[verify-worker.py](../skills/beadwork-run/scripts/verify-worker.py)、[verify-phase.py](../skills/beadwork-run/scripts/verify-phase.py) 及对应 CLI 路由。共用运行事实读取函数可以小范围提取，保留 implementer 现有可观察行为和报告字段。

验收用例：

- 缺日志、hash 错误、旧 HEAD、dirty 运行、未结束进程组不能支撑成功交付。
- 无修复记录、只用一次修复或没有第三次失败候选时，fixer code_failure 被拒绝；三次均有真实记录时可进入下一 stage。
- stage 0 的真实代码失败可以推进；环境或证据阻塞不能消耗阶段。
- 同 HEAD 较晚失败不能被较早成功覆盖；未知运行不能无说明消失。
- final 的组合参数能形成对应覆盖；漏参数、未核实覆盖或手填 passed 不能补齐缺失 gate。
- 更换 fixer 会话保留额度和运行历史；历史快照在新增运行后仍可验收。

**修复三：让补充 boundary gates 成为后续交付的累计下限**

目标：已确认的补充验证义务随阶段和接替者继承，不能只保留来源文字而丢失执行要求。

保留 root 的 required_boundary_gates 作为原始下限；在阶段检查点保存累计下限。它由 root 下限、已验收阶段/修复报告中的 boundary_gates，以及本轮明确确认的新边界取并集得到。gate_sources 保存新增原因与来源。补充边界一旦确认即持久化，即使对应报告 BLOCKED 或随后中断，也不得因换 stage 丢失。

`final-stage` 将累计下限写入下一 fixer dispatch；`fixer-accept`、`final-assemble` 和 controller accept 检查覆盖。最后交付 HEAD 必须满足累计下限，不复用旧 HEAD 上的通过记录。沿用项目 final 覆盖 gate-unit/gate-full 的既有去重约定，累计义务和实际执行覆盖分别记录，避免重复执行。

同一 attempt 不自动删除已确认 gate。若原 gate 声明确实错误，保留证据并交上层核实契约；本次不增加通用 gate 撤销流程。main 变化形成新 attempt 时继续交接尚适用的已确认边界，不能仅因为 attempt ID 改变而清空。

主要落点：finalization.py 的阶段准备、fixer 选择及报告验收；controller 的最终输入/验收；相关 schemas。

验收用例：

- stage 0 新增 gate-extra，stage 1 fixer 必须继承；省略它时最终交付失败。
- fixer 新增边界后中断或进入下一阶段，边界继续保留。
- 最终报告保留 gate_sources 但省略对应 gate/当前 HEAD 结果时拒绝。
- 重复 gate 去重；final 的既有通用覆盖不引入重复运行。

**修复四：持久化各角色的必要输入与上下文补充**

目标：独立上下文的接收者可以从 dispatch 及其引用建立必要上下文；派发消息不再是关键证据的唯一载体。

保留现有字段，增加必要的来源绑定并提高准备入口的校验。文件来源沿用 path/sha256；Beads 使用完整 ID，并保留本次读取快照的来源指针。hash 证明读取了哪个版本，不代表冻结 Beads；后续刷新发现实质冲突时显式阻塞或交接补充事实。

| 交接 | 固化内容 | 生成/核对责任 |
| --- | --- | --- |
| preflight → controller → executor | 验收过的 preflight 报告、当前 ticket 计划来源、有效 linked spec、显式 gate 下限、BASE smoke 来源 | controller prepare 从来源中提取并核对，agent 判断语义 |
| executor → implementer | 当前执行计划/适配来源、规则/spec 指针、必要 gates、已有提交及前序失败来源 | ticket-stage/适配入口生成 |
| executor/finalizer → reviewers | 已验收 writer 报告及验证来源、适配证据、本轮范围、最终审查的固定 children、本轴前次报告与处置 | review-prepare 从检查点生成 |
| finalizer → fixer | 已选失败报告/collection、有效 stage BASE、累计 gate 下限、已完成修复与未解决 finding 来源 | final-stage 从检查点生成 |
| 任一协调者接替 | 原 root/attempt、当前检查点及新增事实文件 | 原直接派发者明确交接 |

输入必填规则：required_boundary_gates 必须显式存在，允许 []；linked_spec 必须有有效来源，parent 即 spec 时明确指向 parent。无前序实现或前次 review 时使用明确的 null/空数组，不靠缺字段猜测。按当前角色与阶段判断必需来源，合法部分阻塞不要求不存在的成功证据。

上下文补充写新的事实文件并在检查点追加绑定，不覆盖原 dispatch、不生成新 BASE、不重置额度。继续原 agent 与接替 agent 使用同一来源；未获授权的 acceptance/seam 变化不能伪装为事实补充。reviewer 只接收本轴前次审查，避免通过输入引入跨轴结论依赖。

主要落点：[controller.py](../skills/beadwork-run/scripts/controller.py)、[preflight-operations.py](../skills/beadwork-run/scripts/preflight-operations.py)、[ticket_execution.py](../skills/beadwork-run/scripts/ticket_execution.py)、finalization.py、executor-operations.py。

验收用例：缺必要来源在派发前失败；显式空 gate 集合合法；parent 即 spec 合法；错误 ticket/HEAD 的报告指针及损坏 hash 被拒绝；跨 cwd 读取所有路径有效；上下文补充在恢复中保留且不改变阶段/额度；两轴 dispatch 不携带对方前次 findings。

**修复五：增加 final-deliver 并记录派发者的收尾确认**

拟新增入口：

```sh
python3 <skill-dir>/scripts/executor-operations.py final-deliver \
  --dispatch <root-dispatch.json> --output <root-report.json>
```

只读取检查点明确选中的已验收 stage report。执行完整来源、现场和选择校验后，原字节复制到 root 目录，生成 root receipt，并按 root dispatch 重新验收。stdout 只输出短回执，成功与合法 BLOCKED 均可交付；不重跑 gates、不重开 review、不增加 stage。

目标文件使用新名称。复制或回执生成中断后保留已写文件，恢复时核对原选择与 hash，复用完全一致的已完成步骤或写新文件，不覆盖旧证据。controller accept 继续独立执行完整检查。迁移角色指令，取消正常流程手工复制/改 receipt 的要求。

在 [report-delivery.md](../skills/beadwork-run/references/report-delivery.md) 统一收尾记录：直接派发者记录宿主 task ID、确认状态、观察时间和证据说明，必要时附命令/外部资源的未解决事项。记录写入新的验收附件并绑定所验收来源，不写回子 agent 报告。保留 stopped_tasks 字段；子 agent 自述和派发者观察有冲突时停止推进。

收尾记录只保存实际观察，不调用不存在的宿主探测 API，不按旧 PID 自动 kill，不将消息静默、取消请求已发送或 receipt 到达视作停止。未知/仍运行时可保存阻塞交付，但不能重派 writer、合入或清理。脚本只检查记录与状态选择一致，直接派发者仍承担真实性责任。

主要落点：finalization.py、executor-operations.py、controller 验收入口及共享交付协议。

验收用例：只交付当前 selected_stage；更正后的旧报告、其他 attempt 报告和变化的 HEAD 被拒绝；root 与 stage 报告字节/hash 一致；中断重试无覆盖、无新增额度；交付 BLOCKED 保留恢复入口；未确认停止的记录不能授权后续写入或集成。

**实施顺序与交付拆分**

| 顺序 | 交付范围 | 依赖与完成条件 |
| --- | --- | --- |
| 1 | finalizer 检查点、唯一 review、明确选择和冻结规则 | 先将重复 review 负例转成回归；保证恢复与更正仍可完成 |
| 2 | fixer 完整验收、stage 0 采集、验证快照及 code_failure 额度绑定 | 基于步骤 1 记录已验收 fixer/验证选择；封闭无证据成功和提前推进 |
| 3 | 累计 gate 下限及各阶段继承 | 使用步骤 2 的真实运行覆盖；遗漏补充边界必须失败 |
| 4 | 必要 dispatch 输入、reviewer 证据与恢复事实补充 | 从前述检查点自动生成来源，减少人工转填 |
| 5 | final-deliver、收尾确认与协议文档收敛 | 依赖稳定的选择/验收入口；完成 controller 全链路负例 |

每步同时更新相关脚本测试和对应角色/参考文档，避免中间交付出现“文档已要求、CLI 尚不支持”。不创建真实 Beads tickets，不改变消费项目配置。正式修改 skill 源码前，先解析本地安装真实路径；本方案文档不改变当前 skill 执行。

**历史证据与协议过渡**

历史报告、回执、dispatch 和日志不改写。现有 legacy 读取能力保持，用明确的协议版本区分新增的严格交付路径，不通过缺少新字段自动退回宽松验收。

新派发使用新契约。已有 attempt 恢复时，从明确提供的旧 dispatch/report/receipt 导入可证明的选择、额度与边界，追加新检查点并保留原来源；不能按修改时间挑选“最新报告”。无法证明唯一 review、验证来源或额度时交付具体 BLOCKED，保留现场，不静默重置尝试或伪造成功。已经完成的历史记录仍可审阅，不要求批量迁移。

过渡只服务当前已有格式，不新增面向未知未来版本的适配框架。实施时将旧格式回归与新增负例一并运行，确保严格验收没有破坏合法部分阻塞、无提交完成和已有行为审查。

**验证与完成标准**

新增测试通过真实脚本入口观察可见行为，使用临时 Git/worktree 和受控命令 fixture。验证采集测试应实际生成 started/result/log，不以手填 passed 作为成功依据；专门测试伪造/损坏报告时才使用手工负例。优先扩展现有 test_finalization、test_ticket_execution、test_run_verification、test_gate_repair、test_verify_worker、test_verify_phase、test_executor_operations 和 test_controller，不复制实现内部逻辑作为 oracle。

三项已复现缺陷先形成能在当前实现暴露问题的回归，再实施修复。输入完善和交付脚本按对应的成功、失败及中断恢复行为测试。覆盖原始报告保留、同 HEAD 更正、来源缺失、跨 cwd、状态恢复、额度不重置及合法 BLOCKED；不为纯文字修改新增行为测试。

跨脚本协议完成后，从仓库根运行完整套件：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_*.py'
```

测试创建临时 Git 仓库/worktree，按本仓库规则取得所需执行权限。完成 skill validator、相对资源引用、agents/openai.yaml 策略、安装真实路径和 git diff --check 检查。架构文档只更新必要概览；具体协议保留在 skills/beadwork-run/references/ 及角色入口。

完成标准为：三个负例均被确定性拒绝；合法 ticket 与最终验收可完成；中断、同 HEAD 更正和已有行为审查不增加额度、不丢失证据；controller 不能通过其他验收入口绕过新约束；报告与文档说明一致。

交付时分别报告脚本回归、CLI 临时 fixture 和真实 Codex 嵌套派发的验证情况。完整单元测试通过不代表宿主收尾确认或真实嵌套派发已经验证；真实 agent 批次若未执行，明确记录该边界。

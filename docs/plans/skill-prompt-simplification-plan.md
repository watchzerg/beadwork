# Beadwork 提示词精简与协议对齐计划

日期：2026-09-16。

状态：提示词精简已实施并同步到安装源码；P06 自动初始化替代仍保留为未完成项。实施与验证详情见 [验收记录](../acceptance/skill-prompt-simplification-acceptance.md)。本文下述内容保留原计划目标与完成标准；未修改生产脚本或消费项目，未启动真实 ticket graph。

## 1. 目标与分析基线

目标是减少 agent 在执行时需要记忆、选择和手工搬运的协议细节，同时保留影响正确性、权限和恢复行为的必要约束。优先修正脚本重构后留下的旧操作指令，再消除同一上下文中的重复说明。

本轮静态 review 覆盖 `beadwork-run` 的 220 行入口、6 份角色指令、全部 references，以及相关脚本、README、项目契约和架构说明。用户级 `/Users/watchzerg/.agents/skills/beadwork-run` 当前为指向本仓库 `skills/beadwork-run` 的 symlink。实施前须重新核对，不能把本文记录视为永久有效的运行状态。

已确认的主要事实：

- 当前 v2 finalizer 组装器可从检查点自动取得已选 review/fixer 来源，但执行说明仍要求手工提供完整来源数组。
- 正常 prepare/stage 入口已生成 dispatch、报告路径和 schema，共用交付协议仍描述手工准备这些文件。
- controller 同时保留脚本入口和完整手工操作路线；初始化脚本与主文档的 worktree 创建方式存在差异，尚不能断言可以直接替换。
- 模型组合、阶段推进、gate-fix 和恢复约束在同一角色会读取的多份文件中重复。
- 部分角色同时读取职责说明、操作协议和恢复协议，正常路径也会加载当前不适用的细节。

这些是静态发现，不是精简后成功率或 token 收益的实测结果。原有 [脚本化计划](script-automation-refactoring-plan.md) 与 [验收记录](../acceptance/script-automation-refactoring-acceptance.md) 保留，不重写其历史状态；本计划以实施时源码为准核对残留。

## 2. 范围与不可削弱的约束

主要修改 `skills/beadwork-run/SKILL.md`、`agents/*.md` 和 `references/*.md`。README、架构与接入文档仅在链接、职责描述或说明归属受影响时同步。脚本修改限于第 P06 项确认的正常入口对齐缺口及必要回归；不得借机进行通用框架重构。

必须保持：

1. controller 独占 Beads 写入、Git/worktree 生命周期和最终集成；executor/finalizer 只写证据，源码由当前唯一 writer 修改。
2. 独立角色仍能从自己的入口获得权限、输入来源、交付方式和停止规则，不依赖继承派发者上下文。
3. 保留 ticket/stage/gate-fix 三层循环、既有模型策略与额度；恢复不重置 BASE、轮次或修复机会。
4. 宿主任务与外部资源的真实停止由派发者观察；回执、静默和进程组退出不能替代该判断。
5. 保留固定 BASE/HEAD、append-only、明确来源选择、原始 findings 与更正历史；不改写历史报告。
6. 保留双轴 review、完整范围审查、`COMPLETED` 与 PASS 的区别，以及 writer DONE 与整票完成的区别。
7. 保留 seam 授权、行为 red、实际测试收集、真实边界覆盖和 BASE 已满足时的正常适配；不制造 red 或空提交。
8. 脚本负责事实与状态绑定，agent 负责需求、覆盖、失败根因、处置和授权语义。脚本通过不代替语义验收。
9. 保持 branch/worktree 布局、既有协议字段、Python 运行约束和 explicit-only invocation policy。
10. 不删除历史设计文档来追求表面行数下降，不运行真实消费项目、不创建 tickets、不 commit、push 或合入 main，除非后续任务另有授权。

## 3. 目标结构与精简原则

采用现有文件内的职责收敛与准确路由，不再建立一层通用协议或大量微型参考文件。

| 文档类别 | 负责的内容 | 应移出或压缩的内容 |
| --- | --- | --- |
| `SKILL.md` | controller 正常流程、权限、交接、终态、异常路由 | 子角色内部完整状态机、机器字段搬运、重复命令细节 |
| 角色指令 | 本角色权限、语义判断、执行顺序、按需阅读入口 | 脚本生成字段清单、其他角色操作、通用编码教程 |
| execution/operations 参考 | 命令、必要人工输入、返回值、失败和恢复入口 | 已在同一上下文读到的完整职责说明、重复模型表 |
| `report-delivery.md` | 报告与回执、更正、来源绑定、真实收尾 | 正常 prepare 已完成的手工准备、所有角色底层命令目录 |
| recovery 参考 | 恢复分支、异常状态和历史格式要求 | 正常开工不需要预读的解释 |
| 共享测试契约 | seam、计划、red 与 gate 选择的权威规则 | 从角色文件复制回来的同义规则 |
| README/维护文档 | 来源致谢、安装、维护和性能分析说明 | 执行时需要遵守但仅在维护文档出现的规则 |

每一项删减都记录理由：脚本已生成、同一上下文重复、仅恢复时适用、通用常识或维护背景。跨独立角色的必要约束不按文本重复率删除。必要的命令用法和人工输入含义继续保留，不能为了缩短提示而迫使 agent 阅读实现源码。

## 4. 工作项与实施顺序

| ID | 工作项 | 主要依赖 | 改动类型 |
| --- | --- | --- | --- |
| P00 | 固定基线与角色加载清单 | 无 | 只读盘点 |
| P01 | finalizer 正常交付使用检查点选择 | P00 | 文档为主，核对现有行为 |
| P02 | 共用交付协议使用 prepare 产物 | P00 | 文档 |
| P03 | 模型与阶段规则收敛 | P01、P02 | 文档 |
| P04 | 按角色和触发条件加载参考 | P01–P03 | 文档与引用 |
| P05 | writer 提交、测试与报告说明去重 | P02、P04 | 文档 |
| P06 | controller 正常脚本入口对齐 | P00；最终合并在 P03 后 | 条件性脚本修复与文档 |
| P07 | 清理维护背景与低价值提醒 | P04、P05 | 文档 |
| P08 | 验收、加载负担对比与交付 | P01–P07 | 验证与记录 |

P06 的差异核对可以提前进行；不得因它尚未完成而阻止其他纯文档工作。若发现需要改变业务契约的差异，保留该部分现行规则并明确标为未完成，不把候选脚本入口提前写成默认成功路径。

### P00：固定实施基线与加载路径

实施前记录 Git HEAD、已有 diff、安装真实路径及 invocation policy。

按 controller、preflight、executor、implementer、reviewer、finalizer、fixer 列出入口与必读/条件读取文件。覆盖普通成功、TDD、direct verification、BASE 已满足、代码修复、中断恢复和 legacy 恢复。当前上下文已读且未变化的文件计一次，独立角色分别计算。

形成精简前的文件行数/字节数与加载清单，后续复用同一口径。无需新增通用依赖图分析工具。

完成标准：每个拟删除段落能回答“谁会读、何时读、权威来源在哪里、删除后如何找到必要信息”。

### P01：移除 finalizer 的过期来源搬运

修改 [最终执行协议](../../skills/beadwork-run/references/final-execution.md)、[finalizer](../../skills/beadwork-run/agents/finalizer.md) 和 [review 协议](../../skills/beadwork-run/references/review.md)。依据 [finalization.py](../../skills/beadwork-run/scripts/finalization.py) 与 CLI 核对当前 v2 和 legacy 的差别。

1. v2 正常 `final-assemble` 示例仅提供 dispatch、draft、output；明确已选 review/fixer 来源由检查点生成。
2. 删除正常路径手工拼接 `review_rounds`、`collection.pair`、完整 fixer binding 数组的要求。
3. 将仍有效的显式来源参数标为兼容/特殊核对用法，按实际需要放入恢复说明；不删除脚本的显式参数一致性检查。
4. 修正 finalizer 恢复时必须手工传 previous report/receipt 的笼统表述，以当前严格检查点的实际恢复入口为准。
5. 保留 draft 中需要 agent 判断的字段、review 更正使阶段选择失效的语义，以及 root 必须通过 final-deliver 交付的要求。

完成标准：正常 v2 路径无需手工搬运已绑定来源；缺选择、错误来源、HEAD 变化仍被拒绝。不得将此结论直接推广到尚未核实的 ticket/legacy 路径。

### P02：统一报告交付的正常入口

修改 [交付契约](../../skills/beadwork-run/references/report-delivery.md) 及直接调用它的角色文件。

1. 将“派发者手工建目录、生成 schema、写 dispatch”替换为使用对应 prepare/stage/review-prepare 返回的产物。
2. 保留绝对路径、固定身份、读取 schema、原样短回执和独立验收的要求。
3. 正常交付优先引用各角色的 assemble/check/accept；底层 `--schema`、`--check-report` 用法只在确有需要的部分报告/故障路径提供。
4. 先检查部分 BLOCKED 报告的调用者，再移动底层命令。优先放入已有 recovery 参考；确实无法清晰归属时最多增加一份聚焦的交付故障参考，并提供明确触发条件。
5. handoff-close 与 context-add 保留可执行说明；角色只引用共用规则，不重复完整字段和失败分类。

完成标准：每个角色正常交付只有一条清楚的路线；无有效 dispatch、schema 不可读、自检失败与合法 BLOCKED 均有可达的处理入口。

### P03：收敛模型与阶段说明

依据 [workflow_policy.py](../../skills/beadwork-run/scripts/workflow_policy.py) 核对模型与额度。

1. 删除 finalizer、review、controller-operations 中重复的逐阶段模型表，执行时使用生成 dispatch 的 model/reasoning_effort。
2. controller 直接选择的 preflight/finalizer 模型保留一个明确配置位置，不误删没有脚本生成来源的选择规则。
3. `SKILL.md` 保留子角色职责、等待方式、终态和恢复入口；删除 finalizer/implementer 内部 gate-fix 的长篇推演。
4. 角色文件保留决定“继续、repair、blocked、interrupted”的简短规则；细节按对应 execution/verification 参考定位。
5. “不另设无进展计数”等历史对照表述收敛成当前额度和终止规则，确保不引入额外自动尝试。

完成标准：修改模型配置时不再需要同步多张运行时模型表；controller 不需要复述子角色完整状态机才能正常等待和验收。

### P04：减少不适用的参考加载

1. finalizer 首次执行不默认读取 recovery-finalizer；实际恢复或历史格式识别时读取。
2. fixer 仅加载其输入、验证、交付和恢复来源相关部分，不要求了解 finalizer root 交付与阶段管理的全部命令。
3. implementer 只读取 ticket-execution 的自身交付部分；executor 读取其负责的 stage、验收和 root 交付规则。
4. reviewer 按本轴职责和本轮证据触发测试契约读取，保留来源不可读时 BLOCKED 的规则，不以“已有 finding”作为读取必要契约的前提。
5. 检查所有角色在独立上下文下都能定位 skill、项目规则、spec 和 schema；迁移段落后同步引用和章节指针。
6. 不为节省一次阅读创造多层跳转。每个需要执行的动作应能从角色入口直接或经一份明确参考找到用法。

完成标准：正常路径不加载完整 legacy 恢复说明；独立角色仍能完成权限判断、正常交付与异常上报。

### P05：精简 writer 指令

修改 [implementer](../../skills/beadwork-run/agents/implementer.md)、[fixer](../../skills/beadwork-run/agents/fixer.md)、[executor operations](../../skills/beadwork-run/references/executor-operations.md) 及相关交付段落。

1. 将 fmt、diff、验证、暂存、check-layer、commit 的机械顺序保留在一个操作参考中；implementer 保留分层原则、范围判断、进度和阻塞条件。
2. 只在必要位置说明 `.beads`/无关改动不得提交、commit 身份要求及验证后改动须重跑，避免重复完整提交清单。
3. TDD/direct verification 的必填字段与 seam/red 规则以共享契约为准；角色保留模式选择、BASE 适配及何时交回上层。
4. fixer draft 只列人工填写字段；明确 HEAD、身份、commit 列表、工作区状态与运行快照由脚本生成，消除“先要求填写再禁止手填”的歧义。
5. 保留根因修复、相关调用方与正常恢复能力核查；压缩通用编辑操作提醒。

完成标准：writer 不需要在多份说明中重建提交顺序，不被要求填写机器生成字段；实际验证与权限约束不减少。

### P06：统一 controller 正常入口

本项先核对行为，再修改默认路线。主要涉及 [SKILL.md](../../skills/beadwork-run/SKILL.md)、[controller operations](../../skills/beadwork-run/references/controller-operations.md)、[batch_initialize.py](../../skills/beadwork-run/scripts/batch_initialize.py)、[tracker_operations.py](../../skills/beadwork-run/scripts/tracker_operations.py) 和 [batch_evidence.py](../../skills/beadwork-run/scripts/batch_evidence.py)。

逐项核对：

| 环节 | 必须证明的等价性或前置条件 |
| --- | --- |
| worktree 创建 | 固定 branch/path、正确 primary、共享 Beads workspace、已有 branch/worktree 的恢复行为 |
| 基线准备 | update-main 返回的固定 SHA、安装输入、env-facts、smoke 范围及失败保留 |
| parent 初始化 | claim 身份、批次 comment、未知写入结果协调，完成前不能开始 child |
| child 开工 | sync_result、原子 claim、start comment、root dispatch 和 BASE 的顺序与绑定 |
| comment/close | 正确目标、成功前置来源、写后读回、重复执行、实际 comment ID 的后续使用 |
| 最终交接 | 固定 children、完整累计 gates/commits/smells、manifest 来源和语义补充 |
| merge/cleanup | 继续使用现有受审 SHA 与 checkpoint 条件，不改变集成权限 |

处理规则：

1. 已等价：正常文档直接使用现有脚本入口，删除重复手工过程。
2. 存在局部缺口：先补足该入口及必要行为回归，再替换文档。根据实际 tracker/worktree 契约核对命令；源码中缺少检查不等于已证实真实环境必然失败。
3. 需要扩大协议、变更授权或缺少可验证条件：完成不受影响的部分，保留该环节现有路线并列出具体差异，不能宣称本项全部完成。
4. 每个初始化、claim、comment、close 的正常动作仅提供一个默认入口；手工路线仅在确实支持的恢复条件下出现。
5. 文档给出最小必要输入和返回值，避免只提到脚本名字而让 controller 临时读源码猜参数。

完成标准：正常流程没有含糊的“脚本或手工任选”；所选路线覆盖原有 Beads workspace、基线、写入与恢复义务。无需为统一入口改写历史证据。

### P07：处理维护背景与低价值说明

1. preflight 的 timing 指标解释移至适用的性能/维护文档；执行角色仅保留确实需要的输出提示。
2. reviewer 的方法来源与迁移说明归入 README 致谢，运行时不加载迁移背景。
3. Standards 的 12 项 smell baseline 保留名称与判断范围；可压缩常识性修复建议，不改变 blocking 分类，不鼓励为凑列表重构。
4. 清理含糊的“新版/旧版”措辞；真正影响恢复行为时使用准确的版本条件。
5. 保留历史计划和验收记录，不把它们加入正常 skill 的必读链。

完成标准：维护背景不再挤占正常执行指令；review 方法与验收范围保持一致。

## 5. 验证计划

### 5.1 文档与行为验证分开

按 [测试计划契约](../../skills/beadwork-run/references/testing-plan.md)，纯文档精简采用 direct verification：核对命令、链接、角色加载和协议保持，不为文字改动制造 TDD red，也不写只匹配措辞或标题的测试。

如果 P06 修改可观察行为，使用现有临时 Git/worktree 与受控 bd/just fixtures，先建立有意义的失败或差异场景，再实现和验证。新 seam 或授权变化不由本计划自动批准；不把消费项目 just recipes 强加给本仓库。

### 5.2 必须覆盖的场景

| 场景 | 验收重点 | 验证方式 |
| --- | --- | --- |
| 新批次、普通 ticket | 单一入口、输入完整、正确 claim/start 次序 | 文档走查；P06 行为改动用 CLI fixture |
| TDD / direct verification | 契约可达、行为 red 与收集范围保持 | 角色路径走查，复用已有回归 |
| BASE 已满足 | 正常适配、无提交审查、不制造 red | 适配路径走查及已有相关回归 |
| v2 finalizer 正常组装 | 省略手工来源数组仍使用明确检查点选择 | 核对并运行相关 finalization 回归 |
| 显式错误来源 | 来源不一致仍拒绝，不从目录时间挑选 | 复用或补充必要行为回归 |
| 代码失败与中断 | 分类不混淆、额度不重置、阶段推进不改变 | stage/gate-fix 路径走查及相关回归 |
| review 缺轴、半成品、更正 | 复用原 round、重新组装、保留原件 | 恢复路径走查及已有回归 |
| writer 停止未知 | 不派接替、不合入、不清理 | 收尾契约走查及已有 handoff 回归 |
| 部分 BLOCKED / 缺 dispatch | 底层自检入口仍可找到，不伪造成功 | 故障路由检查 |
| legacy 恢复 | 保留条件和原证据，不偷换为 v2 成功 | 恢复说明与实际兼容分支对照 |
| tracker 响应丢失与竞争 | 正确读回、不重复 comment、不误关闭 | P06 相关 fixture 回归 |

已有测试足够时直接复用；只为新发现且与本项相关的行为缺口补测试。测试通过后不无理由重复完整套件。

### 5.3 检查命令与权限

仅文档改动从仓库根运行：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B skills/beadwork-run/scripts/maintenance_check.py docs
git diff --check
```

修改 skill 时运行可用的 `skill-creator/scripts/quick_validate.py`，核对相对引用、`agents/openai.yaml` 和安装真实路径。验证器和依赖以当前环境为准；不可用时明确列为未验证，不自动宣称通过。

定向脚本回归示例：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_finalization.py'
```

P06 按实际改动选择 `test_batch_operations.py`、`test_tracker_operations.py`、`test_controller.py`、`test_main_sync.py` 及关联测试。跨脚本协议或目录迁移运行完整套件：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_*.py'
```

测试创建临时 Git/worktrees 时按仓库规则申请对应窄范围执行权限。文档检查不启动真实 graph。真实 Beads 兼容和 Codex 嵌套派发若未运行，交付中分别注明，不能用脚本回归替代。

## 6. 加载负担与效果评估

比较 P00 与完成后的相同角色、相同场景：

- 必读文件与条件文件的数量、行数和字节数；同一上下文按实际读取范围去重。
- 正常操作中需要 agent 手工拼接的机器事实、来源数组和 schema 准备步骤。
- 同一状态、模型和提交步骤在单个上下文中的重复定义数量。
- 角色完成工作所需的引用跳转，以及是否出现必须读脚本源码才能执行的缺口。

优先报告确定的结构收益，不设必须下降某个百分比的行数/token 指标。若没有实际 tokenizer 和宿主日志，只报告行数/字节数，不把它们换算成实测 token 或成功率。将加载范围变窄与实际宿主是否按范围读取分开记录。

如后续开展真实行为对比，应固定任务、输入证据和运行条件，记录误路由、无谓读取、错误字段和恢复行为；这属于另行明确范围的验证，不是本次文档交付的前置条件。

## 7. 实施批次与交付标准

| 批次 | 内容 | 完成门槛 |
| --- | --- | --- |
| A | P00、P01、P02 | 基线清楚；过期交付指令修正；故障交付入口仍可达 |
| B | P03、P04、P05、P07 | 各角色加载路线与权威来源明确；必要约束完整；validator/文档检查通过 |
| C | P06 | 入口差异逐项核对；必要脚本修复有回归；未解决差异明确保留 |
| D | P08 | 场景走查、适用回归、加载对比和未验证边界完整记录 |

每批保留可审阅的 diff。出现错误时只修正本次引入的改动，不 reset 用户工作或覆盖执行证据。若实现中修改了文件布局，同批修正所有引用；不留下指向尚未创建文件的运行指令。

最终交付记录应包含：完成的 P 编号、删减/迁移的规则及权威来源、实际源码变更、适用测试与 validator 结果、按角色的加载对比、未完成事项，以及真实 Beads/宿主是否验证。可以在本计划中追加简洁结果，若证据较多再建立独立验收文档，不预先创建空文件。

整个计划完成须满足：

1. 正常 v2 finalizer 不再人工组装脚本已选择的来源；正常派发不手工重建 prepare 产物。
2. controller 正常操作路线明确；没有在等价性未证明时删除必要检查。
3. 角色与参考各有职责，条件加载可达，独立上下文信息充分。
4. 模型策略、阶段额度、权限、测试契约、review 与收尾约束保持。
5. 所有必要人工输入有说明，机器生成字段不要求手填，旧格式处理范围清楚。
6. 链接、命名、diff、skill validator 及风险相称的回归通过；跳过和失败如实列出。
7. 精简收益有同口径对比，不宣称未经实测的效率或成功率提升。

## 8. 当前计划文档的验收

初次计划交付只检查范围、工作项依赖、源码链接和 Markdown/diff 质量。后续实施状态与实际验证范围以验收记录为准；文档检查与脚本回归不代表真实宿主行为已验证。

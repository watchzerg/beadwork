# Beadwork 脚本职责拆分验收记录

对应[实施方案](../plans/script-modularization-plan.md)。本记录随步骤更新，未验证的步骤不标记完成。

## 执行基线

- 开始日期：2026-09-16；最终验收日期：2026-09-17；HEAD：`06f9190660a3e2dee433221574d8a9ba84f813cf`。
- Python：3.14.7；安装真实路径为本仓库 `skills/beadwork-run`。
- 开始时仅方案文档为未跟踪文件，无生产源码改动。
- 基线源码、CLI/schema 快照与逐批日志保存在本机临时目录 `/tmp/beadwork-modularization/`，不包含消费项目数据，不作为可长期依赖的仓库制品。
- 已采集 8 个 argparse 入口的完整 parser 树（含循环注册子命令）、6 个角色共 12 份报告/receipt schema；graph 和手工解析的 verifier 参数另按源码及公开 CLI 测试核对。

## 步骤状态

| 步骤 | 状态 | 检查结果 |
| --- | --- | --- |
| A0 基线 | 完成 | 264 项通过，413.530 秒；8 个 parser、12 份 schema 与两组原实现交付样本已固定 |
| A1 schema 清理 | 完成 | 删除 149 行旧实现；43 项通过，5.173 秒；CLI/schema 完全一致 |
| A2 基础能力 | 完成 | 修正后 264 项通过，410.630 秒；旧/当前样本重验通过且 hash 不变 |
| A3 review 来源 | 完成 | 修正后 54 项通过，110.622 秒；只读来源和交接组装分离 |
| A4 状态与验证读取 | 完成 | 修正后 264 项通过，471.627 秒；循环组缩至 4 个模块 |
| A5 ticket 拆分 | 完成 | 264 项通过，443.541 秒；ticket 脱离循环组，旧证据 hash 保持 |
| A6 finalization 拆分 | 完成 | 264 项通过，453.025 秒；静态 import 图无循环 |
| A7 入口收敛 | 完成 | 修正测试 seam 后 101 项通过，310.738 秒；4 组旧来源重验通过 |
| A8 局部 fixture | 完成 | 52 项通过，35.521 秒；两个 helper 迁入 fixture_support |
| A9 最终验收 | 完成 | 267 项通过，571.991 秒；编译、链接、diff、validator 全部通过 |

## 验证边界

本轮不执行真实消费项目 ticket graph、真实 Beads 写入或真实 Codex 嵌套派发。CLI/临时 Git 与进程 fixture 不替代这些环境的验证。

## A1 检查

正式 schema 导入提前到 RECEIPT/EXPECTED_PLAN 初始化之前；旧函数正文删除，verify_ticket 的兼容导出保留。8 个 parser 树和 12 份 schema 与基线逐对象一致。三个 verifier 与 evidence 共 43 项通过。

## A2 过程检查

首次完整回归期间，源码审查发现 finalization 的局部 evidence 路径变量遮蔽新 evidence 模块；主动停止该次验证，保留 A2-tests.log。已改名为 evidence_root，同时将 review 的 acceptance 来源变量命名为 acceptance_source，避免后续迁移发生同类遮蔽；修正后重新运行完整回归。旧只读 Git verifier 和特殊文件名的 NUL 处理未合并改写。

A2 修正后的完整回归为 264 项通过，410.630 秒。原实现生成的 legacy/current ticket 来源均经当前 controller.inspect 接受；所有保存的 JSON hash 保持不变。

## A3 过程检查

review_evidence 已接收双轴来源与 collection 只读重验；review_inputs 迁至 review_operations，handoff 保留 context/closure。首次定向测试暴露迁移后未限定的 contexts 名称，已修正为 handoff.contexts 并重跑。补充一次性 symtable 检查，当前生产模块无未定义全局引用。循环依赖尚处于分批迁移中，只有 A9 图检查通过后才声明整体解除。

## A4 结构检查

新增 ticket_state、ticket_verification；final_state 接收 fixer 准入。gate_repair/run_verification 已直接依赖状态模块，final_verification 的 attempt 身份来自 dispatch_contract。包含延迟和字面量动态 import 的图中，循环组从基线 10 个模块收敛到 controller/executor_operations/finalization/ticket_execution 四个，留待 A5–A7 消除。8 个 parser 树和 12 份 schema 保持一致，symtable 未发现未定义全局引用。

A4 首次回归在第 5 项发现 controller.comment 的补证循环变量 evidence 遮蔽了直接证据模块引用，已改为 evidence_path 并从头重跑。失败日志 A4-tests.log 保留；未通过时没有推进状态标记。

## A5 结构检查

implementer 的结构与事实验收迁入 implementer_reports，schema 构造不再接收整个 validator 模块参数；verify-worker 显式调用其接口。ticket_reports 负责候选组装与完整报告检查，ticket_execution 仍在自检成功后按原顺序发布 receipt 和选择 checkpoint。controller 的旧阶段准备/计划适配委托 ticket_execution。名称、模块属性、8 个 parser、12 份 schema 和两组旧来源重验均通过；完整回归 264 项通过，443.541 秒。

## A6 结构检查与细化

新增 fixer_reports；finalization 分出 resume_stage_sources、initial_stage_sources、publish_fixer、check_stage_history、check_review_history。prepare_stage 从 152 行降至 73 行，保留 legacy 分支、发布顺序和既有字段。额外发现 final-deliver 会回调 controller.inspect：完整最终验收已收归 finalization.inspect_delivery，controller 复用该入口，目录/schema/receipt/来源、Git 和结束时 hash 检查均保留。此调整是落实原依赖目标，没有削减自检。当前静态 import 图已无循环；CLI/schema 与名称/模块属性检查通过；完整回归 264 项通过，453.025 秒。

## A7 检查

review_operations 接管准备、发布与收集；executor_operations 只保留 CLI 路由、现场检查和向下的兼容别名。preflight 使用同文件 FactsCollector 管理单次采集，将 tracker 输入、仓库/图检查、恢复现场、工具链和待审 ticket 输入分成具名步骤，保留查询顺序与错误记录。清理范围限定在本轮修改的文件，删除重复 import、旧转发正文和残留动态入口查询；公开 CLI 参数/schema 对照仍一致。

用 A0 保存的原源码额外生成 legacy/current finalizer 样本，与原先两组 ticket 样本共 4 组均由当前 controller.inspect 接受；保存的 JSON hash 全部不变。静态依赖图无循环，名称/模块属性与 diff 空白检查通过。

A7 首次定向回归发现两处测试仍通过已移除的 controller.executor_ops 动态查找 review 入口，导致在故障注入前退出。已将测试 seam 移到 review_operations，并增加指定中断异常的断言，确保实际覆盖 round 发布中断及原预留 round 恢复。失败日志 A7-tests.log 保留；修正后重跑两条恢复路径及相关入口套件。

## A8 检查

prepare_utility_stage 与 closure_source 迁入 fixture_support；前者直接引用职责归属模块，test_controller 保留导入供原调用方使用。两个 helper 均不拥有 setUp/tearDown 或临时目录生命周期，既有 TestCase 复用与资源清理维持原样。controller、baseline adaptation 两个套件共 52 项通过，35.521 秒。未进行全量 fixture 框架整理。

## A9 结构与兼容核对

- 8 个 argparse parser 树、6 个角色的 12 份报告/receipt schema 与 A0 解析后逐对象一致。
- legacy/current ticket、legacy/current finalizer 共 4 组原实现生成的证据由新实现重验通过，保存的全部 JSON hash 不变。
- 包含函数内 import 和字面量 __import__ 的生产依赖图没有循环；symtable 未定义名称和模块属性检查没有发现遗漏。
- 安装真实路径仍为仓库 skills/beadwork-run，agents/openai.yaml 仍为 allow_implicit_invocation: false；未修改模型政策和 SKILL.md。
- 新增 test_module_boundaries 的 3 项检查：依赖方向与循环、schema 构造不执行命令/扫描 checkpoint、三个 verifier 从 symlink 安装及无关 cwd 正常工作。最终完整维护结果另记下文。

### 文件规模

统计包含注释和空行。生产文件由 29 个、5,690 行变为 38 个、5,814 行；测试由 18 个、4,416 行变为 19 个、4,457 行，另有 fixture_support 63 行。总行数小幅增加来自模块导入、职责说明和具名步骤，不能视为性能改进。

| 文件 | 实施前行数 | 实施后行数 | 主要变化 |
| --- | ---: | ---: | --- |
| controller.py | 628 | 349 | 基础事实、阶段准备与报告校验下沉 |
| executor_operations.py | 470 | 222 | 保留 CLI 路由和局部现场操作 |
| ticket_execution.py | 640 | 388 | 状态、报告、验证读取拆出；接收原 controller 的 legacy 准备 |
| finalization.py | 578 | 549 | fixer 报告拆出，阶段准备拆为具名步骤；接收完整最终交付验收 |
| verify_ticket.py | 564 | 417 | 删除被正式导入覆盖的旧实现 |
| preflight-operations.py | 276 | 315 | collect 从 174 行降为 26 行；采集职责分组，文件总行数增加 |

finalization 仍是最大生产文件（549 行），但最长函数 prepare_stage 从 152 行降至 73 行；本次保留相邻最终验收编排与明确 legacy 分支，没有为了行数继续拆包。ticket 的 prepare_legacy_stage 为 81 行，保留原协议准备步骤。

| 新模块 | 行数 | 归属 |
| --- | ---: | --- |
| repository.py | 94 | Git/仓库事实 |
| dispatch_contract.py | 63 | 身份、路径与计划 |
| report_io.py | 63 | 固定 verifier 调用及来源读取 |
| review_evidence.py | 70 | 双轴原始来源只读重验 |
| ticket_state.py | 147 | ticket checkpoint 与来源选择 |
| ticket_verification.py | 105 | ticket 验证快照和读取 |
| implementer_reports.py | 148 | implementer schema、报告与事实 |
| ticket_reports.py | 212 | stage/ticket 报告组装与重验 |
| fixer_reports.py | 83 | fixer 报告组装与重验 |

### 调用边界核对

verify-worker 的 implementer 检查调用 implementer_errors/check_implementation，不回调 report_io.implementer；schema 路径只构造结构。report_io 的固定 verifier 子进程边与静态 import 边分别核对。ticket 的 stage 报告自检成功后才写 receipt/checkpoint；final-deliver 继续重验选中 stage、复制原报告并生成 root receipt。双轴原始来源、closure、HEAD/gate 和进程结束检查没有绕过。

### 保留的边界

- fixture 只迁移两个共享函数；既有 TestCase 复用未整体改造。
- legacy 协议分支继续保留，不进行证据迁移。
- finalization 和 verifier CLI 仍有可继续局部整理的代码，但本轮不新增包层级、registry 或通用回调。
- 计时仅记录实际回归，不宣称运行性能提升。

最终 full 检查设置 PYTHONPYCACHEPREFIX 到临时目录，以免 py_compile 在源码树创建缓存。其与 -B 组合令标准库冷启动重复编译；现场对照三次启动中位数约 0.025 秒与 0.116 秒，检查期间子进程仍持续更新。随后仅在该临时缓存中预热标准库，同一启动检查约 0.024 秒；没有修改源码、用例或跳过验证。该次总耗时包含此环境开销，不用于改造前后的性能比较。

## A9 最终结果

2026-09-17 完成以下完整维护检查：

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPYCACHEPREFIX=/tmp/beadwork-modularization/final-pycache \
python3 -B skills/beadwork-run/scripts/maintenance_check.py full \
  --output /tmp/beadwork-modularization/A9-maintenance.json
```

| 检查 | 结果 |
| --- | --- |
| local-links | 通过，无失效本地链接 |
| diff-check | 通过 |
| py-compile | 通过 |
| unittest | 267 项通过，571.991 秒；维护入口测得子进程 572.146 秒 |
| skill-validator | exit_code=0，Skill is valid!；未跳过 |
| CLI/schema 基线对照 | 8 个 parser、12 份 schema 一致 |
| 历史来源兼容 | 4 组通过，原始 JSON hash 全部不变 |
| 静态依赖与名称检查 | 无循环、无未定义全局名称/缺失模块属性 |
| 新增文件空白检查 | 通过，覆盖 git diff 尚不包含的未跟踪文件 |
| 安装/策略 | symlink 仍指向源码；allow_implicit_invocation: false 未改变 |

A0–A9 全部完成，A8 按触发条件局部实施。完整回归后只更新本文和方案完成标记，另跑 docs 检查；没有再次重复全套测试。未执行真实消费项目 graph、真实 Beads backend 写入或真实 Codex 嵌套派发；验收时尚未提交或 push；后续按用户指令提交。

提交前的 staged diff 检查发现 fixture_support 文件末尾多一个空行，已删除并再次检查；此修改不影响代码行为。

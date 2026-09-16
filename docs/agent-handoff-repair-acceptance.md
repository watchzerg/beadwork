**Agent 交接契约修复验收记录**

对应 [修复方案](agent-handoff-repair-plan.md)。日期：2026-09-16。五项修复已实施并完成验收，以下按方案顺序记录结果。

| 顺序 | 实施结果 | 验收证据 |
| --- | --- | --- |
| 1：唯一 review 与明确选择 | v2 finalizer 使用 append-only attempt 检查点，固定 round、fixer、review 和 stage report；恢复沿用原 stage | 重开 review、遗漏已选 blocking collection 均拒绝；collect 后中断保留选择；准备半成品复用原目录；同 round 更正使旧报告失效且保留原件 |
| 2：真实验证与修复额度 | stage 0/fixer 采集真实 started/result/log；fixer-assemble/check/accept 绑定来源；成功覆盖最终 HEAD | 无 gate、较晚失败、日志缺失不能通过 review；三次 fixer 修复与第三次失败候选是推进依据；stage 1 不能借 stage 0 的旧失败推进；日志损坏能交付部分 BLOCKED |
| 3：累计边界 | final-gates、fixer 验收与阶段检查点累计 gates，下一 writer 继承，最终覆盖校验不丢失下限 | gate-extra 跨阶段保留；只保留来源文字或缺当前 HEAD 的成功运行无法通过；stage 2 writer 与累计边界经独立 CLI 场景复核 |
| 4：持久输入与恢复事实 | 新票要求已验收 preflight 来源和显式 spec/gates；review dispatch 包含 writer/验证/阶段/本轴前次审查；context-add 保存补充事实链 | 缺必要输入及被改写的准入来源拒绝；单票原有适配与恢复测试继续执行；上下文恢复不换 stage；来源改写被拒绝；review 两轴各自读取对应历史来源 |
| 5：交付及收尾 | final-deliver 原字节交付已选报告；handoff-close 保存直接派发者观察；成功与阶段推进验收要求对应 closure | root 与 stage 字节一致；旧选择不能交付；缺收尾记录不能 controller accept；正常和 BLOCKED 均有 root 交付路径 |

针对前三项缺陷，实施前新增的三个回归均在原实现上失败；修复后通过。测试使用公开 CLI、临时 Git/worktree 及真实启动的受控 just fixture，生成 started/result/log，不将手填 passed 作为 v2 成功来源。旧格式回归显式保留 v1 fixture，避免将历史宽松格式当作新协议成功证据。

**独立验收及追加修复**

按 skill-creator 的 independent forward-testing 指引，独立 agent 在隔离临时 fixture 中复核最终阶段、缺收尾来源、日志缺失及同 HEAD 更正。补充场景验证 stage 0 失败、stage 1 fixer DONE 后收到 blocking review，再进入 stage 2 时能返回新的 writer，并保留 gate-extra。

该检查发现：已验收 fixer 的日志随后损坏时，finalizer 原本只能退出校验，无法交付部分 BLOCKED。现已修复为保留原 fixer 报告及绑定，在新的阶段报告 verification_issues 中记录损坏来源和原因；这种报告只能 blocked/interrupted，不能伪装成功或推进代码修复。已新增对应回归。

**验证结果**

- 定向同步/准入及交接回归：40 项通过。
- 最终完整脚本回归：237 项通过，耗时 375.486 秒；命令为 `PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_*.py'`。
- 本轮完整回归日志：`/private/tmp/beadwork-handoff-acceptance.log`（本机临时证据，不纳入仓库）。
- skill validator：通过，使用临时 uv/PyYAML 环境，没有修改项目依赖。
- Python 语法、改动文档中的 28 个本地相对链接和 git diff --check：通过，包含新增方案与验收文档。
- 用户级安装真实路径为本仓库 skills/beadwork-run；agents/openai.yaml 的 allow_implicit_invocation: false 保持不变。

历史报告不改写；v2 新派发不会因为缺少新增字段退回宽松验收。历史运行缺少严格检查点或实测来源时，保留原件并给出阻塞，不自动重置修复额度或把历史声明当作验证通过。

本次未运行真实消费项目的 ticket graph，也未验证真实 Codex 多层 writer/reviewer 的完整派发生命周期。独立 agent 执行的是临时 CLI 场景测试，不能替代真实 graph 的宿主收尾验证。未提交、合入或推送 Git；用户原有 AGENTS.md 改动保留。

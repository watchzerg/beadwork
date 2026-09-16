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

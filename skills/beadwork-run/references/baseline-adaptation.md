# 开工基线与执行计划适配

executor 在建立上下文或首个测试发现 Expected red 已不成立时读取本文件。正常 TDD 不新增报告步骤。以当前 ticket 的完整 acceptance 判断剩余工作，单个测试通过不证明整票完成。

| BASE 事实 | 执行 |
| --- | --- |
| 行为缺失 | 正常 TDD，取得行为 red。 |
| 部分已有、部分缺失 | 整票保持 TDD；已有部分引用证据，对剩余行为取得 red。 |
| 行为全部已有但缺少覆盖 | direct_verification；在 approved seam 内补测试，可正常提交。 |
| 全部要求和已有覆盖均足够 | direct_verification；运行 gates 和已有行为 review，无提交完成。 |

自动适配只改变验证方式，不改变 acceptance、产品决策、approved seam 或 gate 覆盖。生产接线和真实错误形态必须在验证范围内。需求冲突、新 seam、外部验收条件仍按原阻塞规则处理。

## 同一 implementer 继续

implementer 在当前阶段 review 前向 executor 提交计划建议：JSON 含 mode、reason、acceptance（criterion/evidence）、verification（command/result）和 boundary_gates。证据说明行为在开工 BASE 已满足，不能把本票刚实现的 green 当作基线事实。补测试后验证时如实区分新增测试和生产行为。

executor 语义核对后执行：

```bash
python3 <skill-dir>/scripts/executor-operations.py ticket-adapt-plan --dispatch <当前stage-dispatch.json> --input <已核准建议.json>
```

入口追加计划调整、expected-plan 和新 stage/implementer 上下文，保留原 BASE、stage、stage_base、models、approved seams、gate_repair_root、review 历史和全部已有验证来源；把新上下文选择写入 root 检查点。同一 implementer 改用返回的 implementer dispatch 继续，executor 改用返回的 stage dispatch。不重派 writer，不消耗阶段/修复机会，不覆盖原计划。

controller 不同步审批和写适配 comment；最终 completion/停止记录引用报告与 root 检查点即可。恢复通过原 root 选择明确的实际计划，不从目录时间推断。需求、产品范围或 seam 授权变化仍返回上层处理。

## 完成与 review

组装器为新契约 DONE 派生 `delivery_kind`：有真实提交为 `changed`，无提交为 `already_satisfied`。补测试/文档的真实提交也属于 changed；空提交不能作为交付。already_satisfied 要求 direct_verification、BASE=HEAD、commit 列表为空、现场干净、全部 acceptance 的当前验证及双轴 PASS。

无提交 review 通过 `review-prepare --evidence <acceptance.json>` 准备；文件为 criterion/evidence 非空数组，包含可读取的实现与验证来源。两轴收到 `review_kind: existing_behavior` 和 hash 绑定的证据文件：核实本票已有实现与全部验收要求，不对空 diff 自动 PASS，也不扩展为全仓库历史审查。普通 changed review 沿用 change 范围。

review 推翻“已满足”并发现本票代码缺陷时，按 code_failure 进入下一阶段。下一阶段需要行为改动时，executor 按同一适配入口恢复 TDD（保留既有 seam），取得真实 red；当前已授权阶段上限不变。同 HEAD 的报告更正仍不算新 review。

DONE 后沿用 completion、close 和 frontier；comment 说明基线已满足、本票无新增提交。最终 main=HEAD 时仍做完整 gates 与 parent 范围的 existing_behavior review，再记录已在 main、关闭和清理；不创建空提交。

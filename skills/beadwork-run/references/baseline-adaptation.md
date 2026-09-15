# 开工基线与执行计划适配

executor 在建立上下文或首个测试发现 Expected red 已不成立时读取本文件。正常 TDD 不新增报告步骤。以当前 ticket 的完整 acceptance 判断剩余工作，单个测试通过不证明整票完成。

| BASE 事实 | 执行 |
| --- | --- |
| 行为缺失 | 正常 TDD，取得行为 red。 |
| 部分已有、部分缺失 | 整票保持 TDD；已有部分引用证据，对剩余行为取得 red。 |
| 行为全部已有但缺少覆盖 | direct_verification；在 approved seam 内补测试，可正常提交。 |
| 全部要求和已有覆盖均足够 | direct_verification；运行 gates 和已有行为 review，无提交完成。 |

自动适配只改变验证方式，不改变 acceptance、产品决策、approved seam 或 gate 覆盖。生产接线和真实错误形态必须在验证范围内。需求冲突、新 seam、外部验收条件仍按原阻塞规则处理。

## 同一 executor 继续

executor 在当前阶段 review 前向 controller 提交计划建议：JSON 含 `mode`（TDD/direct_verification）、`reason`、`acceptance`（criterion/evidence 数组）、`verification`（command/result 数组）和 `boundary_gates`（保留声明及实测边界）。证据必须说明目标行为在开工 BASE 已满足，不能把本票刚实现的 green 当作基线事实。测试尚未存在时可添加测试后验证，但如实区分测试补充与生产行为变更。

controller 语义核对后执行：

```bash
python3 <skill-dir>/scripts/controller.py adapt-plan --dispatch <原dispatch.json> --input <已核准建议.json>
```

该命令只写证据：产生新目录的计划调整记录、expected-plan、schema 和 dispatch，保留原 BASE、stage、models、prior_reviews及全部既有验证来源。同一 executor 等 controller 记录完毕后改用返回的 dispatch；无需 BLOCKED、重派 writer 或消耗阶段。controller 独占调用和 Beads 写入，将新 dispatch 与 plan_adjustment 路径/hash 写入本票中文 comment，再通知原 executor 继续。原 Test plan、dispatch 和报告不覆盖。

从明确选中的最新执行上下文恢复，`prepare executor` 沿用调整后的 mode/seams 与 gate 下限。使用原 stage 和 BASE，不从新目录推断新阶段。源码仍按本票范围检查；适配前的正确工作不重做。新增或补正语义证据留在原始来源，不凭目录时间猜选记录。

## 完成与 review

组装器为新契约 DONE 派生 `delivery_kind`：有真实提交为 `changed`，无提交为 `already_satisfied`。补测试/文档的真实提交也属于 changed；空提交不能作为交付。already_satisfied 要求 direct_verification、BASE=HEAD、commit 列表为空、现场干净、全部 acceptance 的当前验证及双轴 PASS。

无提交 review 通过 `review-prepare --evidence <acceptance.json>` 准备；文件为 criterion/evidence 非空数组，包含可读取的实现与验证来源。两轴收到 `review_kind: existing_behavior` 和 hash 绑定的证据文件：核实本票已有实现与全部验收要求，不对空 diff 自动 PASS，也不扩展为全仓库历史审查。普通 changed review 沿用 change 范围。

review 推翻“已满足”并发现本票代码缺陷时，按 code_failure 进入下一阶段。下一阶段需要行为改动时，controller 按同一适配入口恢复 TDD（保留既有 seam），取得真实 red；四阶段上限不变。同 HEAD 的报告更正仍不算新 review。

DONE 后沿用 completion、close 和 frontier；comment 说明基线已满足、本票无新增提交。最终 main=HEAD 时仍做完整 gates 与 parent 范围的 existing_behavior review，再记录已在 main、关闭和清理；不创建空提交。

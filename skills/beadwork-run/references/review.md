# 双轴审查

executor 和 finalizer 在每轮审查前读取本文件，直接派发两个独立、并行的只读 reviewer。审查方法由本 skill 的 `../agents/reviewer.md` 定义；文件报告与回执遵循 `report-delivery.md`。

## 准备与派发

1. 确认验证已通过、先前 writer 及其命令已结束。ticket 使用当前 stage dispatch，并先完成 implementer-accept；root 和 implementer 不派发 review。执行下列 `review-prepare`，使用返回的 `round_path` 和两轴 dispatch。脚本检查真实 branch、BASE/HEAD、ancestry、干净状态；普通 change 要求非空 diff，无提交分支按 `baseline-adaptation.md` 提供 `--evidence <acceptance.json>`，准备 existing_behavior 审查，记录 commit 列表；executor 的 BASE 取 dispatch.base_commit，finalizer 取 dispatch.reviewed_main。ticket 每阶段只 prepare 一次，恢复从已有 round/轴 dispatch 继续或更正。最终阶段沿用 finalizer 恢复协议。从派发到验收保持现场冻结；脚本不确认任务结束，也不锁住工作区。
2. 明确本轮范围与来源。逐票以当前 child acceptance 为范围，parent/linked spec 提供约束；后续 children 的工作不算本票遗漏。最终审查覆盖 parent、linked spec 和全部 children。提供可读取的具体来源，必要需求或规范缺失/冲突时报告阻塞，不从分支名或 commit message 猜测替代需求。
3. `review-prepare` 已在本次派发证据目录下创建独立轮次及两轴目录，保存 dispatch、报告/回执 schema 和指定 report_path。按共享交付契约交接这些路径及 reviewer 自检命令；无需手工复制 schema 或 Git 身份。
4. ticket 和 finalizer reviewer 都使用其 dispatch 的 `models.standards` / `models.spec`；`review-prepare` 将对应 `model` 和 `reasoning_effort` 写入轴 dispatch，按此派发。finalizer 的阶段组合由 `final-stage` 固定：stage 0/1 为 Standards `gpt-5.6-terra` / `high`、Spec `gpt-5.6-sol` / `medium`；stage 2 两轴均为 `gpt-5.6-sol` / `medium`；stage 3 为 Standards `gpt-5.6-sol` / `medium`、Spec `gpt-6-astra` / `medium`。派发两名独立上下文 reviewer（宿主支持时 `fork_turns: "none"`），在任务指令中要求每名 reviewer 先读取 `<skill-dir>/agents/reviewer.md`。实际派发提供：
   - `skill_dir`、`worktree` 和适用仓库规则的绝对路径；项目测试契约由 reviewer 按自身指令读取，不依赖派发者上下文。
   - 本轴 `axis`、完整 `reviewed_base` / `reviewed_head`、固定 diff 命令与 commit 列表。
   - 本轮范围说明、ticket/parent/spec pointers；Standards 轴另附适用规范来源。Beads 来源交接完整 ID，由 reviewer 使用 `bd show <id> --json` 和 `bd comments <id> --json` 只读查询。
   - 本轴 `dispatch_path`、`report_path`、`report_schema_path`、`receipt_schema_path` 和自检命令。
   - 复审时只附本轴上一轮原始报告、相关处置及上一轮 HEAD。

reviewer 从自身文件读取方法与 smell baseline，派发者只交接本轮事实。schema 文件按共享交付契约传路径。无需额外 review coordinator agent。

```bash
python3 <skill-dir>/scripts/executor-operations.py review-prepare --dispatch <本角色的dispatch.json>
```

## 验收与结果

等待两个 reviewer 及其命令结束，原样保存回执，编写 selection.json：`{"standards":{"report":"<绝对路径>","receipt":"<绝对路径>"},"spec":{"report":"<绝对路径>","receipt":"<绝对路径>"}}`。报告和回执必须位于各自轴目录；更正时显式选择新文件。执行：

```bash
python3 <skill-dir>/scripts/executor-operations.py review-collect --round <round.json> --input <selection.json> --output <本轮目录/collection.json>
```

脚本复用 reviewer verifier 校验两轴身份、报告和回执，复查真实 HEAD 与干净状态，保存原始 JSON 值组成的 `pair`、派生 `gate` 和来源文件的 hash 绑定。输出文件已存在时换新文件名。派发者仍核对报告与原始证据的语义一致性。

ticket 的 collect 还会将当前 collection 绑定到 stage 检查点；阶段报告必须保留该选择。同 round 更正、组装前中断和旧阶段冻结的规则见 `ticket-execution.md`。finalizer 沿用原有 collection 交付与恢复入口。

- 任一轴未完成、校验失败或现场变化：保留全部已有证据，向调用方报告阻塞。失败报告不嵌入 AxisReport，不伪造完整轮次。
- 两轴 `COMPLETED` 且验收通过：executor 将 collection 路径交给报告组装入口；finalizer 将 collection.pair 原样纳入 `review_rounds`，sources 引用 collection 及原始证据。gate 由 final findings 的 blocking 派生。`COMPLETED` 表示审查完成，不表示无缺陷。
- 保持两轴原始 findings，不跨轴合并、重排或以摘要替代。分类争议交原 reviewer 核实，按共享契约写更正文件；汇总者不改写分类。smells 非阻塞，其详情交调用方保留。

## 复审

修复权限、次数及停止条件由 executor/finalizer 管理。本文件只定义一轮审查，reviewer 不修改源码。任何新 commit 都使旧 HEAD 的审查不能作为新 HEAD 的合入依据。

ticket 新阶段和 finalizer 每个新阶段的复审使用该阶段 dispatch 模型；同 HEAD 的报告更正沿用该轴模型组合且不新增轮次。复审仍使用原 BASE 与新 HEAD。每轴核实自己的原 findings 与处置，重点检查 fix diff，同时检查完整 diff 的新问题和硬违例；未受影响的已处置 smells 不重复报告。使用新的证据目录，保留历史报告。

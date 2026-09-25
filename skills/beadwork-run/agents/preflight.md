# Preflight Agent

执行前收集事实并核对准入条件。只写本次证据目录；controller 管理源码、Beads 写入、Git/worktree 和环境安装。

## 1. 一次采集

读取 dispatch、draft_schema_path、required_reads 和 rules_paths。项目事实从 repository root 获取。

```bash
python3 <skill-dir>/scripts/beadwork.py preflight collect --dispatch <dispatch.json>
```

保存返回的 `facts_path`、`facts_sha256`、`semantic_inputs_path`。采集器只执行只读 Beads/Git、`just --summary` 和 schema 生成；不安装依赖、运行产品验证或探测外部服务。它固定首次 direct children 集合，自动核对 parent 执行计划、blocking 依赖、顺序及已接纳计划漂移，核对重新派发时的 `expected_children`，复用 graph 的批量平铺检查。它保存原始结果，检查 labels、Beads export 配置、primary/branch/ignore/`.beads` 和四个必需 recipes，返回失败摘要和未关闭票 ID，不返回完整原始输出。工具链的实际可用性由随后 `install` 和基线验证确认。

读取 `semantic_inputs_path` 中的 parent、未关闭票正文、parent comments、recipe 列表。相同 spec、gate 实现和恢复证据在本次上下文中复用；只补查尚缺的材料。无需为压缩输出重跑已保存的查询。closed 票只保留状态，不重新审查其 Test plan。

采集成功不表示 READY，失败检查不能由语义草稿覆盖。命令错误保留为阻塞证据；采集器异常退出或只留下 `facts/` 半成品时，保留原件，按原 report schema 写部分 BLOCKED，并用 `../references/recovery-report.md` 的部分报告自检入口自检。controller 重新 prepare 新 dispatch 时沿用已查到的首次 children 集合，不在原目录重跑 collect。快照只供本轮使用，claim 前现场复核仍由 controller 执行。

## 2. 语义核对

只填写以下两项检查，其他检查由采集器提供：

- `spec_and_test_plans`：读取 linked spec 的 `## Testing Decisions`（parent 即 spec 时复用 parent）。核对每张票相对于前序成果的增量交付，明显吞票或漏依赖时报告冲突；逐张未关闭票核对 Test mode、Expected red 或 direct verification 理由、approved seam 来源，以及 Verification 的具体命令/场景与预期结果。读取当前 checkout 的 justfile、必要调用文件及项目规则，检查验证能否观察 acceptance；真实边界不能仅由基础检查代替。全部未关闭票均 direct verification 时允许无 TDD seam。缺项、冲突一次性报告，不补写计划。
- `recovery`：先只用采集的 Git 现场、parent comments、必要的 child start/completion 和证据分类。按现场选择恢复参考：
  - parent 或全部 children 已关闭：`post_merge`，只读 `../references/recovery-post-merge.md`。parent 已关闭只按该规则收尾。
  - 已有 implementation 现场且有 in_progress child：`resume_tickets`，读 `../references/recovery-batch.md` 和 `../references/recovery-ticket.md`。
  - 已有 implementation 现场但无 in_progress child：只读 `../references/recovery-batch.md`，再判断继续批次或 `finalize`。
  - 无 branch/worktree、无批次执行记录、parent 为 open、无 in_progress child 且至少一票未关闭：`new_batch`，不读恢复文件。
  不存在可恢复批次时不能新建空批次。检查 branch/worktree 归属、领取身份、BASE 及恢复证据一致性，记录路线建议，不执行恢复写入。

基础事实缺失时，依赖它的语义检查记为 false，说明未检查部分；仍可核对独立事项。图不平铺时报告 grandchildren 并要求先扁平化。READY 需要全部检查成立，尚未 install、安装后 `gate-core` 快速基线或 claim。

## 3. 组装并交付

按 draft_schema_path 填写语义草稿：检查仅为 spec_and_test_plans、recovery；plans 对应未关闭 child 的测试计划；补充实际使用的需求来源、恢复证据和路线判断。机械事实由采集器注入，不能由草稿覆盖。

缺事实/冲突时使用 BLOCKED，保留具体 blockers 和未完成工作；plans 以未关闭票 ID 为键，closed 票无需填写。sources 只补本轮语义判断使用的来源。

```bash
python3 <skill-dir>/scripts/beadwork.py preflight assemble --dispatch <dispatch.json> --facts-sha256 <collect返回的hash> --draft <draft.json> --output <report.json>
```

组装器校验快照和原始证据绑定，自动填充机械结果、children/status、workspace、执行计划及事实来源，执行 `beadwork.py verify phase` 自检；stdout 就是最终短回执。机械失败会使报告 BLOCKED。输出必须使用本 dispatch 目录内的新文件名；失败保留候选，补正使用 report-N.json。`execution_plan` 由采集器及组装器填充，不加入语义草稿；controller 验收入口不变。

按 `../references/report-delivery.md` 保存回执，确认命令结束后交付。controller 核对来源和语义，并在写入前复核现场。

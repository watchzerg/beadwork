# 恢复 ticket

恢复 `in_progress` ticket 时，从它的 start comment 读取 BASE。start comment 缺失时，仅在 worktree 干净且批次记录与已完成 tickets 的提交证据能证明当前 HEAD 是该票开工前的基线时补写；否则保留现场并停止。start comment 存在但不含可验证的 BASE SHA 时停止，不从 `HEAD~1` 猜测。核实 BASE 后执行 `prepare executor`（`mode: resume`），由脚本保存派发材料。

恢复输入必须指向前次 `previous_dispatch`；已有回执时提供 `previous_report` 与 `previous_receipt`，明确选中更正版本。代码失败使用 `continuation: repair`；未完成阶段使用 `resume`。读取 `controller-operations.md` 的旧报告导入规则；不要从新会话、commit 数或已完成 review 数直接重置/推断当前阶段。

有执行计划调整时，从 controller 的适配 comment 选中 dispatch/plan_adjustment，沿用实际 mode、seams 和 gate 下限；见 `baseline-adaptation.md`。

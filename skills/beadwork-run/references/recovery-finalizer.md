# finalizer 接替

新版 `prior_finalization` 指向最近阶段：`{stage_path: <stage dispatch.json 的绝对路径>}`。同一 `reviewed_main` 且没有 `new_attempt_reason` 时，重新运行是同一 attempt：沿用 `attempt_id`、原始 `start_head`、稳定 `stage_base`、已有 review/fixer/验证来源、commits 与允许的 dirty 现场。先确认旧 writer 和命令结束，再用 `final-stage` 的 `continuation: resume` 接续；有阶段 report 时同时提供其 report/receipt，明确选择更正版本。

前阶段 `outcome: code_failure` 才能以 `continuation: repair` 进入下一阶段。stage 3 仍失败时停止。报告更正没有新 HEAD 时不增加阶段或 review。不要以新会话、报告缺失、commit 数或“无进展”重新计算额度。

只有 `reviewed_main` 实际变化，或用户明确授权一次额外修复，才能带 `new_attempt_reason` 建立新的 attempt；新 attempt 从干净现场开始，旧证据继续保留。

旧格式仍接受 `{fix_used: boolean, review_rounds_used: 0..2, report_path: <旧报告绝对路径>}`。导入时必须同时提供旧 report/receipt、已完成的 collection 来源和（如有）fixer dispatch/report/receipt；旧文件不改写。旧 `fix_used: false/true` 分别对应新版 stage 0/1，代码失败进入后续阶段仍需给出可核实的代码失败依据。

若宿主在 fixer 已交付 report/receipt、但阶段报告尚未写出时中断，先在**旧 stage dispatch** 下用 `final-assemble` 补齐阶段报告：传入全部既有 review/fixer 来源和实际现场，fixer 已完成但尚待 review 时记 `BLOCKED / interrupted`；fixer 确认代码失败则记 `BLOCKED / code_failure`。保存 stdout 为该阶段 receipt，再用这对阶段 report/receipt 恢复。这样 DONE fixer 的提交和精确 HEAD 验证会被继承，脚本不再派同阶段 writer。旧 fixer 也没有可用报告时，先确认其已结束，再在同阶段接续 dirty/commit 现场；新的 fixer 报告须覆盖原阶段 BASE 起的全部提交。

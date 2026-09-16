# finalizer 接替

新派发采用 finalization_version: 2。prior_finalization 指向原阶段 dispatch；同一 reviewed_main 恢复原 attempt 和检查点，保留 BASE、stage、fixer/review 的明确选择、累计 gates、commits、dirty 现场及 gate-fix 额度。先确认旧任务结束，再调用 final-stage continuation: resume；返回原 stage、selected_fixer、review_round、selected_review、selected_stage 和 context_sources。

fixer DONE 已验收时，不重新派 writer；review 已开始时只继续原 round 的缺失轴或同 HEAD 更正。collect 已完成而阶段报告未写出时直接使用已选 collection 组装。collection 写出但检查点未完成时，用原 round 和明确 selection 重新 collect 到新文件。review 准备只有半成品时使用 review-prepare --resume，保留原目录。

只有检查点选中的 code_failure 阶段才能 repair 到下一阶段，stage 5 失败停止。更正 review 后旧阶段报告失效，重新组装再决定交付或推进；不因更换会话重新计算额度。

只有 reviewed_main 实际变化，或用户明确授权额外修复，才通过 new_attempt_reason 创建新 attempt，并要求干净现场。交接已确认的补充边界，旧证据保持原样。

历史 v1 及更早报告仍可按原格式读取，不批量改写或自动授予 v2 成功。缺少严格检查点、可证明的原 review 选择或运行来源时，新 prepare/恢复给出具体阻塞；保留原 dispatch/report/receipt、额度与现场，不静默重建阶段。不要执行历史文件中已经过时的命令来规避当前检查。

正常交付使用 final-deliver，不手工复制和改 receipt。具体入口见 final-execution.md；收尾和新增事实按 report-delivery.md。

v2 的 final-stage 从检查点恢复已选来源，无需手工传 previous_report/previous_receipt；repair 同样使用已选报告。兼容 v1 的 final-assemble 仍需 `--fixers <来源数组.json>` 及逐个 `--review <collection.json>`：fixers 为完整有序 dispatch/report/receipt bindings，review 包含 prior_reviews 和本轮来源。v2 若显式提供这些参数，必须与检查点完全一致；正常调用省略，不能用兼容参数绕过当前选择。

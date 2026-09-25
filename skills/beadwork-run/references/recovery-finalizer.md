# finalizer 接替

新派发采用 `workflow_contract_version: 8`。prior_finalization 指向原阶段 dispatch；同一 reviewed_main 恢复原 attempt 和检查点，保留 BASE、stage、document-syncer/fixer/review 的明确选择、commits、dirty 现场及 gate-fix 额度。先确认旧任务结束，再调用 final-stage continuation: resume；返回原 stage、document_dispatch、selected_document、selected_fixer、review_round、selected_review、selected_stage 和 context_sources。

document-syncer 或 fixer DONE 已验收时，不重新派 writer；review 已开始时只继续原 round 的缺失轴或同 HEAD 更正。collect 已完成而阶段报告未写出时直接使用已选 collection 组装。collection 写出但检查点未完成时，用原 round 和明确 selection 重新 collect 到新文件。review 准备只有半成品时使用 review-prepare --resume，保留原目录。

stage 0 文档同步中断保留原 dispatch、BASE、已有提交和 dirty 现场；确认旧任务停止后恢复同一个 writer。writer 自报或派发者收尾观察任一未确认停止时，返回的 document_dispatch 为空；确认旧任务结束后，可在相同 HEAD 用 document-assemble/accept 追加更正的收尾报告，再恢复写入；不覆盖旧报告。同步已验收时只继续完整 gate/review，后续修复阶段不重新派同步器。新 reviewed_main 导致新 attempt 时重新检查文档影响。

finalizer 自己的验证中断或结果未知时，确认旧任务及外部资源结束，将 verification_notes 写入本阶段新的 BLOCKED 恢复报告并组装选中，再重跑必要 gates。检查点保留该报告的绑定来源，review 准入及后续组装自动继承收尾说明；缺说明或来源变化仍阻塞，不删除旧运行记录。

只有检查点选中的 code_failure 阶段才能 repair 到下一阶段，stage 5 失败停止。更正 review 后旧阶段报告失效，重新组装再决定交付或推进；不因更换会话重新计算额度。

只有 reviewed_main 实际变化，或用户明确授权额外修复，才通过 new_attempt_reason 创建新 attempt，并要求干净现场。交接验收范围、未解决的问题和验证证据，旧证据保持原样。

正常交付使用 final-deliver，不手工复制和改 receipt。具体入口见 final-execution.md；收尾和新增事实按 report-delivery.md。

final-stage 从 checkpoint 恢复已选来源；组装不接受显式 review/fixer 参数。历史格式仅可按 recovery-report.md 诊断，不导入当前执行流程。

# 文档同步规则

本规则由 document-syncer、fixer、executor、finalizer 和两轴 reviewers 共用。目标项目已有的文档入口、目录职责和维护约定决定内容落点；本 skill 不规定目录结构。

## 范围与依据

- document-syncer 在最终 stage 0 检查整个批次：linked spec、parent/children acceptance、已接受的变更说明、ticket 证据，以及最终同步后的实际代码。diff 帮助定位影响，不能替代需求和调用链核对。
- review 后 `document_mode: review_closeout` 只修复派发的文档 findings 及直接关联内容，遵循 [文档收尾](document-closeout.md)；不重新梳理整个文档库。
- fixer 处理当前 failures/findings，并同步修复直接影响的文档；不因每次修复而重新梳理整个文档库。finalizer 和最终 reviewers 核对批次整体仍然一致。
- 必要影响包括使用方式、接口/CLI、配置、运行与故障处理、架构职责、领域概念，以及因本批变更失效的示例、链接和入口。只修改本批变更及其直接影响的内容，不顺带清理无关历史问题。
- spec 定义预期行为，代码与验证证据说明实际行为。两者冲突须作为实现缺陷或需求歧义交回 finalizer，不能通过改写文档掩盖偏差，也不能把未验证能力写成已验收。
- 沿用项目对当前文档、历史 spec、计划、验收记录和生成文件的区分；不覆盖历史记录，不手改要求通过生成器维护的文件。

## 完成与验收

每批必须检查文档影响，但不强制产生修改。`updated` 表示已同步必要文档；`no_change_needed` 必须给出检查范围与具体依据，例如本批仅影响内部实现，或文档已在 tickets 中同步。检查未完成为 `incomplete`，不能用空结论代替。

同步器报告记录 inspected、summary 和结果，脚本绑定 BASE/HEAD、实际 commits、changed_files、验证来源和收尾证据。finalizer 核对改动是否属于文档、覆盖是否充分、是否越界；脚本不根据目录或扩展名推断文档语义。

最终 Standards 轴检查项目明确的文档维护规则；Spec 轴检查说明与批准需求、实际行为的一致性及必要遗漏。影响使用或验收的错误属于 blocking finding；不把纯措辞偏好升级成阻塞。已有两轴承担文档审查，不增加第三轴。

初始批次文档同步发生在最终 gate 和 review 之前。review 期间冻结候选；后续代码修复进入新 stage，重新完成对应 gate 和两轴审查。仅文档 findings 走一次限定收尾，原 review 不改写，原 gate 不重跑；由 executor/finalizer 的定点验收决定是否完成。同步器 DONE 本身不等于 ticket 或批次验收通过。

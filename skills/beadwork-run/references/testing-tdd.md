# TDD 执行与证据

调用 `tdd` 前，读取 `testing-seams.md` 确认已有授权及变更边界；人工直接调用且没有 assigned ticket 时保留上游交互确认。

Direct-verification ticket 不调用 `tdd`。判断模式或检查 ticket 计划时，读取 `testing-plan.md`。

## Red 证据

Ticket 的 `Expected red` 是出票时的预期；实际 BASE 是开工时记录的代码基线。开工基线已满足目标行为时，beadwork-run 按 `baseline-adaptation.md` 正常适配，不制造 red；部分已满足则对剩余行为继续 TDD。

在实现目标行为前运行新测试，报告具体命令、运行基线与断言失败原因。纯模块加载、编译或环境错误不算行为 red。

优先证明新测试在 BASE 上断言失败。若 BASE 尚不存在 approved public interface，允许先建立最小可加载骨架，再取得目标行为的断言失败；骨架只解决接口加载与调用，不实现目标行为。报告须区分原始 BASE 和加入骨架后的状态，记录骨架差异及复现方式，不将后者称为 BASE 上的 red。后续 vertical slices 基于当时已有实现记录各自运行基线。

选择实际测试命令或核对收集范围时，读取 `testing-gates.md`。

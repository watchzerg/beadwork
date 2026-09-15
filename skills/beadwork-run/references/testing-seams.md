# 测试 seam

## Spec 定义 seam

`to-spec` 在用户确认后，将少量稳定 seam 写入 `## Testing Decisions`。每个 seam 包含：

- 稳定 ID，例如 `S1`
- observable public interface
- 能观察和不能观察的行为
- 现有测试 prior art；没有时明确写“暂无”
- `Status: approved`

Spec 是 seam 定义的唯一来源。Ticket 引用 spec pointer 和 seam ID，不复制定义；parent 本身就是 spec 时可通过 parent 解析。

若整个 spec 都适用 direct verification，`Testing Decisions` 明确记录无需新增 TDD seam 及理由。

## 确认与变更边界

- 引用 spec 中 `approved` seam 的 TDD ticket 已获得用户确认；执行时不再询问同一 seam。Acceptance criteria 或现有测试本身不能证明 seam 已获批准。
- 在 approved interface 和观察范围内，可自行补充用例、fixture、输入组合，以及调整测试组织和辅助代码。
- 新增或替换观察接口、改测内部实现，或削弱已约定的观察能力时，暂停相关实现，说明原 seam、拟议变化及原因，取得用户确认后继续。

选择测试模式或编写、核对 Test plan 字段时，读取 `testing-plan.md`；执行或验收 TDD 时，读取 `testing-tdd.md`。仅需补充验证覆盖时，读取 `testing-gates.md`。

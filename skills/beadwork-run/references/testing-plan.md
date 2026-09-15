# 测试计划

## Ticket 声明 Test plan

`to-tickets` 发布 `ready-for-agent` ticket 前，必须在 quiz 中确认以下 `## Test plan` 之一。

TDD 用于需要通过新增测试证明的可观察行为变化：

```markdown
## Test plan

- **Mode:** TDD
- **Approved seams:** S1
- **Observable behavior:** <本 ticket 交付的行为>
- **Expected red:** <测试将揭示的缺失或错误行为；这是预期，不是实测证据>
- **Boundary gates:** <额外验证所需的 gate-* recipe；无则写 none>
```

Direct verification 用于无需新增 red → green 测试的改动或基线已满足的验证；允许为既有行为补充回归测试而不制造 red：

```markdown
## Test plan

- **Mode:** direct verification
- **Reason:** <为何无需新增 red → green 测试，例如行为不变且已有回归覆盖，或属于声明式改动>
- **Verification:** <具体 just 命令或运行场景及预期结果；复用回归覆盖时指出相关测试>
- **Boundary gates:** <额外验证所需的 gate-* recipe；无则写 none>
```

按可观察行为及已有覆盖选择模式，不按文件类型决定。纯重构、机械迁移可以复用已有 behavioral oracle；配置和 wiring 若改变权限、持久化或错误处理等行为，仍需相应行为测试。

两种模式都必须声明 `Boundary gates`（无则写 `none`），包括 Verification 引用的额外 gate。检查名称与覆盖有效性时，读取 `testing-gates.md`。

执行时基线已满足 Expected red 不属于计划结构错误：beadwork-run 按 `baseline-adaptation.md` 核准实际执行计划，保留原声明和 seam 授权。部分行为已有时，仅对剩余行为取得 red。

test mode 缺失或冲突、TDD 缺少 observable behavior / expected red 或 seam reference 无效、direct verification 缺少 reason / verification、`Boundary gates` 缺失或引用无效的 ticket，不得进入实现。此限制适用于 `ready-for-agent` 和无人值守执行；人工直接调用 `tdd` 且没有 assigned ticket 时保留交互确认。

解析或确认 approved seam 时，读取 `testing-seams.md`；执行或验收 TDD 实测 red 时，读取 `testing-tdd.md`。

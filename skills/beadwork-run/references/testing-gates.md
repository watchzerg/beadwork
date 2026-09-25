# 测试验证入口

Beadwork 只要求项目提供 `install`、`test [ARGS...]`、`gate-core` 和 `gate-full`。项目根 justfile 及其调用文件定义实际验证内容；读取当前 checkout 的项目规则、测试配置和相关测试，确认命令、收集范围、环境及覆盖能力，不从命令名称推断行为。

## 每票验证

- `install` 检查并准备开发环境。初始化后以 `gate-core` 建立快速基线；合入 main 改变 HEAD 后重新验证，安装输入变化才重新安装。
- implementer 按项目规则选择格式化及静态检查命令，修改范围限制为本次相关文件。
- 通过 `test [ARGS...]` 运行覆盖改动的最窄有效验证；参数由项目定义。需要完整相关 suite 时仍通过项目的 `test` 入口选择，不能以零匹配或占位命令作为通过。
- Test plan 的 Verification 说明命令或场景及预期结果。涉及数据库、浏览器、跨进程等真实行为时，必须用能观察该行为的证据完成本票验收；无法收窄就运行完整相关 suite。
- Direct verification 执行声明的检查或场景，不为制造 red 新增 tautological test。TDD 的行为 red 按 `testing-tdd.md` 核对。
- 本票提交后在同一干净候选 HEAD 上通过验证采集器运行带 `--delivery` 的无参数 `gate-core`。core 通过仅证明基础检查，executor/reviewer 仍须核对 acceptance 与 Test plan 的行为覆盖。
- 已知失败必须解释并解决；不能通过更换测试选择或进入下一 stage 隐去未解决的问题。失败、中断和成功运行都保留原始证据。

## 最终验证

parent finalize 在最终干净候选上执行一次无筛选 `gate-full`，覆盖项目完整验收。实际内部 suites、顺序和服务准备由项目维护，Beadwork 不维护边界名称或延期清单。

finalizer/reviewer 核对 parent 全部 acceptance、单票证据与完整验收范围；修改测试框架、筛选或 gate 定义时，必须审查是否遗漏必要覆盖。成功命令不自动证明未覆盖的线上、人工或真实凭据场景。

完整失败或修复改变候选后，从 `gate-full` 入口重新执行；不拼接分次运行的成功片段。同一有效候选的完整成功可以复用，但之后出现失败或无效验证须重新验收。

工具链、环境诊断和可选开发命令遵循项目 `AGENTS.md`。缺少环境时按具体失败停止并保存证据，不能用诊断输出替代验证结果。

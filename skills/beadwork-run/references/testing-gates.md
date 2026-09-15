# 测试 gates

## 声明与交接

`Boundary gates` 只列通用验证之外需要的 recipe；`gate-unit` 由工作流执行，无需重复列出。所列名称须以 `gate-` 为前缀、出现在 `just --summary` 中，并已实现相关验证；占位 recipe 不能作为有效引用。编写或检查字段格式时，读取 `testing-plan.md`。

仅补跑覆盖实际影响的 gate 不需要重新确认；将新增 gate、原因和实际结果写入验证报告，后续验证须收集声明及实测补充的边界。若同时改变需求或 approved seam，暂停相关实现并取得确认；判断 seam 变更范围时，读取 `testing-seams.md`。

Direct verification 执行 Test plan 声明的验证和工作流要求的通用 gates，记录实际命令或运行场景及结果；不为制造 red 而新增 tautological test。需要判断 TDD 失败是否构成有效 red 时，读取 `testing-tdd.md`。

## 测试 gate 选择

项目安装与验证只调用仓库根 `justfile` 的契约 recipe。Recipe 及其调用脚本是实际命令组成、测试收集范围和环境检查的事实来源；本文件提供选择规则。

- 已实现测试入口后，使用 `just test [ARGS...]` 按 recipe 支持的路径或筛选参数收窄；新增测试须确认被实际收集。
- 默认测试范围之外的真实边界，由已实现的 `gate-<boundary>` recipe 验证，并在 ticket 中声明。只有实际定义了对应 suite 才增加边界 gate。
- 每层和修复轮选择实际覆盖改动的最窄验证入口；recipe 不支持收窄时运行对应完整 gate。没有收集到相关测试不能作为通过的证据。
- 无需行为测试的改动执行 Test plan 中的直接验证，并运行工作流要求的通用 gates。

选择验证入口前，读取仓库根 `justfile`；涉及测试收集或边界覆盖时，再读取对应 recipe 调用的脚本、测试配置与相关测试。以实际实现确定参数、收集范围和覆盖边界，不从 recipe 名称推断能力；未实现或显式失败的占位 recipe 不可作为有效 gate。

环境事实通过 `just env-facts` 查询，是否可运行以实际 gate 结果为准。工具链遵循 `AGENTS.md`。

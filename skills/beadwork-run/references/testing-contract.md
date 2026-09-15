# 共享测试契约定位

本目录的测试契约供 `to-spec`、`to-tickets`、`tdd` 和本 skill 共用。规划与人工 TDD 阶段通过项目 `AGENTS.md` 的指引直接读取所需参考文件；读取共享规则不启动 ticket graph 流程。

本 skill 的各角色从 `<skill-dir>/references/` 定位 `testing-seams.md`、`testing-plan.md`、`testing-tdd.md` 和 `testing-gates.md`，均解析为绝对路径。`testing_seams_doc` 是该目录中 `testing-seams.md` 的绝对路径；其余共享文件在同目录定位。

项目特例由适用的 `AGENTS.md` 及其明确引用的文档提供。`rules_paths` 只交接适用仓库规则入口，不预先展开全部测试契约。读取项目事实时，preflight 和建 worktree 前的 controller 使用 repository root；implementation 阶段（含 controller 验收）的各角色使用当前 worktree。具体 seam 定义来自 linked spec；命令、测试收集范围和环境要求来自该 checkout 的 `justfile` 及其调用文件。

按任务读取 `testing-seams.md`（授权边界）、`testing-plan.md`（计划）、`testing-tdd.md`（red 证据）、`testing-gates.md`（验证覆盖）。各角色指令规定加载时机；已在当前上下文读取且未变化的文件无需重复加载。所需文件不可读取时，按当前阶段的缺事实/阻塞处理。

需要用户确认的 seam 变化，在本流程返回 `BLOCKED`；已有批准不重复询问。无效计划不进入实现。实测 BASE 由 controller 建立恢复点并交接，执行者按测试契约记录证据。

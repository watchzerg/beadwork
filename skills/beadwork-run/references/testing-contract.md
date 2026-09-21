# 共享测试契约定位

本目录的测试契约供 `to-spec`、`to-tickets`、`tdd` 和本 skill 共用。规划与人工 TDD 阶段通过项目 `AGENTS.md` 的指引直接读取所需参考文件；读取共享规则不启动 ticket graph 流程。

本 skill 的各角色从 `<skill-dir>/references/` 定位 `testing-seams.md`、`testing-plan.md`、`testing-tdd.md` 和 `testing-gates.md`，均解析为绝对路径。`testing_seams_doc` 是该目录中 `testing-seams.md` 的绝对路径；其余共享文件在同目录定位。

项目特例由适用的 `AGENTS.md` 及其明确引用的文档提供。`rules_paths` 只交接适用仓库规则入口，不预先展开全部测试契约。读取项目事实时，preflight 和建 worktree 前的 controller 使用 repository root；implementation 阶段（含 controller 验收）的各角色使用当前 worktree。具体 seam 定义来自 linked spec；命令、测试收集范围和环境要求来自该 checkout 的 `justfile` 及其调用文件。

`testing-seams.md` 定义授权边界，`testing-plan.md` 定义计划，`testing-tdd.md` 定义 red 证据，`testing-gates.md` 定义验证覆盖。各角色入口按结构化的角色、scope、axis 和 Test plan mode 规定固定读取组合；不在本定位文件中另建递归路由，不因后续可能需要而预读其他 testing 文件。共享文件内的跨文件指针供规划和人工 TDD 场景使用，本 skill 的角色不用它们扩展固定组合。已在当前上下文读取且未变化的文件无需重复加载。固定组合中的文件不可读取时，按当前阶段的缺事实/阻塞处理。

需要用户确认的 seam 变化，在本流程返回 `BLOCKED`；已有批准不重复询问。无效计划不进入实现。实测 BASE 由 controller 在安装后绑定 `gate-plan` 并通过 `gate-core` 建立快速基线，执行者按测试契约记录证据。完整 `gate-full` 保留给最终干净候选；单票的 deferred 边界仍需要能证明 acceptance 的定向证据。

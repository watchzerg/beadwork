# executor 开工与提交前检查

两个入口均使用 controller 的 executor dispatch，只读取源码、Git 和 Beads；`inspect` 另写本轮证据。脚本不暂存、不 commit、不运行格式化或验证。成功 stdout 为 JSON；失败非零退出，保留现场，由 executor 按现有状态规则报告。

## 开工或接替

```bash
python3 <skill-dir>/scripts/executor-operations.py inspect --dispatch <dispatch.json>
```

核对 worktree 归属、branch、BASE ancestry 和 schema/expected-plan 文件。新票要求 HEAD 等于 BASE 且现场干净；恢复票允许已有 commits 和未提交工作。查询当前 ticket、comments 和 parent，核对 ID、ticket 的 `in_progress` 与正文存在性。

每次创建独立 `context-*` 目录，保存查询 JSON、完整 description 和 `inspection.json`。stdout 返回路径、HEAD、staged/unstaged/untracked 路径与恢复 commit 列表；失败已取得的材料保留在错误中指向的目录。缺少可用 dispatch 时按共享报告交付契约返回部分报告。

executor 读取这些来源，再按 agent 指令读取规则、spec、ADR 和相关代码。保存正文不能修复上游缺失；脚本也不判断需求完整性、已完成层的正确性或 test plan 语义。

## 每次提交前

```bash
python3 <skill-dir>/scripts/executor-operations.py check-layer --dispatch <dispatch.json> --input <layer.json>
```

`layer.json` 仅包含 `files`（本次提交的 worktree 相对文件路径数组）和 `message`（实际 commit message）。路径逐项填写，允许删除；重命名填写旧、新两个路径，不能使用 glob、目录简写或 `..`。该清单只约束本次提交。

executor 先选择本层范围；对仍存在且按项目契约适用的文件执行 `just fmt`，无适用文件时跳过，避免无参数扩大到全仓。检查格式化后的 diff，通过现有采集入口完成验证，显式暂存并核对 staged diff，再运行本入口。

检查 staged 集合非空且与 files 完全一致、不含 `.beads`，本层路径没有未暂存内容，message 含完整 ticket ID，并复查 Git 身份。返回实际 HEAD、staged 路径及本层之外仍未提交的路径；后者允许保留，由 executor 判断本层是否依赖它们。

检查通过后由 executor 执行普通 commit，核对实际 SHA 和提交内容。脚本不判断层是否可独立验证、覆盖是否充分，也不将 HEAD/status 相同视为内容相同。验证后源码变化需重跑受影响验证；检查后改变暂存范围需重新检查。

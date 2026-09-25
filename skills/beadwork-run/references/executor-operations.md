# ticket 开工与提交前检查

inspect 使用 root/stage executor 或 implementer dispatch；check-layer 仅由 implementer 使用其 dispatch，只读取源码、Git 和 Beads；`inspect` 另写本轮证据。脚本不暂存、不 commit、不运行格式化或验证。成功 stdout 为 JSON；失败非零退出，保留现场，由调用者按当前角色状态规则报告。

## 开工或接替

```bash
python3 <skill-dir>/scripts/beadwork.py executor inspect --dispatch <dispatch.json>
```

核对 worktree 归属、branch、BASE ancestry 和 schema/expected-plan 文件。新票要求 HEAD 等于 BASE 且现场干净；恢复票允许已有 commits 和未提交工作。查询当前 ticket、comments 和 parent，核对 ID、ticket 的 `in_progress` 与正文存在性。

每次创建独立 `context-*` 目录，保存不含任何嵌套 description 的 tracker metadata 投影、完整 comments 和 `inspection.json`；ticket/parent description 作为 path/sha256 binding 存入 ticket root 的内容寻址目录，相同内容跨 stage 复用。stdout 返回这些 binding、HEAD、staged/unstaged/untracked 路径与恢复 commit 列表；失败已取得的材料保留在错误中指向的目录。缺少可用 dispatch 时按共享报告交付契约返回部分报告。

executor 读取这些来源，再按 agent 指令读取规则、spec、ADR 和相关代码。保存正文不能修复上游缺失；脚本也不判断需求完整性、已完成层的正确性或 test plan 语义。

## 每次提交前

```bash
python3 <skill-dir>/scripts/beadwork.py executor check-layer --dispatch <dispatch.json> --input <layer.json>
```

`layer.json` 仅包含 `files`（本次提交的 worktree 相对文件路径数组）和 `message`（实际 commit message）。路径逐项填写，允许删除；重命名填写旧、新两个路径，不能使用 glob、目录简写或 `..`。该清单只约束本次提交。

implementer 只选择当前 ticket 的代码、测试和必要文档，排除 `.beads` 与无关改动。按项目规则格式化相关文件，检查修改后的 diff，并执行必要的静态检查；通过 verification.md 的采集入口运行覆盖本层的最窄相关 `test`，不得以零匹配为通过。项目可提供独立格式化或类型检查命令，Beadwork 不要求其固定名称。显式暂存并核对 staged diff，再运行本入口。

检查 staged 集合非空且与 files 完全一致、不含 `.beads`，本层路径没有未暂存内容，message 含完整 ticket ID；实际 message 另说明交付范围与验证状态，并复查 Git 身份。返回实际 HEAD、staged 路径及本层之外仍未提交的路径；后者允许保留，由 implementer 判断本层是否依赖它们。

检查通过后由 implementer 执行普通 commit，核对实际 SHA 和提交内容。脚本不判断层是否可独立验证、覆盖是否充分，也不将 HEAD/status 相同视为内容相同。验证后源码变化需重跑受影响验证；检查后改变暂存范围需重新检查。

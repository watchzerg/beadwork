# Review 后的文档收尾

executor 与 finalizer 共用此流程。只有当前两轴均完成且 `repair_route: docs` 时进入；含代码 blocking findings 使用原修复 stage，审查未完成或需求不明确则阻塞。代码范围包括产品行为、测试、配置、构建逻辑和 skill 执行协议；Markdown 不自动属于纯文档。

## 一次限定任务

直接派发者核对两轴全部 blocking findings，仅调整说明能解决时，准备 `input.json`：

```json
{
  "files": ["README.md", "docs/usage.md"],
  "reason": "仅补齐已实现且已验证行为的使用说明；不改变行为或执行协议。"
}
```

files 使用 worktree 相对文件路径，包含必要的直接关联文档，不使用目录或 glob。派发者负责语义分类；脚本约束实际提交范围，不能自行从路径推断是否为文档。若确需扩大文档范围，停止并说明，不绕过原派发范围。

```bash
python3 <skill-dir>/scripts/beadwork.py executor document-closeout-prepare --dispatch <stage-dispatch.json> --input <input.json>
```

返回 document_dispatch、document_launch_context、acceptance_schema_path 和 document_closeout。按 dispatch 的 model/reasoning_effort 和独立上下文派发一次 document-syncer，交接绑定的原 review、需求、实现依据和通信目标。该 writer 只修原 findings 及直接关联内容；任务内可编辑、自查、修正，再通过 document-assemble 交付，不运行 gate-core/gate-full，不派 reviewer。

按项目约定执行文档检查：可通过 `run-verification --recipe test -- <项目文档参数>` 采集；已有独立文档命令或人工检查应记录命令、结果及证据路径。没有独立命令时核对 diff、链接、示例和实现依据，不为此新增强制 recipe。已通过采集器执行的文档检查按完整 argv 分别取最新记录；每项必须在文档提交后的当前干净 HEAD 通过，不能用新提交或更换参数隐藏旧失败。无法验证的事项明确列为阻塞。

## 派发者定点验收

document-syncer 使用现有 document-assemble 生成报告与回执。executor/finalizer 核对全部原 findings 是否解决、完整提交范围是否保持纯文档、检查结果是否充分；不扩展成全票或全批次的新一轮审查。将结论填写到 acceptance_schema_path 对应的输入：

```json
{
  "outcome": "passed",
  "dispositions": [
    {
      "axis": "spec",
      "finding_index": 0,
      "resolved": true,
      "evidence": "docs/usage.md 的参数示例已与原 finding 引用的 CLI 实现和验证结果一致。"
    }
  ],
  "scope_evidence": "逐项核对提交 diff，仅修改原派发文件中的说明。",
  "checks_evidence": "文档链接检查通过，命令示例与当前 CLI 声明一致；附实际日志或来源路径。",
  "blockers": []
}
```

finding_index 是该轴原 findings 数组的零起始索引；所有 blocking findings 必须恰好出现一次，不能遗漏或通过重新编号替换原问题。

```bash
python3 <skill-dir>/scripts/beadwork.py executor document-closeout-accept --dispatch <stage-dispatch.json> --report <document-report.json> --receipt <document-receipt.json> --input <assessment.json> --observation <observation.json>
```

- `passed`：writer DONE，全部 findings 已解决、检查通过、实际提交未越界、现场干净且任务已确认停止。协调者组装 passed，继续 ticket DONE 或最终 READY_TO_MERGE。
- `blocked`：仍有文档遗漏、检查失败、越界或依据不足。保留具体 blockers，组装 blocked 并交回 controller；不自动再派文档 writer 或 reviewer。
- `code_required`：确认必须修复实现、测试、配置或执行协议；dispositions 和 blockers 给出具体依据。writer 停止且现场干净后组装 code_failure，沿原额度进入下一代码修复 stage，重新验证和 review。

“一次”指一个文档任务与一次最终验收，不限制任务内编辑次数。未交付的任务中断时先确认旧 writer 和命令结束，再接续原 dispatch；不重新 prepare。验收记录选中后该轮结束；不得把 blocked 自动改成另一次修复任务。新 stage 中的 review 可以再次按同一规则分流。

## 交付证据

原 gate 和双轴 review 继续绑定代码候选 H1。文档提交 H1 → H2 由 document_closeout 绑定 writer、原 collection、报告、回执、收尾观察和逐项验收；最终交付 H2。原 BLOCKED findings 不改写为 PASS，也不声称代码 gate 在 H2 重新运行过。

收尾开始后原 review 保持冻结。组装器与独立 verifier 重新核对来源、阶段、BASE/HEAD 和验收状态；只有通过的收尾允许复用 H1 的代码验证。finalizer 仍先完成 stage 0 的批次文档同步与完整 gate-full；review 后收尾不能替代这些前置步骤。原始报告、提交和收尾记录均保留，不能删除失败证据以获取成功。

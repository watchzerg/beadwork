# 子 agent 交付

所有角色使用文件报告、短回执与 SHA-256 内容绑定。直接派发者验收自己的子 agent，模型判断语义，脚本校验身份、现场和来源。

## 权限与派发

controller 独占 Beads 写入、Git/worktree 生命周期、安装与最终集成。其余角色对 Beads 只读；源码由当前 implementer/fixer 写入，stage 0 文档由 document-syncer 写入；协调者与 reviewers 只写证据。writer 与 reviewer 直接完成本角色工作，子 agent 派发由 controller/executor/finalizer 负责。writer 使用普通 commits；本流程不使用 stash、reset、amend、squash、force-remove 或 push。

同一时刻只有一个源码 writer。派发接替 writer、合入或清理前，派发者确认原 writer、命令与后代任务已结束。review 期间保持候选冻结，后续源码修复进入新 stage。

prepare 返回 dispatch 和角色所需的 required_reads。按返回模型配置派发独立上下文 agent，使用 `fork_turns: "none"`；交接 dispatch 路径、项目规则、需求来源及可用的进度通信目标。子角色读取自己的清单，条件参考在触发时读取。派发者仅为 outputSchema 读取 receipt schema，支持 strict 时启用。

## 报告与验收

1. 使用 assembler 的角色读取 draft_schema_path，填写语义判断；脚本生成 Git 身份、提交、验证及 review 来源。这些角色在诊断时读取完整输出 schema；reviewer 读取 report_schema_path 并填写 AxisReport。
2. assemble 已执行完整自检；成功 stdout 即最终短回执，合法 BLOCKED 也可交付。独立 check 用于报告更正或复核。输出采用新文件名，保留原件。
3. 派发者等待子 agent 及命令结束，原样保存 receipt，读取报告并做相应语义验收。
4. 编写实际收尾 observation：task_id、stopped、observed_at、evidence、unresolved。普通验收直接传 `--observation <observation.json>`，入口自动保存内容绑定的 closure，然后执行完整验收。receipt 到达仅证明交付，不证明任务结束。
5. 验收成功后由脚本选择来源。更正使用新的 report/receipt，由派发者明确选择；同 HEAD 更正只补事实，额度与 review round 沿用原值。

成功及 code_failure 推进需要确认 stopped 且 unresolved 为空。未知停止状态可交付 BLOCKED，现场继续保留。子 agent 自报与派发者观察冲突时补齐实际收尾证据。SHA-256 绑定文件内容，语义结论由接收者核对；原始 findings 保存在来源链中。

## 入口

| 子角色 | 生成报告 | 直接派发者验收 |
| --- | --- | --- |
| preflight | preflight assemble | controller accept |
| implementer | implementer-assemble | implementer-accept |
| executor | ticket-assemble → ticket-deliver | controller accept |
| document-syncer | document-assemble | document-accept |
| fixer | fixer-assemble | fixer-accept |
| finalizer | final-assemble → final-deliver | controller accept |
| reviewer | dispatch.self_check_argv | review-collect |

writer 交付见 [writer-delivery.md](writer-delivery.md)，review 见 [review.md](review.md)。源码写入前的能力或上下文阻塞，也尽量通过正常入口交付部分报告；入口材料缺失时读 [recovery-report.md](recovery-report.md)。

## 等待与进度

子角色在 commit、长 gate 开始/结束和 reviewer 派发时直接向可用的派发者目标发送简短进度。默认连续 20 分钟无已确认进展后排查 Git、验证记录和后代任务；正常运行继续等待。用户要求停止或确认失控写入时及时中止。

## 恢复与补充事实

已有 closure 时，验收可直接使用 `--closure <closure-source.json>`。需要单独保存观察时：

```bash
python3 <skill-dir>/scripts/beadwork.py executor handoff-close --dispatch <child-dispatch.json> --report <report.json> --input <observation.json>
```

原始 JSON 输出可直接保存并作为 --closure 输入。脚本记录宿主观察，不探测 agent 或操作旧 PID。

```bash
python3 <skill-dir>/scripts/beadwork.py executor context-add --dispatch <root-or-stage-dispatch.json> --input <facts.json>
```

facts 包含非空 reason 和 sources（path/sha256 数组）；事实文件位于证据目录。入口追加来源链，恢复时交接 context_sources，沿用 BASE、需求、seam 授权和额度。发现事实冲突时交回派发者。

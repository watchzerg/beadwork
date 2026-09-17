# 正常流程精简与脚本化验收记录

日期：2026-09-17。范围见 [改造计划](normal-flow-simplification-plan.md)。本轮采用 clean cutover，保留原有未提交修改与历史证据，不提供旧批次续跑迁移。

## 实施结果

| 项目 | 当前行为 | 主要验证 |
| --- | --- | --- |
| checkpoint 来源选择 | ticket-assemble / final-assemble 只接受 dispatch、draft、output；review/fixer 来源从已选择 checkpoint 读取 | 多阶段历史、同轮更正、恢复、遗漏或损坏来源拒绝 |
| draft 输入契约 | 五类语义草稿由 draft_contracts 统一生成与校验；机械字段由 assembler 生成，输出 schema 仍完整校验 | ticket/final draft 注入机械字段时，在报告或 checkpoint 写入前拒绝；现有角色交付链回归 |
| comment ID | tracker 从唯一匹配 comment 读回实际 ID 并返回字符串 comment_id | 首次发布、缓存重入、结果文件丢失、重复 marker 与缺失 ID |
| 完整初始化 | 固定 update-main 与 preflight/plan 来源，创建 worktree、核对共享 workspace、执行 install/env-facts/gate-full、claim 与批次 comment 后发布 ready | 安装/gate 失败、未知命令收尾观察、workspace 不匹配、基线移动、child 已开工、claim/comment 结果丢失 |
| 推送与清理 | controller push 固定受审 SHA，Git push/readback 后推送 Beads；cleanup 必须消费交付结果，显式 skip 必须有原因 | 本地 bare remote、读回 SHA 不符、Git/Beads 部分失败、重试包含新 comment、skip 组合、损坏结果与重复清理 |
| 正常路径精简 | 删除手工初始化步骤、重复 draft 字段清单和旧批次回退说明；删除 recovery-legacy-cleanup | 本地引用检查、当前命令与角色入口核对 |
| 测试与生产边界 | 删除生产旧 stage 构造及无用 alias；fixture 直接构造工具级测试所需 stage 数据 | AST 边界检查；当前 ticket/finalizer 公开入口仍覆盖六阶段、模型升级、恢复与 gate 修正额度 |

初始化和推送共用的小型 operation_commands 模块只负责 started/result/log 证据，不承担流程调度或重试策略。失败尝试保留；初始化重跑上游步骤后，下游成功结果不再复用。

## 静态输入量

以下数字为字符数，不是 token 或运行时间。schema 使用 `json.dumps(..., ensure_ascii=False, indent=2)`，不计末尾换行；比较完整输出 schema 与现在正常填写的 draft schema。reviewer 仍读取 AxisReport。

| 角色 | 完整输出 schema | draft schema | 减少 |
| --- | ---: | ---: | ---: |
| preflight | 8,885 | 4,048 | 54.4% |
| implementer | 5,497 | 2,849 | 48.2% |
| executor stage | 40,534 | 2,503 | 93.8% |
| fixer | 4,449 | 2,097 | 52.9% |
| finalizer stage | 16,492 | 2,695 | 83.7% |

下表是相同文件组合在本轮实施前后的对照，包含实施前已有的工作区修改。它用于比较受影响材料，不代表完整运行时上下文；项目规则、dispatch、其他按需契约和历史证据均未计入。

| 角色材料组合 | 实施前 | 实施后 |
| --- | ---: | ---: |
| controller：SKILL + controller-operations + report-delivery | 24,083 | 24,091 |
| implementer：角色入口 + ticket-execution + report-delivery | 13,388 | 12,743 |
| executor：角色入口 + ticket-execution + report-delivery | 12,194 | 11,549 |
| finalizer：角色入口 + final-execution + report-delivery | 9,644 | 9,246 |
| preflight：角色入口 + report-delivery | 6,729 | 6,386 |

controller 的材料总量基本持平，收益主要来自模型无需逐项组织初始化命令与 comment、手工提取 comment ID，或维护 Git/Beads 推送和清理证据。执行角色的主要收益来自更小的输入 schema，以及不再重复组织机械来源字段。

## 验证记录

最终完整回归通过：302 个测试，464.487 秒，`OK`。本机完整日志位于 `/tmp/beadwork-full-final-tests.log`。首次完整运行暴露的旧兼容测试依赖已删除或迁移到当前入口；最终整套运行使用稳定的脚本版本，无失败。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_*.py'
uv run --no-project --with PyYAML --script /Users/watchzerg/.codex/skills/.system/skill-creator/scripts/quick_validate.py /Users/watchzerg/projects/beadwork/skills/beadwork-run
git diff --check
```

skill validator、Python AST 解析和本地 Markdown 链接检查通过。用户级安装路径解析到本仓库 `skills/beadwork-run`；`agents/openai.yaml` 继续设置 `allow_implicit_invocation: false`。

验证使用临时 Git/worktree、受控 Beads fixture 和本地 bare remote。未运行真实消费项目 ticket graph、真实 Beads 后端写入或 Codex 嵌套派发；未实测 token、延迟或成功率。未执行本仓库 commit/push。

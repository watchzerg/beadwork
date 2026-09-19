# 正常流程精简与脚本化改造计划

本文保留 2026-09-17 的历史方案。2026-09-19 已移除最终 Git/Beads push 及交付结果前置条件；现行本地清理入口见 [controller-operations.md](../../skills/beadwork-run/references/controller-operations.md)。下文推送部分不再是执行契约。

## 目标与边界

实施已确认的七项优化：checkpoint 自动选择来源、draft 输入契约、tracker comment ID、完整批次初始化、推送与清理闭环、兼容说明退出正常路径、测试构造与生产逻辑分离。

用户已确认没有未完成批次，采用 clean cutover；本轮接口不保留兼容参数、旧字段回退或 intent 迁移。历史证据不改写。保留工作区已有未提交修改、角色边界、双轴 review、阶段额度、固定 BASE/HEAD、唯一 writer 与 append-only 语义。

## 实施顺序

1. 来源与边界：ticket/final assemble 只消费 checkpoint；删除显式 review/fixer 参数；移除生产旧 stage 构造和 controller 无用别名，测试仅构造所需数据。
2. draft 契约：preflight、implementer、ticket stage、fixer、finalizer stage 共用生成和校验定义；dispatch 提供 draft_schema_path。模型只填语义字段，输出机械字段由脚本生成；reviewer 保留 AxisReport 契约。
3. tracker 与初始化：comment 唯一读回并返回字符串 comment_id；初始化绑定 update-main 结果，依次完成 Beads worktree/workspace、install/env-facts/gate-full、parent claim 和批次 comment 后才发布完成记录。失败尝试追加，未知任务先获得实际收尾观察再恢复。
4. 推送与清理：controller push 固定受审 SHA，Git 推送与读回后执行 Beads push；每次尝试独立记录，支持明确 skip 及原因。cleanup 必须消费绑定 checkpoint 的成功/跳过交付结果。

各批同步修改调用方、相关文档和测试。正常路径删除重复机械说明；历史格式识别仅用于诊断，不保留旧续跑入口。不建立通用工作流引擎。

## 接口与恢复

- draft-schema.json 为模型输入契约，assembler 共用定义并在写候选前校验；完整输出 schema 继续由脚本验证。
- ticket-assemble/final-assemble 输入仅 dispatch、draft、output；review-collect 继续显式选择报告并更新 checkpoint。
- tracker comment 结果保存 comment_id；丢失本地结果时通过原 intent 读回，不重复发布。
- batch_initialize prepare/execute 绑定固定 update-main 结果及 READY preflight。完成记录绑定步骤、claim 和 comment；不能用于跳过后续实时检查。
- 初始化失败步骤使用新尝试恢复；重新 install 后重跑后续环境及 gate。已进入 child 工作的批次不重跑初始化。
- controller push --input 接收 merge checkpoint 及 Git/Beads 的 push/skip 决定；skip 必须说明用户限制。恢复重新推送，不永久缓存 Beads 成功。
- controller cleanup --merge-record --delivery-result 校验交付结果和现有 Git/worktree 条件；成功推送到清理之间不新增本流程 Beads 写入。

## 验证与验收

使用公开 CLI、临时 Git/worktree、受控 Beads fixture 与本地 bare remote。覆盖来源更正/多阶段/损坏、draft 机械字段注入、comment 重入与结果丢失、初始化失败及中断恢复、workspace 不匹配、推送部分失败/跳过/重试、无交付结果拒绝清理以及重复清理。

每批运行相关测试；最后运行完整回归、skill validator、引用/安装路径/调用策略核对及 whitespace 检查：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s skills/beadwork-run/scripts -p 'test_*.py'
git diff --check
```

记录相同角色必读材料字符量与删除的机械步骤，不将其宣称为实测 token 或延迟收益。脚本 fixture 不代表真实 Beads 后端或 Codex 嵌套派发已验证。交付不包含真实项目执行、本仓库 commit/push 或远端写入。

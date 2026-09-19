# 串行规划与发布

为 Beadwork 调用 `to-tickets` 或调整剩余票顺序时读取。真实 blocking 依赖保留在 Beads；parent 保存完整执行序列，批准并接纳后严格执行，不跳过被阻塞的下一张票。

## 规划与确认

在 `to-tickets` 同一次确认中给出：计划位置、交付、前序已提供的能力、本票新增行为、真实 blockers 和 Test plan。使用 [testing-plan.md](testing-plan.md) 与 [testing-gates.md](testing-gates.md)；需要 seam 时读取 [testing-seams.md](testing-seams.md)。

先形成最小可验证路径，尽早处理影响后续设计的不确定性；每张票以已完成前序成果为基线。主要实现责任明确归属，回归验证可以重叠。若一张票必须吸收另一张未完成票的大部分交付，先修正切片或真实依赖。不要按文件划分责任，也不要仅因票小而优先。

用户一次确认切片、依赖及顺序。发布时保存临时编号到完整 ID 的映射，恢复发布沿用已创建票的确定身份。依赖写入并读回后，用以下脚本发布计划；没有有效计划的 parent 不能开工。日常不增加独立 `to-chain`，不 fork 上游 skill。

此接入契约明确覆盖上游 `to-tickets` 的“不修改 parent”限制：已批准拆票的发布者可以新增或替换唯一 execution-plan 区块；不得改 parent 其他正文或状态，不得因此关闭 parent。所有 Beads 写入仍遵循调用场景的所有权：拆票阶段由发布者执行，运行阶段仅 controller 写入。

## 发布入口

`<skill-dir>` 解析为此 skill 的真实绝对路径。所有输入、intent、输出使用未存在的绝对文件路径；证据放在目标项目 `.worktrees/.evidence/<parent>/` 下，不进入 Beadwork 源码仓库。

创建 `publish-input.json`：

```json
{
  "repository_root": "/absolute/project",
  "parent_id": "project-abc",
  "ticket_order": ["project-abc.1", "project-abc.2", "project-abc.5", "project-abc.3"]
}
```

```bash
python3 <skill-dir>/scripts/beadwork.py plan prepare --input <publish-input.json> --output <publish-intent.json>
python3 <skill-dir>/scripts/beadwork.py plan publish --intent <publish-intent.json>
```

脚本检查完整 children、平铺关系、逐票 blocking 依赖和活动票位置；生成只替换目标区块的正文，写前重读，写后读回。发布失败保留 intent；同一 intent 重试不会重复追加区块。正文或 parent 状态被其他人修改时重新 prepare，不覆盖对方修改。写前检查与写后验证不是跨进程事务。

生成的 parent 区块只有 `ticket_order`，无 `version`、序号、priority 或前后指针：

````markdown
## 执行计划

<!-- beadwork:execution-plan:start -->
```json
{
  "ticket_order": ["project-abc.1", "project-abc.2"]
}
```
<!-- beadwork:execution-plan:end -->
````

数组位置决定执行顺序，ID 只作身份。子票不重复保存顺序。脚本拒绝缺失、重复、损坏的区块、重复 JSON keys、额外字段、children 不匹配和逆向 blocking 依赖；模型无需手工重复检查。

## 准入与执行

Preflight collect 自动解析计划并保存原始来源；READY 验收再次查询现场，并固定批次计划。缺计划返回 BLOCKED，不自动按票号或 priority 推断。计划位置、范围、依赖、漂移和 reopen 检查由脚本承担；模型只核对增量交付和恢复事实。

`beadwork.py graph next`、main-sync 和 child claim 共用计划事实与选择。第一张未关闭票不可领取则停止；活动票必须是该票且符合原有恢复身份。恢复使用原 claim intent、BASE、stage 和执行现场，排序不能重启或更换 writer。

计划证据位于 `<primary>/.worktrees/.evidence/<parent>/execution-plan/initial.json`。调整使用唯一 `after-<前记录 SHA256>.json`，每条记录绑定前记录及批准来源；从 initial 沿来源链查找，禁止按目录时间选择。`started-*`、`closed-*` 记录领取与关闭来源，用于拒绝移动已开始票及重新打开已完成票。

Parent 其他正文、JSON 空白变化不影响顺序比较。执行序列变化时不领取新票，也不自动中止已有 writer；先保留并核对当前执行现场。同步前后和实际 claim 都检查绑定；旧 intent 不能采用新计划开工。

## 调整未开始部分

用只读入口获取 parent 计划及当前选择绑定：

```bash
python3 <skill-dir>/scripts/beadwork.py plan inspect --repository-root <primary> --parent <parent-id>
```

首次计划只由 READY preflight 固定，要求批次尚未开工。缺计划或已有执行现场但未采用计划时直接拒绝，不提供迁移、补建或默认排序。

中途改序仅调整未开始部分，不增删 children，不移动已关闭或已开始票；活动票未结束或 main-sync 未完成时不能接纳重排。若已发布新顺序导致旧同步无法恢复，先用发布脚本恢复已接纳顺序、完成同步，再重新发布和接纳调整。用户批准后先 publish 更新 parent，再创建 `adopt-input.json`：

```json
{
  "repository_root": "/absolute/project",
  "parent_id": "project-abc",
  "ticket_order": ["project-abc.1", "project-abc.3", "project-abc.2"],
  "previous": {"path": "/absolute/selected-record.json", "sha256": "<inspect 返回的 SHA256>"},
  "reason": "本次已批准的调整原因"
}
```

`previous` 必须使用 inspect 返回的已采用计划绑定，不接受 `null`。不得因下一张被阻塞就自行接纳改序。

```bash
python3 <skill-dir>/scripts/beadwork.py plan adopt --input <adopt-input.json>
```

脚本校验现场、范围和受保护位置，追加来源绑定。发布成功但接纳前中断时，执行器保持阻塞；继续同一接纳操作即可。缺来源、多个活动票、reopen、children 增删或恢复矛盾时报告具体阻塞，不改写历史。

# 执行模型注意力减负

本次优化当前 skill 的正常执行路径。保留 controller、协调者、writer 和双轴 reviewer 的职责，保留当前修复额度、候选 HEAD 和 append-only 证据。

## 改动顺序

1. 统一角色读取清单，由 prepare 生成；角色说明保留职责、语义判断和正常步骤。
2. 将 ticket 特殊恢复、模型扩展和 review 中断处置路由到条件参考文件；修正 direct verification 提交检查、comment 核对对象和 fixer 恢复路由。
3. 为最终修复生成内容绑定的当前阶段上下文，沿原始来源校验；累计历史留作审计。
4. 验收入口直接接收收尾观察，自动保存 closure；review collection 同样支持观察输入，保留显式选择及原始证据。
5. 精简重复的禁止句、机械字段说明和历史格式说明，按正常 ticket、修复与恢复场景复查。

gate-fix 的三次额度和修改前登记继续保留：源码修改本身不是脚本入口，自动推断登记时机无法可靠区分开发验证与交付修复。本次将漏登记的适用范围明确为 ticket，避免误导 final fixer。收尾状态的时序重构涉及恢复准入和全部报告消费者，本次保留双边确认，用合并 CLI 操作减少正常路径成本。

## 验证

- 读取清单覆盖不同 role、mode 和 axis，并随计划适配刷新。
- 最终上下文覆盖 stage 0 gate 失败、后续 reviewer findings、重复恢复、来源篡改和历史裁剪。
- 收尾观察合并入口仍拒绝未停止的成功交付及不匹配的来源。
- 执行相关 unit、integration/workflow、CLI/distribution 与 `just gate-full`。
- 记录当前说明体量和实际减少的机械命令；真实 Beads 与真实 Codex 派发需单独验收。

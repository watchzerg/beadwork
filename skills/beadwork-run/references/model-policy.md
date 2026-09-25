# 模型政策与授权扩展

仅在评估 complex_ticket、主动提高模型档位或用户明确授权扩展时读取。正常派发使用 prepare 返回的模型配置。

模型与矩阵以 `../scripts/workflow_policy.py` 为准。常规三档依次为 GPT-6 Luna-high、Sol-medium、Sol-high；普通 implementer 六阶段各档两次。授权扩展额外允许 Astra-medium、Astra-high，普通阶段禁止选择 Astra。档位表示工作流升级顺序，不是实测能力排名。executor 本体普通票使用 Sol-medium，`complex_ticket` 使用 Sol-high，并将 implementer 下限设为 Sol-medium、两轴 reviewer 下限设为 Sol-high；提前升档后不要求再凑齐低档次数。跨模块协议、并发恢复、资源生命周期或共同不变量适合标记复杂票；文件多或测试慢本身不构成复杂票。


模型与矩阵以 `../scripts/workflow_policy.py` 为准。stage 0 派发独立 document-syncer，固定使用 GPT-6 Sol-medium（DOCUMENT_SYNC_MODEL），无 fixer；stage 1..5 的 fixer 默认为 GPT-6 Sol-medium 两次、Sol-high 三次。Standards 首轮使用 Sol-medium，修复后使用 Sol-high；Spec 始终使用 Sol-high。新阶段可用 `model_overrides` 覆盖 fixer/standards/spec，并提供非空 `model_override_reason`；只允许常规档位内升档，后续继承且不降档，同阶段恢复沿用原模型。finalization 不使用 Astra。

- `continuation: extend`：每张 ticket 仅可追加一次，仅在默认 stage 5 交付 `code_failure` 且旧任务已停止后使用。controller 交接用户明确追加的额度与授权说明，executor 传入 `additional_stages`（整数 1–5）和非空 `extension_reason`；普通“继续”、自动重试或接替会话不构成追加授权。三个角色默认使用 `gpt-6-astra` / `medium`；授权时可用 `model_overrides` 逐角色覆盖并填写 `model_override_reason`，例如 reviewers 保持 Sol-high，或 implementer 使用 Astra-high。未指定角色采用 Astra-medium。先应用覆盖，再检查不低于该角色此前实际档位。脚本持久化追加数量、授权说明、覆盖配置及最终模型；repair/resume 继承已选模型和计数，不重新应用 Astra 默认值。扩展上限耗尽后停止，不能再次 extend。

"""模型、阶段和修复额度的单一静态策略来源。"""

MODEL_LEVELS = [
    {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
    {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
    {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
]
STAGE_MODELS = [(0, 0, 2), (0, 1, 2), (1, 1, 2), (1, 2, 2), (2, 2, 2), (2, 2, 2)]
# stage 0 只验证；stage 1..5 的 fixer 依次使用 Terra-medium 两次、Terra-high 两次、Sol-medium 一次。
FINAL_STAGE_MODELS = [(0, 1, 2), (0, 1, 2), (0, 2, 2), (1, 2, 2), (1, 2, 2), (2, 2, 2)]
MODEL_ROLES = ("executor", "standards", "spec")
MAX_STAGES = len(STAGE_MODELS)
MAX_GATE_REPAIRS = 3

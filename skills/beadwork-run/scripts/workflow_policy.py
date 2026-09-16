"""模型、阶段和修复额度的单一静态策略来源。"""

MODEL_LEVELS = [
    {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
    {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
    {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
    {"model": "gpt-6-astra", "reasoning_effort": "medium"},
]
STAGE_MODELS = [(0, 0, 2), (1, 0, 2), (2, 1, 2), (3, 2, 3)]
FINAL_STAGE_MODELS = [(2, 1, 2), (2, 1, 2), (2, 2, 2), (3, 2, 3)]
MODEL_ROLES = ("executor", "standards", "spec")
MAX_STAGES = len(STAGE_MODELS)
MAX_GATE_REPAIRS = 3

"""模型、阶段和修复额度的单一静态策略来源。"""

MODEL_LEVELS = [
    {"model": "gpt-6-luna", "reasoning_effort": "high"},
    {"model": "gpt-6-sol", "reasoning_effort": "medium"},
    {"model": "gpt-6-sol", "reasoning_effort": "high"},
]
EXTENSION_MODEL_LEVELS = MODEL_LEVELS + [
    {"model": "gpt-6-astra", "reasoning_effort": "medium"},
    {"model": "gpt-6-astra", "reasoning_effort": "high"},
]
STAGE_MODELS = [(0, 1, 1), (0, 1, 2), (1, 1, 2), (1, 2, 2), (2, 2, 2), (2, 2, 2)]
# stage 0 只验证；stage 1..5 的 fixer 依次使用 Sol-medium 两次、Sol-high 三次。
FINAL_STAGE_MODELS = [(1, 1, 2), (1, 2, 2), (1, 2, 2), (2, 2, 2), (2, 2, 2), (2, 2, 2)]
MODEL_ROLES = ("executor", "standards", "spec")
MAX_STAGE_EXTENSION = 5
# 静态报告 schema 覆盖一次用户授权的最大扩展；运行时仍由 dispatch 的
# stage_limit 和 append-only extension 证据决定实际可用额度。
MAX_STAGES = len(STAGE_MODELS) + MAX_STAGE_EXTENSION
MAX_GATE_REPAIRS = 3

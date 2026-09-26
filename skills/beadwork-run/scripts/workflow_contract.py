"""Beadwork agent 的独立启动上下文契约。"""

import repository

LAUNCH_CONTEXT = {"fork_turns": "none", "required": True}


def launch_context(value):
    repository.require(
        value.get("launch_context") == LAUNCH_CONTEXT,
        'agent dispatch 必须显式要求 fork_turns: "none"',
    )
    return dict(LAUNCH_CONTEXT)


def set_launch_context(value):
    value["launch_context"] = dict(LAUNCH_CONTEXT)
    return value

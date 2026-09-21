"""Beadwork 当前执行现场契约；旧现场只读保留，不自动迁移。"""

import repository

VERSION = 4
LAUNCH_CONTEXT = {"fork_turns": "none", "required": True}


def launch_context(value):
    repository.require(
        value.get("launch_context") == LAUNCH_CONTEXT,
        'agent dispatch 必须显式要求 fork_turns: "none"',
    )
    return dict(LAUNCH_CONTEXT)


def stamp(value):
    value["workflow_contract_version"] = VERSION
    value["launch_context"] = dict(LAUNCH_CONTEXT)
    return value


def require_current(value):
    repository.require(
        value.get("workflow_contract_version") == VERSION,
        "执行现场契约版本不受支持；旧证据保持不变，请从新批次开始",
    )
    launch_context(value)
    return value


def current(value):
    return value.get("workflow_contract_version") == VERSION

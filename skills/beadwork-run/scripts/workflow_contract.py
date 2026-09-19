"""Beadwork 当前执行现场契约；旧现场只读保留，不自动迁移。"""

import repository

VERSION = 2


def stamp(value):
    value["workflow_contract_version"] = VERSION
    return value


def require_current(value):
    repository.require(
        value.get("workflow_contract_version") == VERSION,
        "执行现场契约版本不受支持；旧证据保持不变，请从新批次开始",
    )
    return value


def current(value):
    return value.get("workflow_contract_version") == VERSION

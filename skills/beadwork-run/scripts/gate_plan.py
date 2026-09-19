"""目标项目 gate-plan 的读取与机械校验。"""

from __future__ import annotations

import json
import re

import repository

REQUIRED_RECIPES = (
    "check-toolchain",
    "install",
    "typecheck",
    "test",
    "gate-plan",
    "gate-core",
    "gate-full",
    "env-facts",
    "fmt",
)
RESERVED = {"gate-plan", "gate-full"}


def parse(raw, recipes):
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ValueError("gate-plan 必须输出 JSON object") from error
    repository.require(
        isinstance(value, dict) and set(value) == {"core", "full", "defer_to_final"},
        "gate-plan 必须且只能包含 core、full 与 defer_to_final",
    )
    core, full, deferred = value["core"], value["full"], value["defer_to_final"]
    repository.require(
        isinstance(core, str) and re.fullmatch(r"gate-[A-Za-z0-9_-]+", core), "gate-plan core 无效"
    )
    repository.require(
        isinstance(full, list)
        and full
        and all(
            isinstance(item, str) and re.fullmatch(r"gate-[A-Za-z0-9_-]+", item) for item in full
        ),
        "gate-plan full 必须是非空有序 gate 列表",
    )
    repository.require(len(full) == len(set(full)), "gate-plan full 含重复成员")
    repository.require(
        core == "gate-core" and core in full, "gate-plan core 必须是 full 中的 gate-core"
    )
    repository.require(not (RESERVED & set(full)), "gate-plan/full 是保留入口，不能成为 full 成员")
    repository.require(
        isinstance(deferred, list)
        and all(
            isinstance(item, str) and re.fullmatch(r"gate-[A-Za-z0-9_-]+", item)
            for item in deferred
        )
        and len(deferred) == len(set(deferred)),
        "gate-plan defer_to_final 必须是唯一的 gate 列表",
    )
    invalid_deferred = set(deferred) - (set(full) - {core})
    repository.require(
        not invalid_deferred,
        "defer_to_final 只能包含 full 中的非 core 边界：" + ", ".join(sorted(invalid_deferred)),
    )
    recipes = set(recipes)
    repository.require(
        set(REQUIRED_RECIPES) <= recipes,
        "缺少 recipes：" + ", ".join(sorted(set(REQUIRED_RECIPES) - recipes)),
    )
    declared = set(full)
    available = {name for name in recipes if re.fullmatch(r"gate-[A-Za-z0-9_-]+", name)} - RESERVED
    repository.require(
        declared <= recipes, "gate-plan 含不存在 recipe：" + ", ".join(sorted(declared - recipes))
    )
    repository.require(
        available <= declared, "存在未登记 gate recipe：" + ", ".join(sorted(available - declared))
    )
    return {"core": core, "full": full, "defer_to_final": deferred}


def boundaries(plan):
    return [name for name in plan["full"] if name != plan["core"]]


def require_boundaries(plan, names):
    repository.require(
        isinstance(names, list)
        and len(names) == len(set(names))
        and all(isinstance(name, str) for name in names),
        "boundary gates 无效或重复",
    )
    missing = set(names) - set(boundaries(plan))
    repository.require(
        not missing, "boundary gates 不属于 gate-plan full：" + ", ".join(sorted(missing))
    )


def required_for_ticket(plan, names):
    """返回本票默认必须完整执行的 gates，顺序唯一取自 full。"""
    require_boundaries(plan, names)
    required = {plan["core"], *(set(names) - set(plan["defer_to_final"]))}
    return [name for name in plan["full"] if name in required]


def deferred_for_ticket(plan, names):
    """返回仍保留为最终覆盖义务的边界，顺序唯一取自 full。"""
    require_boundaries(plan, names)
    selected = set(names) & set(plan["defer_to_final"])
    return [name for name in plan["full"] if name in selected]

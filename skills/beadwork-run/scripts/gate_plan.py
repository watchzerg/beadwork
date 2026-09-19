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
        isinstance(value, dict) and set(value) == {"core", "full"},
        "gate-plan 只能包含 core 与 full",
    )
    core, full = value["core"], value["full"]
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
    return {"core": core, "full": full}


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

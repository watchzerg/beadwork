"""Ticket stage 追加额度的纯决策规则。"""

import workflow_policy


def ticket_models(number, complex_ticket, previous, facts):
    """授权扩展先选择默认或覆盖配置，再检查此前档位；恢复由调用方原样返回。"""
    roles = ("implementer", "standards", "spec")
    extended = number >= len(workflow_policy.STAGE_MODELS)
    catalog = workflow_policy.EXTENSION_MODEL_LEVELS if extended else workflow_policy.MODEL_LEVELS
    if extended:
        levels = (
            {role: 3 for role in roles}
            if facts.get("continuation") == "extend"
            else {role: catalog.index(previous[role]) for role in roles}
        )
    else:
        levels = dict(zip(roles, workflow_policy.STAGE_MODELS[number], strict=True))
        if complex_ticket:
            for role, floor in zip(roles, (1, 2, 2), strict=True):
                levels[role] = max(levels[role], floor)
        if previous:
            for role in roles:
                levels[role] = max(levels[role], catalog.index(previous[role]))
    overrides = facts.get("model_overrides", {})
    if not isinstance(overrides, dict) or not set(overrides) <= set(roles):
        raise ValueError("模型角色无效")
    if overrides:
        reason = facts.get("model_override_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError("模型覆盖需记录理由")
    for role, model in overrides.items():
        floor = (
            catalog.index(previous[role]) if facts.get("continuation") == "extend" else levels[role]
        )
        if model not in catalog or catalog.index(model) < floor:
            raise ValueError("模型只能升级；Astra 仅用于授权扩展阶段")
        levels[role] = catalog.index(model)
    return {role: catalog[level] for role, level in levels.items()}


def authorize_extension(previous, selected_stage, report, facts, stage_limit):
    """校验一次性追加授权，返回新上限和可持久化记录。"""
    default_limit = len(workflow_policy.STAGE_MODELS) - 1
    if stage_limit != default_limit or previous.get("stage_extension"):
        raise ValueError("每张 ticket 仅允许追加一次 stage")
    if "recovery_reason" in facts or "recovery_failure" in facts:
        raise ValueError("extend 不接受 recovery 字段")
    if (
        previous["stage"] != stage_limit
        or report["outcome"] != "code_failure"
        or not report["execution"]["stopped_tasks"]
    ):
        raise ValueError("只有已耗尽且任务已停止的 code_failure 可追加 stage")
    additional = facts.get("additional_stages")
    if type(additional) is not int or not 1 <= additional <= workflow_policy.MAX_STAGE_EXTENSION:
        raise ValueError("单次最多追加五个 stage")
    reason = facts.get("extension_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("追加 stage 需要用户授权原因")
    new_limit = stage_limit + additional
    return new_limit, {
        "version": 1,
        "kind": "authorized-stage-extension",
        "stage": previous["stage"],
        "selected_stage": selected_stage,
        "additional_stages": additional,
        "new_stage_limit": new_limit,
        "reason": reason.strip(),
    }

"""Ticket stage 追加额度的纯决策规则。"""

import workflow_policy


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

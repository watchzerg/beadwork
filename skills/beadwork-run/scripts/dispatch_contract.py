"""dispatch 路径、身份和计划来源契约；不推进工作流。"""

from pathlib import Path

import evidence
import repository
import workflow_contract
from repository import require


def validate_plan(d):
    if d.get("plan_source"):
        evidence.bound(d["plan_source"]["report"])
    for source in d.get("environment_evidence", []):
        evidence.bound(source)
    if d.get("ticket_scope") and d.get("expected_plan_path"):
        require(
            evidence.read(d["expected_plan_path"])
            == {"mode": d["test_mode"], "approved_seams": d["approved_seams"]},
            "执行计划文件与 dispatch 不符",
        )
    if not d.get("plan_adjustment"):
        return
    record = evidence.read(evidence.bound(d["plan_adjustment"]))
    previous = evidence.read(evidence.bound(record["dispatch"]))
    keys = ("repository_root", "worktree", "branch", "parent_id", "ticket_id", "base_commit")
    require(all(d.get(k) == previous.get(k) for k in keys), "计划调整属于其他 ticket 或 BASE")
    validate_plan(previous)
    recovery = record["recovery"]
    checkpoint = evidence.read(evidence.bound(recovery["checkpoint"]))
    require(
        checkpoint["state"]["stage_dispatch"] == record["dispatch"]
        and checkpoint["root"] == previous["ticket_root"],
        "计划适配检查点与原 stage 不符",
    )
    state = checkpoint["state"]
    selected = state["selected_stage"]
    for item in ([selected] if selected else []) + state["implementer_sources"]:
        for source in item.values():
            evidence.bound(source)
    for item in state["implementer_sources"]:
        closure = state.get("closures", {}).get(item["report"]["sha256"])
        if closure:
            evidence.bound(closure.get("closure_source", closure))
    for source in recovery["context_sources"]:
        context = evidence.read(evidence.bound(source))
        for item in context["sources"]:
            evidence.bound(item)
    require(
        record["original_plan"] == evidence.read(previous["expected_plan_path"]), "原执行计划已变化"
    )
    require(
        record["effective_plan"] == evidence.read(d["expected_plan_path"]),
        "实际执行计划与调整记录不符",
    )
    require(
        record["effective_plan"]["approved_seams"] == record["original_plan"]["approved_seams"],
        "计划调整不得改变 seam",
    )


def dispatch(path):
    p = evidence.absolute(path)
    d = evidence.read(p)
    workflow_contract.require_current(d)
    require(
        d["role"] in ("executor", "finalizer", "implementer", "fixer", "document-syncer"),
        "需要 executor、implementer 或 finalizer dispatch",
    )
    require(Path(d["dispatch_path"]) == p, "dispatch 路径不符")
    require(Path(d["report_path"]).parent == p.parent, "报告目录与 dispatch 不符")
    validate_plan(d)
    return d


def output_path(path, directory):
    p = evidence.absolute(path)
    require(p.parent == directory, "输出必须位于指定证据目录")
    require(not p.exists(), "证据文件已存在，请使用新文件名")
    return p


def same_ticket(a, b):
    keys = ("repository_root", "worktree", "branch", "parent_id", "ticket_id", "base_commit")
    require(all(a.get(k) == b.get(k) for k in keys), "来源不属于同票同 BASE")


def same_attempt(a, b):
    keys = ("repository_root", "worktree", "branch", "parent_id", "reviewed_main", "attempt_id")
    require(
        all(a.get(k) == b.get(k) for k in keys)
        and a["expected_children"] == b["expected_children"],
        "最终阶段不属于同一集成尝试",
    )


def verification_dispatch(path):
    p = evidence.absolute(path)
    d = evidence.read(p)
    workflow_contract.require_current(d)
    repository.require(
        d["role"] in ("executor", "implementer", "fixer", "finalizer", "document-syncer")
        and d["dispatch_path"] == str(p),
        "需要 executor 或 fixer dispatch",
    )
    repository.require(
        not d.get("ticket_scope") or d["role"] in ("implementer", "document-syncer"),
        "单票验证采集仅由 implementer 或文档收尾 writer 执行",
    )
    repository.require(Path(d["report_path"]).parent == p.parent, "dispatch 证据目录不符")
    return d

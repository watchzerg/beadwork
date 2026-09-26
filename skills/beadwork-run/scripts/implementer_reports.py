"""implementer 报告结构、运行事实与组装；不选择 writer 或推进阶段。"""

from pathlib import Path

import dispatch_contract
import draft_contracts
import evidence
import gate_repair
import repository
import ticket_verification
import verify_ticket as v


def implementer_schema():
    schema = v.executor_schema(v.axis_report_schema())
    schema["properties"].pop("review")
    schema["properties"].pop("execution")
    schema["properties"].pop("document_closeout")
    schema["required"].remove("review")
    schema.pop("allOf")
    schema["properties"].update(
        role={"const": "implementer"},
        ticket_id=v.TEXT,
        stage_base=v.SHA,
        stopped_tasks={"type": "boolean"},
        verification_notes={"type": "object", "additionalProperties": {"type": "string"}},
        verification_sources={"type": "array", "items": {"type": "object"}},
        verification_issues={"type": "array", "items": {"type": "object"}},
    )
    schema["required"] += [
        "role",
        "ticket_id",
        "stage",
        "outcome",
        "stage_base",
        "stopped_tasks",
        "verification_notes",
        "verification_sources",
        "verification_issues",
    ]
    return schema


def implementer_errors(report, d):
    errors = v.schema_errors(report, implementer_schema())
    if errors:
        return errors
    for key in ("ticket_id", "base_commit", "stage", "stage_base"):
        if report[key] != d.get(key):
            errors.append(key + " 与 dispatch 不符")
    if d.get("role") != "implementer" or d.get("ticket_scope") != "implementer":
        errors.append("需要 implementer dispatch")
    if report["outcome"] in ("code_failure", "interrupted") and report["status"] != "BLOCKED":
        errors.append("代码失败和中断必须为 BLOCKED")
    if (report["outcome"] == "passed") != (report["status"] == "DONE"):
        errors.append("implementer 状态与 outcome 不符")
    if report["status"] == "DONE":
        if (
            not report["acceptance"]
            or not report["verification"]
            or report["blockers"]
            or report["requested_context"]
            or not report["stopped_tasks"]
        ):
            errors.append("成功交付缺少证据或仍有阻塞/运行任务")
        plan = report["test_plan"]
        if not plan or (plan["mode"] == "TDD" and not plan["red_evidence"]):
            errors.append("成功交付缺少 test plan 或行为 red")
    elif not (report["blockers"] or report["requested_context"]):
        errors.append("未完成交付需要原因")
    if report["test_plan"] and {
        k: report["test_plan"][k] for k in ("mode", "approved_seams")
    } != evidence.read(d["expected_plan_path"]):
        errors.append("test plan 与执行计划不符")
    return errors


def check_implementation(d, report, live=False):
    dispatch_contract.validate_plan(d)
    snapshot = report.get("verification_sources")
    if live and snapshot is not None:
        repository.require(
            snapshot == ticket_verification.verification_snapshot(d),
            "实现交付须包含当前全部验证来源",
        )
    repository.require(isinstance(snapshot, list), "实现交付缺少验证来源快照")
    records, issues = ticket_verification.inspect(
        d, snapshot, report["verification_notes"], report["status"]
    )
    rows = [row[3] for row in records]
    runs = [(start, end, path) for start, end, path, _, _ in records if end is not None]
    repository.require(report.get("verification_issues") == issues, "实现验证问题与原始来源不符")
    repository.require(
        not issues
        or (report["status"] == "BLOCKED" and report["outcome"] in ("blocked", "interrupted")),
        "损坏验证来源只能交付 blocked/interrupted",
    )
    repository.require(
        report["verification"][: len(rows)] == rows, "implementer 丢失或改写验证历史"
    )
    head = report["head_commit"]
    repository.require(head, "实现报告需要当前 HEAD")
    repository.git(d["worktree"], "merge-base", "--is-ancestor", d["stage_base"], head)
    commits = repository.git(
        d["worktree"], "log", "--reverse", "--format=%H %s", d["base_commit"] + ".." + head
    ).splitlines()
    expected = [dict(zip(("sha", "subject"), line.split(" ", 1), strict=True)) for line in commits]
    repository.require(report["implementation_commits"] == expected, "实现提交列表不完整")
    repository.check_batch_beads(d["worktree"], d["base_commit"], head)
    if live:
        repository.topology(d)
        repository.require(repository.sha(d["worktree"], "HEAD") == head, "实现交付 HEAD 已变化")
        repository.require(
            not repository.git(
                d["worktree"], "status", "--porcelain=v1", "--untracked-files=all", "--", ".beads"
            ),
            ".beads 有改动",
        )
        if report["status"] == "DONE":
            repository.require(not repository.status(d["worktree"]), "实现通过需要干净现场")
    if report["status"] == "DONE":
        passed = ticket_verification.delivery_coverage(
            [(start, end) for start, end, *_ in records], head
        )
        repository.require("gate-core" in passed, "交付 HEAD 缺少成功 gate-core")
    if report["outcome"] == "code_failure":
        repository.require(
            gate_repair.used_repairs(gate_repair.root(d)) == 3, "代码 gate 失败必须先用尽三次修复"
        )
        repository.require(
            any(
                start.get("delivery_attempt") == 3
                and start["before"] == end["after"]
                and start["before"] == {"head": head, "status": ""}
                and end["outcome"] == "exited"
                and type(end["exit_code"]) is int
                and end["exit_code"] > 0
                and end["process_group_gone"] is True
                for start, end, _ in runs
            ),
            "缺少第三次修复后候选失败证据",
        )


def implementer_assemble(args):
    d = dispatch_contract.dispatch(args.dispatch)
    report = draft_contracts.read(d, args.draft, "implementer")
    report["verification_sources"] = ticket_verification.verification_snapshot(d)
    records, report["verification_issues"] = ticket_verification.inspect(
        d, report["verification_sources"], report["verification_notes"], report["status"]
    )
    repository.require(
        not report["verification_issues"]
        or (report["status"] == "BLOCKED" and report["outcome"] in ("blocked", "interrupted")),
        "验证来源损坏时只能交付 blocked/interrupted",
    )
    report["verification"] = [row[3] for row in records] + report["verification"]
    if report["test_plan"] is not None:
        repository.require(
            set(report["test_plan"]) == {"decision_source", "red_evidence"},
            "test_plan 只填写判断依据与 red 证据",
        )
        report["test_plan"] = {**evidence.read(d["expected_plan_path"]), **report["test_plan"]}
    head = repository.sha(d["worktree"], "HEAD")
    commits = repository.git(
        d["worktree"], "log", "--reverse", "--format=%H %s", d["base_commit"] + ".." + head
    )
    report.update(
        role="implementer",
        ticket_id=d["ticket_id"],
        stage=d["stage"],
        stage_base=d["stage_base"],
        base_commit=d["base_commit"],
        head_commit=head,
        implementation_commits=[
            dict(zip(("sha", "subject"), line.split(" ", 1), strict=True))
            for line in commits.splitlines()
        ],
        delivery_kind=("already_satisfied" if head == d["base_commit"] else "changed")
        if report["status"] == "DONE"
        else None,
    )
    output = dispatch_contract.output_path(args.output, Path(args.dispatch).parent)
    evidence.write(output, report)
    return str(output)

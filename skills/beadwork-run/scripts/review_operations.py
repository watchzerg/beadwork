"""ticket 与 final review 共用的 append-only 文件和双轴输入机制。"""

import uuid
from pathlib import Path

import dispatch_contract
import evidence
import final_state
import final_verification
import finalization
import gate_repair
import handoff
import report_io
import repository
import review_context
import review_evidence
import role_instructions
import ticket_execution
import ticket_state
import workflow_contract
from command_argv import beadwork_argv

AXES = review_evidence.AXES


def publish_or_match(path, value):
    path = Path(path)
    if path.exists():
        if evidence.read(path) != value:
            raise ValueError("review 准备半成品与当前身份不符")
    else:
        evidence.write(path, value)


require_axis_sources = review_evidence.require_axis_sources


def review_inputs(d, axis):
    writer = None
    prior = d.get("prior_reviews", [])
    if d.get("ticket_scope"):
        value, _, _ = ticket_state.checkpoints(d)
        writer = value["implementer_sources"][-1] if value["implementer_sources"] else None
    elif final_state.strict(d):
        _, final_selection = final_state.selected(d)
        writers = final_selection["fixes"] if d["stage"] else final_selection["documents"]
        writer = writers[-1] if writers else None
    previous_axis = None
    if prior:
        collection = evidence.read(evidence.bound(prior[-1]))
        previous_axis = collection["sources"][axis]
        for item in previous_axis.values():
            evidence.bound(item)
    if writer:
        for item in writer.values():
            evidence.bound(item)
        wd, report = (
            evidence.read(evidence.bound(writer["dispatch"])),
            evidence.read(evidence.bound(writer["report"])),
        )
        repository.require(
            wd["worktree"] == d["worktree"]
            and report["head_commit"] == repository.sha(d["worktree"], "HEAD"),
            "review writer 现场不符",
        )
    verification = list(report.get("verification_sources", [])) if writer else []
    if final_state.strict(d):
        verification += [s for s in final_verification.snapshot(d) if s not in verification]
    return {
        "writer_source": writer,
        "prior_axis_source": previous_axis,
        "plan_source": d.get("plan_source"),
        "plan_adjustment": d.get("plan_adjustment"),
        "expected_children": d.get("expected_children", []),
        "context_sources": handoff.contexts(d),
        "verification_sources": verification,
        "stage_source": evidence.binding(d["dispatch_path"]),
        "scope": "ticket" if d["role"] == "executor" else "batch",
    }


def reviewed_state(d, base, head):
    repository.topology(d)
    wt = d["worktree"]
    repository.require(repository.sha(wt, "HEAD") == head, "受审 HEAD 已变化")
    repository.require(repository.sha(wt, base) == base, "需要完整 BASE SHA")
    repository.git(wt, "merge-base", "--is-ancestor", base, head)
    repository.require(not repository.status(wt), "review 要求 worktree 干净")
    if not repository.git(wt, "diff", base + "..." + head):
        repository.require(base == head, "review diff 为空")
        if d["role"] == "executor":
            repository.require(
                evidence.read(d["expected_plan_path"])["mode"] == "direct_verification",
                "无提交完成需要 direct_verification",
            )


def prepare_review(args):
    d = dispatch_contract.dispatch(args.dispatch)
    ticket_review = bool(d.get("ticket_scope"))
    if ticket_review:
        repository.require(d.get("ticket_scope") == "stage", "review 由 stage executor 派发")
        ticket_execution.review_ready(d)
    if final_state.strict(d):
        finalization.review_ready(d)
    base = d["base_commit"] if d["role"] == "executor" else d["reviewed_main"]
    head = repository.sha(d["worktree"], "HEAD")
    reviewed_state(d, base, head)
    review_kind = "existing_behavior" if base == head else "change"
    acceptance_source = None
    if review_kind == "existing_behavior":
        repository.require(getattr(args, "evidence", None), "已有行为审查需要 acceptance 证据文件")
        acceptance_source = evidence.binding(args.evidence)
        entries = evidence.read(evidence.bound(acceptance_source))
        repository.require(
            isinstance(entries, list)
            and entries
            and all(
                isinstance(x, dict)
                and set(x) == {"criterion", "evidence"}
                and all(isinstance(v, str) and v.strip() for v in x.values())
                for x in entries
            ),
            "acceptance 证据无效",
        )
    if "stage" in d:
        gate_repair.freeze(d)
    directory = (
        final_state.reserve_review(d, getattr(args, "resume", False))
        if final_state.strict(d)
        else ticket_state.reserve_review(d, getattr(args, "resume", False))
        if ticket_review
        else evidence.absolute(args.dispatch).parent / ("review-" + uuid.uuid4().hex)
    )
    directory.mkdir(exist_ok=True)
    inputs = {axis: review_inputs(d, axis) for axis in AXES}
    verification = inputs[AXES[0]]["verification_sources"]
    repository.require(
        all(item["verification_sources"] == verification for item in inputs.values()),
        "review axes 验证来源不一致",
    )
    writer = inputs[AXES[0]]["writer_source"]
    notes = {}
    context_source = evidence.binding(d["dispatch_path"])
    if writer:
        context_source = writer["report"]
        notes = evidence.read(evidence.bound(writer["report"])).get("verification_notes", {})
    verification_view = review_context.publish(
        directory, verification, head, notes, context_source, publish_or_match
    )
    record = {
        "dispatch": evidence.binding(args.dispatch),
        "reviewed_base": base,
        "reviewed_head": head,
        "axes": {},
        "review_kind": review_kind,
        "acceptance_evidence": acceptance_source,
    }
    commits = repository.git(d["worktree"], "log", "--format=%H %s", base + ".." + head)
    for axis in AXES:
        folder = directory / axis
        folder.mkdir(exist_ok=True)
        identity = {
            "review_kind": review_kind,
            "acceptance_evidence": acceptance_source,
            "axis": axis,
            "reviewed_base": base,
            "reviewed_head": head,
            "skill_dir": d["skill_dir"],
            "worktree": d["worktree"],
            "rules_paths": d["rules_paths"],
            "parent_id": d["parent_id"],
            "ticket_id": d.get("ticket_id"),
            "test_mode": d.get("test_mode"),
            "linked_spec": d.get("linked_spec"),
            "dispatch_path": str(folder / "dispatch.json"),
            "report_path": str(folder / "report.json"),
            "report_schema_path": str(folder / "report-schema.json"),
            "receipt_schema_path": str(folder / "receipt-schema.json"),
            "commits": commits,
            "diff_argv": ["git", "-C", d["worktree"], "diff", base + "..." + head],
        }
        review_input = inputs[axis]
        review_input.pop("verification_sources")
        identity.update(review_input, verification_view_source=verification_view)
        identity["handoff_required"] = bool(d.get("preflight_acceptance")) or final_state.strict(d)
        if "stage" in d:
            identity.update(stage=d["stage"], **d["models"][axis])
        identity["self_check_argv"] = beadwork_argv(
            "verify",
            "worker",
            "--check-report",
            "reviewer",
            identity["report_path"],
            "--expected",
            identity["dispatch_path"],
            "--emit-receipt",
        )
        workflow_contract.stamp(identity)
        role_instructions.publish(identity, "reviewer")
        publish_or_match(identity["report_schema_path"], report_io.reviewer("--schema"))
        publish_or_match(identity["receipt_schema_path"], report_io.reviewer("--receipt-schema"))
        publish_or_match(identity["dispatch_path"], identity)
        record["axes"][axis] = evidence.binding(identity["dispatch_path"])
    path = directory / "round.json"
    publish_or_match(path, record)
    selection_path = directory / "selection-draft.json"
    publish_or_match(
        selection_path,
        {
            axis: {
                "report": str(directory / axis / "report.json"),
                "receipt": str(directory / axis / "receipt.json"),
                "observation": {
                    "task_id": "",
                    "stopped": False,
                    "observed_at": "",
                    "evidence": "",
                    "unresolved": [],
                },
            }
            for axis in AXES
        },
    )
    if final_state.strict(d):
        final_state.bind_round(d, path)
    if ticket_review:
        ticket_state.bind_review_round(d, path)
    return {
        "round_path": str(path),
        "selection_draft_path": str(selection_path),
        "axes": {axis: item["path"] for axis, item in record["axes"].items()},
        "reviewer_launch_context": workflow_contract.launch_context(identity),
    }


def collect_review(args):
    path = evidence.absolute(args.round)
    sources = evidence.read(evidence.absolute(args.input))
    repository.require(isinstance(sources, dict) and set(sources) == set(AXES), "需要两轴选择")
    record = evidence.read(path)
    for axis in AXES:
        selected = sources[axis]
        if "observation" in selected:
            repository.require(
                set(selected) == {"report", "receipt", "observation"}, "每轴选择观察或 closure"
            )
            closure = handoff.close(
                str(evidence.bound(record["axes"][axis])),
                selected["report"],
                selected.pop("observation"),
            )
            selected["closure"] = closure["closure_source"]["path"]
    record, d, pair, gate = review_evidence.pair_from_sources(path, sources)
    reviewed_state(d, record["reviewed_base"], record["reviewed_head"])
    result = {
        "round": evidence.binding(path),
        "sources": {
            axis: {key: evidence.binding(value) for key, value in sources[axis].items()}
            for axis in AXES
        },
        "pair": pair,
        "gate": gate,
        "repair_route": review_evidence.repair_route(pair),
    }
    output = dispatch_contract.output_path(args.output, path.parent)
    evidence.write(output, result)
    if d.get("ticket_scope"):
        ticket_state.select_review(d, output)
    if final_state.strict(d):
        final_state.select_review(d, output)
    return {"collection_path": str(output), "gate": gate, "repair_route": result["repair_route"]}

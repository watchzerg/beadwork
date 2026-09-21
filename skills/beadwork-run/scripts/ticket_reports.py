"""executor、阶段与整票报告组装及验收；不推进工作流。"""

import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import active_stage_context
import dispatch_contract
import draft_contracts
import evidence
import handoff
import implementer_reports
import report_io
import repository
import review_evidence
import ticket_state
import workflow_policy


def check_stage_report_core(d, report, *, review_checks=None):
    if report["status"] == "DONE":
        repository.require(
            report.get("delivery_kind") in ("changed", "already_satisfied"),
            "新契约完成报告需要 delivery_kind",
        )
    dispatch_contract.validate_plan(d)
    if "stage" not in d:
        return
    repository.require(
        report.get("stage") == d["stage"]
        and report.get("outcome") in ("passed", "code_failure", "interrupted", "blocked"),
        "报告阶段或 outcome 不符",
    )
    review = report.get("review")
    sources = review.get("sources", []) if review else []
    prior = d["prior_reviews"]
    repository.require(sources[: len(prior)] == prior, "报告丢失或改写前序 review")
    repository.require(
        len(sources) <= len(prior) + 1 and len(sources) <= d["stage"] + 1,
        "每阶段最多新增一轮 review",
    )
    if review:
        repository.require(
            "rounds" in review and len(sources) == len(review["rounds"]),
            "需要完整 review rounds 和来源",
        )
        for source, pair in zip(sources, review["rounds"], strict=True):
            path = evidence.bound(source)
            actual, _ = review_evidence.collection(
                str(path), d["dispatch_path"], verified=review_checks
            )
            repository.require(actual == pair, "报告轮次与原始 collection 不符")
        if len(sources) > len(prior):
            item = evidence.read(sources[-1]["path"])
            origin = evidence.read(
                evidence.bound(evidence.read(evidence.bound(item["round"]))["dispatch"])
            )
            repository.require(origin.get("stage") == d["stage"], "新增 review 不属于当前阶段")
    if len(sources) > len(prior) and review["gate"] == "BLOCKED":
        repository.require(
            report["outcome"] in ("code_failure", "blocked"),
            "完整 BLOCKED review 必须明确代码失败或非代码阻塞",
        )
    if report["outcome"] == "passed":
        repository.require(
            report["status"] == "DONE" and len(sources) == len(prior) + 1,
            "完成需要当前阶段的 review",
        )
    elif report["outcome"] == "code_failure":
        repository.require(report["status"] == "BLOCKED", "代码失败必须为 BLOCKED")
        if len(sources) > len(prior):
            repository.require(review["gate"] == "BLOCKED", "当前 review PASS 不能标为代码失败")
    else:
        repository.require(report["status"] != "DONE", "未完成阶段不能返回 DONE")


def check_stage_report(d, report):
    scope = d.get("ticket_scope")
    if scope == "root":
        return check_ticket(d, report)
    if scope == "stage":
        return check_stage(d, report)
    return check_stage_report_core(d, report)


def assemble(args):
    d = dispatch_contract.dispatch(args.dispatch)
    repository.require(d["role"] == "executor", "需要 executor dispatch")
    report = evidence.read(evidence.absolute(args.draft))
    fields = {
        "status",
        "test_plan",
        "acceptance",
        "verification",
        "requested_context",
        "blockers",
        "concerns",
    }
    notes = report.pop("verification_notes", {})
    outcome = report.pop("outcome", None)
    repository.require(set(report) == fields, "draft 仅提供原语义字段及可选 verification_notes")
    import ticket_verification as verification

    if not d.get("ticket_scope"):
        report["verification"] = (
            verification.collect(
                args.dispatch,
                list(
                    dict.fromkeys(d.get("verification_dispatches", []) + args.verification_dispatch)
                ),
                notes,
                report["status"],
            )
            + report["verification"]
        )
    else:
        repository.require(getattr(args, "report_extra", None), "阶段报告使用 ticket-assemble")
    if report["test_plan"] is not None:
        repository.require(
            set(report["test_plan"]) == {"decision_source", "red_evidence"},
            "draft test_plan 仅提供 decision_source 和 red_evidence",
        )
        report["test_plan"] = {**evidence.read(d["expected_plan_path"]), **report["test_plan"]}
    base, head = d["base_commit"], repository.sha(d["worktree"], "HEAD")
    commits = repository.git(
        d["worktree"], "log", "--reverse", "--format=%H %s", base + ".." + head
    )
    report.update(
        base_commit=base,
        head_commit=head,
        implementation_commits=[
            dict(zip(("sha", "subject"), line.split(" ", 1), strict=True))
            for line in commits.splitlines()
        ],
        review=None,
    )
    report["delivery_kind"] = (
        ("already_satisfied" if base == head else "changed") if report["status"] == "DONE" else None
    )
    if "stage" in d:
        repository.require(
            outcome in ("passed", "code_failure", "interrupted", "blocked"),
            "draft 必须明确 outcome",
        )
        report.update(stage=d["stage"], outcome=outcome)
    repository.require(
        len(args.review) <= d.get("stage_limit", len(workflow_policy.STAGE_MODELS) - 1) + 1,
        "review 轮数超过已授权 stage",
    )
    if args.review:
        rounds = [review_evidence.collection(path, args.dispatch) for path in args.review]
        review = {
            "attempts": len(rounds),
            "gate": rounds[-1][1],
            "final": rounds[-1][0],
            "rounds": [pair for pair, gate in rounds],
            "sources": [evidence.binding(path) for path in args.review],
        }
        if len(rounds) > 1:
            repository.require(
                all(gate == "BLOCKED" for _, gate in rounds[:-1]), "PASS 不进入修复复审"
            )
            review["initial"] = rounds[0][0]
        report["review"] = review
    report.update(getattr(args, "report_extra", {}))
    output = dispatch_contract.output_path(args.output, evidence.absolute(args.dispatch).parent)
    evidence.write(output, report)
    # 自检失败保留候选报告供诊断；更正使用新文件名。
    return check_report(args.dispatch, output)


def check_report(dispatch_path, report_path):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(d["role"] == "executor", "需要 executor dispatch")
    p = evidence.absolute(report_path)
    repository.require(
        p.parent == evidence.absolute(dispatch_path).parent, "报告必须位于本轮 dispatch 目录"
    )
    report = evidence.read(p)
    plan_d = check_stage_report(d, report) or d
    repository.topology(d)
    head = report["head_commit"] or repository.sha(d["worktree"], "HEAD")
    import verify_ticket

    checked = verify_ticket.check_delivery(
        d["worktree"],
        d["branch"],
        d["base_commit"],
        head,
        report["status"],
        str(p),
        plan_d["expected_plan_path"],
    )
    repository.require(
        checked.get("ok") is True,
        "executor 完整自检失败：" + json.dumps(checked, ensure_ascii=False),
    )
    return {
        "status": report["status"],
        "report_path": str(p),
        "report_sha256": checked["report_sha256"],
    }


def check_stage(d, report, *, state=None):
    state = ticket_state.checkpoints(d)[0] if state is None else state
    _check_stage(d, report, set(), state=state, review_checks=set())


def _check_stage(d, report, verified, *, state=None, review_checks=None):
    state = ticket_state.checkpoints(d)[0] if state is None else state
    review_checks = set() if review_checks is None else review_checks
    repository.require(d.get("ticket_scope") == "stage", "需要阶段 dispatch")
    execution = report.get("execution")
    repository.require(
        execution
        and execution["stage_dispatch"] == evidence.binding(d["dispatch_path"])
        and execution["root"] == d["ticket_root"],
        "阶段报告缺少绑定身份",
    )
    repository.require(execution["previous_stages"] == d["prior_stages"], "阶段报告丢失历史")
    # 仅复用本次调用内完整通过的相同内容；来源 hash/receipt 仍由调用方逐项核对。
    key = (
        d["dispatch_path"],
        *(
            hashlib.sha256(
                json.dumps(
                    value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                ).encode()
            ).hexdigest()
            for value in (d, report)
        ),
    )
    if key in verified:
        return
    default_limit = len(workflow_policy.STAGE_MODELS) - 1
    stage_limit = d.get("stage_limit", default_limit)
    repository.require(
        type(stage_limit) is int
        and default_limit <= stage_limit < workflow_policy.MAX_STAGES
        and type(d["stage"]) is int
        and 0 <= d["stage"] <= stage_limit,
        "stage 上限无效",
    )
    repository.require(
        d["stage"] > default_limit
        or (stage_limit == default_limit and not d.get("stage_extension")),
        "默认阶段不能预授追加额度",
    )
    if d["stage"] > default_limit:
        extension = evidence.read(evidence.bound(d.get("stage_extension")))
        additional = extension.get("additional_stages")
        repository.require(
            extension.get("kind") == "authorized-stage-extension"
            and len(d["prior_stages"]) > default_limit
            and extension.get("selected_stage") == d["prior_stages"][default_limit]
            and extension.get("stage") == default_limit
            and extension.get("new_stage_limit") == stage_limit
            and type(additional) is int
            and 1 <= additional <= workflow_policy.MAX_STAGE_EXTENSION
            and stage_limit == default_limit + additional
            and isinstance(extension.get("reason"), str)
            and extension["reason"].strip(),
            "追加 stage 缺少匹配的用户授权证据",
        )
    ticket_state.check_selected_review(
        d, (report.get("review") or {}).get("sources", []), state=state
    )
    recovery = (
        evidence.read(evidence.bound(d["stage_recovery"])) if d.get("stage_recovery") else None
    )
    recovered_stage = False
    previous = None
    for item in d["prior_stages"]:
        old, prior = ticket_state.resolve_source(item)
        dispatch_contract.same_ticket(d, old)
        repository.require(
            old["ticket_root"] == d["ticket_root"], "历史 stage 属于其他 ticket root"
        )
        repository.require(
            old["stage"] == (0 if previous is None else previous + 1), "历史 stage 不连续"
        )
        _check_stage(old, prior, verified, state=state, review_checks=review_checks)
        if prior["outcome"] != "code_failure":
            repository.require(
                recovery
                and not recovered_stage
                and prior["outcome"] == "blocked"
                and recovery["kind"] == "unregistered-gate-repair"
                and recovery["stage"] == old["stage"]
                and recovery["selected_stage"] == item
                and recovery["recovered_head"] == prior["head_commit"]
                and Path(evidence.bound(d["stage_recovery"])).parent
                == Path(old["dispatch_path"]).parent.parent,
                "历史非代码失败阶段缺少匹配的恢复证据",
            )
            recovered_stage = True
        previous = old["stage"]
    repository.require(not recovery or recovered_stage, "恢复证据未绑定历史阶段")
    repository.require(d["stage"] == (0 if previous is None else previous + 1), "stage 计数不符")
    repository.require(
        d["stage_base"]
        == (
            ticket_state.resolve_source(d["prior_stages"][-1])[1]["head_commit"]
            if d["prior_stages"]
            else d["base_commit"]
        ),
        "stage 起始 HEAD 与前序交付不符",
    )
    active_stage_context.check(d)
    sources = execution["implementers"]
    for item in sources:
        w, implementation = ticket_state.resolve_source(item)
        dispatch_contract.same_ticket(d, w)
        repository.require(w["ticket_root"] == d["ticket_root"], "实现来源属于其他 ticket root")
        repository.require(
            w["stage"] == d["stage"] and w["gate_repair_root"] == d["gate_repair_root"],
            "实现来源不属于本阶段",
        )
        report_io.implementer(
            "--check-report",
            item["report"]["path"],
            item["receipt"]["path"],
            "--expected",
            w["dispatch_path"],
        )
        implementer_reports.check_implementation(w, implementation, state=state)
        closure = state.get("closures", {}).get(item["report"]["sha256"])
        handoff.check_close(
            w["dispatch_path"],
            item["report"]["path"],
            closure,
            required=bool(w.get("preflight_acceptance")),
        )
    if sources:
        repository.require(
            implementation["head_commit"] == report["head_commit"], "阶段 HEAD 与最后实现交付不符"
        )
        repository.require(
            all(row in report["verification"] for row in implementation["verification"]),
            "阶段报告丢失实现验证",
        )
    new_review = len((report.get("review") or {}).get("sources", [])) > len(d["prior_reviews"])
    if new_review:
        repository.require(
            all(
                axis["reviewed_head"] == report["head_commit"]
                for axis in report["review"]["final"].values()
            ),
            "当前 review 未覆盖本阶段交付 HEAD",
        )
    if report["status"] == "DONE" or new_review:
        repository.require(
            sources and implementation["status"] == "DONE", "review/完成需要实现通过"
        )
    if sources and implementation["outcome"] == "code_failure" and not new_review:
        repository.require(
            report["outcome"] == "code_failure", "implementer 代码失败不能改报中断或外部阻塞"
        )
    if report["outcome"] == "code_failure" and not new_review:
        repository.require(
            sources and implementation["outcome"] == "code_failure",
            "缺少 implementer gate 失败交付",
        )
    if report["status"] == "DONE" or report["outcome"] == "code_failure":
        repository.require(execution["stopped_tasks"], "成功或阶段推进必须确认任务结束")
    check_stage_report_core(d, report, review_checks=review_checks)
    verified.add(key)


def check_ticket(d, report):
    repository.require(d.get("ticket_scope") == "root", "controller 只验收整票 root")
    state, _, _ = ticket_state.checkpoints(d)
    repository.require(state["selected_stage"], "整票没有已验收的阶段交付")
    stage, selected = ticket_state.resolve_source(state["selected_stage"])
    repository.require(selected == report, "root 报告必须原样引用选中的阶段报告")
    repository.require(
        state["stage_dispatch"] == evidence.binding(stage["dispatch_path"]), "选中阶段不是当前阶段"
    )
    repository.require(
        report["execution"]["implementers"] == state["implementer_sources"], "实现来源不完整"
    )
    check_stage(stage, report, state=state)
    if report["outcome"] == "code_failure":
        repository.require(
            stage["stage"] == stage.get("stage_limit", len(workflow_policy.STAGE_MODELS) - 1),
            "未耗尽 stage 的代码失败由 executor 内部处理",
        )
    return stage


def assemble_stage(args):
    d = dispatch_contract.dispatch(args.dispatch)
    state, _, _ = ticket_state.checkpoints(d)
    repository.require(state["stage_dispatch"] == evidence.binding(args.dispatch), "不是当前 stage")
    selected_reviews = d["prior_reviews"] + (
        [state["selected_review"]] if state["selected_review"] else []
    )
    review_paths = [str(evidence.bound(item)) for item in selected_reviews]
    ticket_state.check_selected_review(d, selected_reviews, state=state)
    report = draft_contracts.read(d, args.draft, "executor")
    stopped = report.pop("stopped_tasks")
    repository.require(type(stopped) is bool, "stopped_tasks 必须为布尔值")
    extra = {
        "execution": {
            "root": d["ticket_root"],
            "stage_dispatch": evidence.binding(args.dispatch),
            "previous_stages": d["prior_stages"],
            "implementers": state["implementer_sources"],
            "stopped_tasks": stopped,
        }
    }
    # 原组装器仍负责 Git、plan 与双轴原始证据；实现日志由已验收报告注入。
    verification = []
    for item in d["prior_stages"]:
        _, prior = ticket_state.resolve_source(item)
        verification += prior["verification"]
    for item in state["implementer_sources"]:
        _, implementation = ticket_state.resolve_source(item)
        verification += implementation["verification"]
    report["verification"] = list(
        {
            json.dumps(row, sort_keys=True): row for row in verification + report["verification"]
        }.values()
    )
    draft = Path(args.dispatch).parent / ("assembly-draft-" + uuid.uuid4().hex + ".json")
    evidence.write(draft, report)
    receipt = assemble(
        SimpleNamespace(
            dispatch=args.dispatch,
            draft=str(draft),
            output=args.output,
            review=review_paths,
            verification_dispatch=[],
            report_extra=extra,
        )
    )
    return d, state, receipt

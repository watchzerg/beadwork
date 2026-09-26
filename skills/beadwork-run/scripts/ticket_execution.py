"""单票阶段编排与交付选择；只写证据，不派发 agent。"""

import uuid
from pathlib import Path

import active_stage_context
import dispatch_contract
import document_closeout
import draft_contracts
import evidence
import gate_repair
import handoff
import implementer_reports
import report_io
import repository
import role_instructions
import stage_policy
import ticket_reports
import ticket_state
import ticket_verification
import workflow_contract
import workflow_policy
from command_argv import beadwork_argv

source = ticket_state.source
resolve_source = ticket_state.resolve_source
root = ticket_state.root
same_ticket = dispatch_contract.same_ticket
checkpoints = ticket_state.checkpoints
state_digest = ticket_state.state_digest
checkpoint = ticket_state.checkpoint


def root_fields(d):
    repository.require(
        not any(
            d.get(k)
            for k in ("previous_report", "previous_receipt", "continuation", "stage", "models")
        ),
        "controller 只准备整票；阶段输入由 ticket-stage 管理",
    )
    d.update(
        ticket_scope="root",
        start_head=d["base_commit"],
        coordinator_model=workflow_policy.MODEL_LEVELS[2 if d.get("complex_ticket") else 1],
    )


def resume_root(d):
    previous = evidence.read(evidence.absolute(d["previous_dispatch"]))
    repository.require(previous.get("ticket_scope") == "root", "恢复需要当前单票 root dispatch")
    import workflow_contract

    workflow_contract.launch_context(previous)
    same_ticket(previous, d)
    repository.topology(previous)
    repository.git(d["worktree"], "merge-base", "--is-ancestor", d["base_commit"], "HEAD")
    repository.require(
        d.get("continuation", "resume") == "resume",
        "controller 不推进 stage；使用原 root 恢复 executor",
    )
    state, _, _ = checkpoints(previous)
    if state["selected_stage"]:
        _, report = resolve_source(state["selected_stage"])
        repository.require(report["status"] != "DONE", "整票已完成，应验收关闭")
    return dict(previous, context_sources=handoff.contexts(previous))


def save_dispatch(d, folder, role):
    folder.mkdir(parents=True)
    d = dict(
        d,
        role=role,
        dispatch_path=str(folder / "dispatch.json"),
        report_path=str(folder / "report.json"),
        report_schema_path=str(folder / "report-schema.json"),
        receipt_schema_path=str(folder / "receipt-schema.json"),
    )
    if role == "implementer":
        for kind in ("schema", "receipt-schema"):
            evidence.write(
                d["report_schema_path" if kind == "schema" else "receipt_schema_path"],
                worker("--" + kind),
            )
        d["self_check_argv"] = beadwork_argv(
            "executor",
            "implementer-check",
            "--dispatch",
            d["dispatch_path"],
            "--report",
            d["report_path"],
        )
    else:
        evidence.write(d["report_schema_path"], report_io.verifier("executor", "--schema"))
        evidence.write(d["receipt_schema_path"], report_io.verifier("executor", "--receipt-schema"))
    draft_contracts.publish(d, role)
    evidence.write(d["dispatch_path"], d)
    return d


worker = report_io.implementer


def stage_result(d, state):
    dispatch_contract.validate_plan(d)
    selected = state["implementer_sources"][-1] if state["implementer_sources"] else None
    writer = evidence.read(evidence.bound(d["implementer_dispatch"]))
    active_stage_context.check(writer, validate_sources=True)
    return {
        "context_sources": handoff.contexts(d),
        "stage": d["stage"],
        "stage_dispatch": d["dispatch_path"],
        "implementer_dispatch": writer["dispatch_path"],
        "implementer_launch_context": workflow_contract.launch_context(writer),
        "active_stage_context_source": writer["active_stage_context_source"],
        "models": d["models"],
        "prior_implementer": selected,
        "selected_stage": state["selected_stage"],
        "selected_review": state["selected_review"],
        "document_closeout": document_closeout.selected(d),
        "review_round": state["review_round_path"],
        "review_started": (Path(d["gate_repair_root"]) / "gate-review-started.json").exists(),
    }


def recover_unregistered_gate_repair(previous, report, state, reason, recovery_failure=None):
    repository.require(
        report["outcome"] == "blocked" and report["execution"]["stopped_tasks"],
        "未登记 gate 修正恢复需要已停止的 blocked 阶段",
    )
    repository.require(
        isinstance(reason, str) and reason.strip(), "未登记 gate 修正恢复需要记录原因"
    )
    p = gate_repair.root(previous)
    repository.require(
        not state["selected_review"]
        and not (p / "gate-review-started.json").exists()
        and not any(x.is_dir() for x in p.glob("review-*")),
        "review 已开始，不能恢复未登记 gate 修正",
    )
    used = gate_repair.used_repairs(p)
    head = repository.sha(previous["worktree"], "HEAD")
    repository.require(
        not repository.status(previous["worktree"]) and head == report["head_commit"],
        "恢复需要报告绑定的干净 HEAD",
    )
    recovery = {
        "kind": "unregistered-gate-repair",
        "stage": previous["stage"],
        "selected_stage": state["selected_stage"],
        "recovered_head": head,
        "reason": reason.strip(),
    }
    if used:
        repository.require(recovery_failure is None, "已有 gate 修正候选时不接受 recovery_failure")
        candidate_path = gate_repair.repair_path(p, used, candidate=True)
        repository.require(candidate_path.exists(), "gate 修正候选尚未绑定")
        candidate = evidence.read(candidate_path)
        repository.require(head != candidate["head"], "恢复需要报告绑定的不同干净 HEAD")
        repository.git(previous["worktree"], "merge-base", "--is-ancestor", candidate["head"], head)
        recovery.update(
            gate_repair=evidence.binding(str(gate_repair.repair_path(p, used))),
            previous_candidate=evidence.binding(str(candidate_path)),
        )
    else:
        repository.require(
            recovery_failure, "没有可恢复的 gate 修正候选；首次未登记需提供 recovery_failure"
        )
        _, result_path, start, attempt = gate_repair.failure_source(previous, recovery_failure)
        repository.require(attempt == 0, "首次未登记恢复只接受原始 delivery candidate")
        failed_head = start["before"]["head"]
        repository.require(head != failed_head, "恢复需要报告绑定的不同干净 HEAD")
        recovery.update(
            failure={"path": str(result_path), "sha256": evidence.digest(result_path)},
            previous_head=failed_head,
        )
    target = p / "unregistered-gate-repair-recovery.json"
    gate_repair.record(target, recovery)
    return evidence.binding(str(target))


def prepare_stage(root_path, facts):
    r = dispatch_contract.dispatch(root_path)
    repository.require(r.get("ticket_scope") == "root", "ticket-stage 需要 executor root dispatch")
    repository.require(
        set(facts)
        <= {
            "continuation",
            "model_overrides",
            "model_override_reason",
            "recovery_reason",
            "recovery_failure",
            "additional_stages",
            "extension_reason",
        },
        "stage 输入字段无效",
    )
    repository.topology(r)
    state, _, _ = checkpoints(r)
    continuation = facts.get("continuation", "resume")
    repository.require(
        continuation in ("resume", "repair", "recover", "extend"), "continuation 无效"
    )
    previous = None
    recovery = None
    extension_record = None
    stage_limit = len(workflow_policy.STAGE_MODELS) - 1
    if state["stage_dispatch"]:
        previous = evidence.read(evidence.bound(state["stage_dispatch"]))
        if continuation == "resume":
            repository.require(
                not facts.get("model_overrides"),
                "已有 stage 沿用模型；提前升级在新 stage 准备时指定",
            )
            repository.require("recovery_reason" not in facts, "resume 不接受 recovery_reason")
            repository.require("recovery_failure" not in facts, "resume 不接受 recovery_failure")
            repository.require(
                not {"additional_stages", "extension_reason"}.intersection(facts),
                "resume 不接受额度扩展字段",
            )
            ticket_state.require_resumable(state)
            return stage_result(previous, state)
        repository.require(state["selected_stage"], "推进 stage 需要已验收的阶段报告")
        old, report = resolve_source(state["selected_stage"])
        check_stage(old, report)
        stage_limit = previous.get("stage_limit", stage_limit)
        if continuation == "repair":
            repository.require(
                report["outcome"] == "code_failure", "只有 code_failure 使用 repair 推进 stage"
            )
            repository.require(report["execution"]["stopped_tasks"], "旧任务未确认停止")
            repository.require("recovery_reason" not in facts, "repair 不接受 recovery_reason")
            repository.require("recovery_failure" not in facts, "repair 不接受 recovery_failure")
            repository.require(
                not {"additional_stages", "extension_reason"}.intersection(facts),
                "repair 不接受额度扩展字段",
            )
        elif continuation == "recover":
            repository.require(
                not {"additional_stages", "extension_reason"}.intersection(facts),
                "recover 不接受额度扩展字段",
            )
            recovery = recover_unregistered_gate_repair(
                previous, report, state, facts.get("recovery_reason"), facts.get("recovery_failure")
            )
        else:
            try:
                stage_limit, extension_record = stage_policy.authorize_extension(
                    previous, state["selected_stage"], report, facts, stage_limit
                )
            except ValueError as error:
                repository.require(False, str(error))
        number = previous["stage"] + 1
    else:
        repository.require(continuation == "resume", "初次 stage 只接受 resume")
        repository.require("recovery_reason" not in facts, "resume 不接受 recovery_reason")
        repository.require("recovery_failure" not in facts, "resume 不接受 recovery_failure")
        repository.require(
            not {"additional_stages", "extension_reason"}.intersection(facts),
            "resume 不接受额度扩展字段",
        )
        number = 0
    repository.require(number <= stage_limit, "stage 额度已用尽，停止并保留现场")
    if previous:
        state["stage_sources"] = state["stage_sources"] + [state["selected_stage"]]
    head = repository.sha(r["worktree"], "HEAD")
    if previous:
        repository.require(head == report["head_commit"], "阶段交付后 HEAD 已变化")
    else:
        repository.require(
            head == r["base_commit"] and not repository.status(r["worktree"]),
            "stage 0 需要原 BASE 的干净现场",
        )
    models = stage_policy.ticket_models(
        number, r.get("complex_ticket", False), previous["models"] if previous else None, facts
    )
    if extension_record:
        extension_record.update(
            models=models,
            model_overrides=facts.get("model_overrides", {}),
            model_override_reason=facts.get("model_override_reason"),
        )
    folder = Path(r["dispatch_path"]).parent / ("stage-" + str(number) + "-" + uuid.uuid4().hex)
    inherited = previous or r
    d = dict(
        inherited,
        ticket_scope="stage",
        ticket_root=evidence.binding(root_path),
        stage=number,
        stage_base=head,
        start_head=head,
        mode="resume",
        models=models,
        model_override_reason=facts.get("model_override_reason"),
        gate_repair_root=str(folder),
        prior_reviews=(report.get("review") or {}).get("sources", []) if previous else [],
        prior_stages=state["stage_sources"],
        previous_stage=state["selected_stage"],
        verification_dispatches=[],
        active_stage_context_source=None,
    )
    if recovery:
        d["stage_recovery"] = recovery
    if extension_record:
        if previous is None:
            raise ValueError("额度扩展缺少上一阶段")
        target = Path(previous["gate_repair_root"]) / "ticket-stage-extension.json"
        gate_repair.record(target, extension_record)
        d["stage_extension"] = evidence.binding(str(target))
        d["stage_limit"] = stage_limit
    d.pop("implementer_dispatch", None)
    folder.mkdir()
    if previous:
        d["active_stage_context_source"] = active_stage_context.publish(folder, d)
    else:
        active_stage_context.check(d)
    w = save_dispatch(dict(d, ticket_scope="implementer"), folder / "implementer", "implementer")
    d["implementer_dispatch"] = evidence.binding(w["dispatch_path"])
    d = save_dispatch(d, folder / "coordinator", "executor")
    new_state = dict(
        state,
        stage_dispatch=evidence.binding(d["dispatch_path"]),
        implementer_sources=[],
        selected_stage=None,
        selected_review=None,
        review_round_path=None,
        review_round=None,
    )
    checkpoint(r, new_state)
    return stage_result(d, new_state)


require_writer = ticket_state.require_writer
implementer_schema = implementer_reports.implementer_schema
implementer_errors = implementer_reports.implementer_errors
verification_snapshot = ticket_verification.verification_snapshot
collect_verification = ticket_verification.collect_verification
check_implementation = implementer_reports.check_implementation


def implementer_check(dispatch_path, report_path):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(d["role"] == "implementer", "需要 implementer dispatch")
    active_stage_context.check(d, validate_sources=True)
    repository.require(Path(report_path).parent == Path(dispatch_path).parent, "实现报告目录不符")
    checked = report_io.implementer("--check-report", report_path, "--expected", dispatch_path)
    report = evidence.read(report_path)
    implementer_reports.check_implementation(d, report, live=True)
    return {
        "status": report["status"],
        "report_path": str(report_path),
        "report_sha256": checked["report_sha256"],
    }


def implementer_assemble(args):
    output = implementer_reports.implementer_assemble(args)
    return implementer_check(args.dispatch, output)


def accept_implementer(stage_path, report_path, receipt_path, closure=None):
    d = dispatch_contract.dispatch(stage_path)
    state, _, _ = checkpoints(d)
    repository.require(state["stage_dispatch"] == evidence.binding(stage_path), "不是当前 stage")
    wpath = evidence.bound(d["implementer_dispatch"])
    item = source(wpath, report_path, receipt_path)
    w, report = resolve_source(item)
    implementer_check(str(wpath), report_path)
    handoff.check_close(
        str(wpath), report_path, closure, required=bool(d.get("preflight_acceptance"))
    )
    if report["status"] == "DONE" or report["outcome"] == "code_failure":
        repository.require(report["stopped_tasks"], "implementer 任务尚未停止")
    if state["implementer_sources"] and state["implementer_sources"][-1] == item:
        return {"accepted": True, "source": item}
    ticket_state.require_resumable(state)
    if state["implementer_sources"]:
        _, prior = resolve_source(state["implementer_sources"][-1])
        repository.require(
            prior["head_commit"] == report["head_commit"]
            or prior["outcome"] in ("interrupted", "blocked"),
            "实现已交付，报告更正不能改变 HEAD",
        )
        if prior["outcome"] in ("passed", "code_failure"):
            repository.require(
                report["outcome"] == prior["outcome"], "已验收实现终态不能改报中断或外部阻塞"
            )
    ticket_state.require_before_review(d, state)
    state.setdefault("closures", {})[item["report"]["sha256"]] = closure
    state["implementer_sources"].append(item)
    state["selected_stage"] = None
    checkpoint(d, state)
    return {"accepted": True, "source": item}


def review_ready(d):
    state, _, _ = checkpoints(d)
    repository.require(
        state["stage_dispatch"] == evidence.binding(d["dispatch_path"])
        and state["implementer_sources"],
        "review 需要当前 stage 已验收的 implementer",
    )
    w, report = resolve_source(state["implementer_sources"][-1])
    worker(
        "--check-report",
        state["implementer_sources"][-1]["report"]["path"],
        state["implementer_sources"][-1]["receipt"]["path"],
        "--expected",
        w["dispatch_path"],
    )
    check_implementation(w, report, live=True)
    repository.require(
        report["status"] == "DONE" and report["stopped_tasks"], "实现未通过，不能 review"
    )
    repository.require(
        state["review_round"] is None, "每 stage 只准备一轮 review；恢复使用原 round"
    )


reserve_review = ticket_state.reserve_review
bind_review_round = ticket_state.bind_review_round
select_review = ticket_state.select_review
check_selected_review = ticket_state.check_selected_review
check_stage = ticket_reports.check_stage
check_ticket = ticket_reports.check_ticket


def deliver(root_path, output):
    d = dispatch_contract.dispatch(root_path)
    state, _, _ = checkpoints(d)
    repository.require(state["selected_stage"], "需要先组装阶段报告")
    _, report = resolve_source(state["selected_stage"])
    check_ticket(d, report)
    target = dispatch_contract.output_path(output, Path(root_path).parent)
    evidence.write(target, Path(evidence.bound(state["selected_stage"]["report"])).read_text())
    return ticket_reports.check_report(root_path, str(target))


def adapt_plan(args):
    d = dispatch_contract.dispatch(args.dispatch)
    repository.require(d.get("ticket_scope") == "stage", "执行计划由当前 stage executor 核准")
    state, previous_checkpoint, _ = checkpoints(d)
    repository.require(
        state["stage_dispatch"] == evidence.binding(args.dispatch), "不是当前执行上下文"
    )
    ticket_state.require_writable(d, state)
    context_sources = handoff.contexts(d)
    if state["implementer_sources"]:
        item = state["implementer_sources"][-1]
        observation = handoff.check_close(
            item["dispatch"]["path"],
            item["report"]["path"],
            state.get("closures", {}).get(item["report"]["sha256"]),
            required=bool(d.get("preflight_acceptance")),
        )
        repository.require(
            observation is None or (observation["stopped"] and not observation["unresolved"]),
            "恢复计划适配需要派发者收尾观察确认旧任务停止",
        )
    for item in ([state["selected_stage"]] if state["selected_stage"] else []) + state[
        "implementer_sources"
    ][-1:]:
        _, report = resolve_source(item)
        repository.require(
            report.get("stopped_tasks", report.get("execution", {}).get("stopped_tasks")),
            "恢复计划适配前必须确认旧任务停止",
        )
        repository.require(
            not report["requested_context"] or context_sources,
            "恢复计划适配前需要 context-add 补齐事实来源",
        )
    adjusted = adapt_plan_dispatch(
        args, {"checkpoint": previous_checkpoint, "context_sources": context_sources}
    )
    old_writer = evidence.read(evidence.bound(d["implementer_dispatch"]))
    adjusted["verification_dispatches"] = []
    folder = Path(adjusted["dispatch_path"]).parent / "adapted"
    writer = dict(
        adjusted,
        ticket_scope="implementer",
        verification_dispatches=list(
            dict.fromkeys(
                old_writer.get("verification_dispatches", []) + [old_writer["dispatch_path"]]
            )
        ),
    )
    writer = save_dispatch(writer, folder / "implementer", "implementer")
    adjusted["implementer_dispatch"] = evidence.binding(writer["dispatch_path"])
    adjusted = save_dispatch(adjusted, folder / "coordinator", "executor")
    state.update(stage_dispatch=evidence.binding(adjusted["dispatch_path"]), selected_stage=None)
    checkpoint(d, state)
    return stage_result(adjusted, state)


def assemble_stage(args):
    d, state, receipt = ticket_reports.assemble_stage(args)
    receipt_path = Path(args.output).with_name(Path(args.output).stem + "-receipt.json")
    evidence.write(receipt_path, receipt)
    item = source(args.dispatch, args.output, receipt_path)
    state["selected_stage"] = item
    checkpoint(d, state)
    return receipt


def adapt_plan_dispatch(args, recovery):
    """记录已核准的执行计划；新单票由 ticket-adapt-plan 调用并更新检查点。"""
    d = dispatch_contract.dispatch(args.dispatch)
    repository.require(d["role"] == "executor", "需要 executor")
    if d.get("ticket_scope"):
        repository.require(
            d.get("ticket_scope") == "stage",
            "整票 root 不适配计划；由 executor 使用 ticket-adapt-plan 更新当前 stage",
        )
    repository.workspace(d)
    directory = Path(args.dispatch).parent
    facts = evidence.read(args.input)
    repository.require(
        set(facts) == {"reason", "acceptance", "verification", "mode"},
        "计划适配字段不符",
    )
    repository.require(
        isinstance(facts["reason"], str) and facts["reason"].strip(), "需要基线适配原因"
    )
    repository.require(facts["mode"] in ("TDD", "direct_verification"), "执行模式无效")
    old_plan = evidence.read(d["expected_plan_path"])
    repository.require(facts["mode"] != old_plan["mode"], "执行模式未变化")
    for key, fields in (
        ("acceptance", {"criterion", "evidence"}),
        ("verification", {"command", "result"}),
    ):
        repository.require(
            isinstance(facts[key], list)
            and facts[key]
            and all(
                isinstance(x, dict)
                and set(x) == fields
                and all(isinstance(v, str) and v.strip() for v in x.values())
                for x in facts[key]
            ),
            key + " 需要实测证据",
        )
    repository.require(
        facts["mode"] != "TDD" or bool(old_plan["approved_seams"]),
        "恢复 TDD 需要既有 approved seams",
    )
    target = directory.parent / uuid.uuid4().hex
    target.mkdir()
    record = {
        **facts,
        "kind": "execution-plan-adjustment",
        "dispatch": evidence.binding(args.dispatch),
        "base_commit": d["base_commit"],
        "observed_head": repository.sha(d["worktree"], "HEAD"),
        "original_plan": old_plan,
        "effective_plan": {**old_plan, "mode": facts["mode"]},
        "recovery": recovery,
    }
    evidence.write(target / "plan-adjustment.json", record)
    result = dict(
        d,
        mode="resume",
        dispatch_path=str(target / "dispatch.json"),
        report_path=str(target / "report.json"),
        report_schema_path=str(target / "report-schema.json"),
        receipt_schema_path=str(target / "receipt-schema.json"),
        expected_plan_path=str(target / "expected-plan.json"),
        test_mode=facts["mode"],
        plan_adjustment=evidence.binding(str(target / "plan-adjustment.json")),
        verification_dispatches=list(
            dict.fromkeys(d.get("verification_dispatches", []) + [args.dispatch])
        ),
    )
    # 保留 BASE、stage、models、prior_reviews；不是新的 writer 或阶段。
    evidence.write(result["expected_plan_path"], record["effective_plan"])
    evidence.write(result["report_schema_path"], report_io.verifier("executor", "--schema"))
    evidence.write(
        result["receipt_schema_path"], report_io.verifier("executor", "--receipt-schema")
    )
    role_instructions.publish(result)
    evidence.write(result["dispatch_path"], result)
    return result

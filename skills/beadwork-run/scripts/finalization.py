"""最终集成的阶段准备和证据校验；只写证据，源码和 Git 引用只读。"""

import uuid
from pathlib import Path

import dispatch_contract
import draft_contracts
import evidence
import final_state
import final_state as fs
import final_verification as fv
import fixer_reports
import gate_repair
import handoff
import report_io
import repository
import review_evidence
import workflow_policy
from command_argv import beadwork_argv

same_attempt = dispatch_contract.same_attempt


def prepare_attempt(d, head):
    prior = d["prior_finalization"]
    # 恢复身份只由显式选择的阶段来源继承。
    for key in ("attempt_id", "attempt_path", "resume_stage", "stage", "models"):
        d.pop(key, None)
    previous = None
    if prior and "stage_path" in prior:
        previous = evidence.read(prior["stage_path"])
        import workflow_contract

        workflow_contract.require_current(previous)
        repository.require(
            previous.get("role") == "finalizer" and "stage" in previous, "需要有效的最终阶段"
        )
        for key in ("repository_root", "worktree", "branch", "parent_id", "expected_children"):
            repository.require(previous[key] == d[key], "恢复批次身份变化")
        fs.selected(previous)
        changed_main = previous["reviewed_main"] != d["reviewed_main"]
        if not changed_main and not d.get("new_attempt_reason"):
            d.update(
                attempt_id=previous["attempt_id"],
                attempt_path=previous["attempt_path"],
                start_head=previous["start_head"],
                resume_stage=prior["stage_path"],
            )
            repository.git(
                d["worktree"], "merge-base", "--is-ancestor", previous["stage_base"], head
            )
            repository.require(
                not repository.status(d["worktree"]) or previous["stage"] > 0,
                "仅修复阶段可接续 dirty 现场",
            )
        else:
            repository.require(not repository.status(d["worktree"]), "新集成尝试必须从干净现场开始")
            d["historical_finalization"] = prior
            d["prior_finalization"] = None
    elif prior:
        raise ValueError("恢复需要当前阶段的 stage_path")
    else:
        repository.require(not repository.status(d["worktree"]), "首次最终验收需要干净现场")
    if "attempt_id" not in d:
        evidence_root = (
            Path(d["repository_root"]) / ".worktrees/.evidence" / d["parent_id"] / "final-review"
        )
        if not d.get("new_attempt_reason") and previous is None and not prior:
            for path in evidence_root.glob("*/stage-*/dispatch.json"):
                old = evidence.read(path)
                repository.require(
                    old.get("reviewed_main") != d["reviewed_main"],
                    "已有同基线最终阶段，重新调用须提供 prior_stage_path",
                )


def read_stage_report(stage, report_path, receipt_path):
    for path in (report_path, receipt_path):
        repository.require(
            Path(path).resolve().parent == Path(stage["dispatch_path"]).parent,
            "阶段报告必须位于原目录",
        )
    report_io.verifier(
        "finalizer",
        "--check-report",
        report_path,
        receipt_path,
        "--expected",
        stage["dispatch_path"],
    )
    report = evidence.read(report_path)
    check_report(stage, report)
    return report


def models(stage, previous, facts):
    levels = dict(
        zip(("fixer", "standards", "spec"), workflow_policy.FINAL_STAGE_MODELS[stage], strict=True)
    )
    if previous:
        for role, model in previous.get("models", {}).items():
            if role in levels:
                levels[role] = max(levels[role], workflow_policy.MODEL_LEVELS.index(model))
    changes = facts.get("model_overrides", {})
    repository.require(isinstance(changes, dict) and set(changes) <= set(levels), "模型角色无效")
    if changes:
        reason = facts.get("model_override_reason")
        repository.require(isinstance(reason, str) and reason.strip(), "模型升级需要理由")
        for role, model in changes.items():
            repository.require(
                model in workflow_policy.MODEL_LEVELS
                and workflow_policy.MODEL_LEVELS.index(model) >= levels[role],
                "模型不能降档",
            )
            levels[role] = workflow_policy.MODEL_LEVELS.index(model)
    return {role: workflow_policy.MODEL_LEVELS[level] for role, level in levels.items()}


def prepare_stage(dispatch_path, facts):
    root = dispatch_contract.dispatch(dispatch_path)
    repository.require(
        root["role"] == "finalizer" and "stage" not in root, "需要 finalizer root dispatch"
    )
    repository.topology(root)
    head = repository.sha(root["worktree"], "HEAD")
    repository.git(root["worktree"], "merge-base", "--is-ancestor", root["reviewed_main"], head)
    value, _, _ = fs.state(root)
    if value["current"] is not None:
        chosen = value["stages"][str(value["current"])]
        path = str(evidence.bound(chosen["dispatch"]))
        repository.require(
            not facts.get("previous_stage") or facts["previous_stage"] == path,
            "必须恢复当前最终阶段",
        )
        old = dispatch_contract.dispatch(path)
        if facts.get("continuation", "resume") == "resume":
            if chosen["report"]:
                prior = evidence.read(evidence.bound(chosen["report"]["report"]))
                repository.require(
                    prior["outcome"] in ("blocked", "interrupted"),
                    "已完成或代码失败阶段不能作为中断恢复",
                )
            return fs.result(old)
        repository.require(chosen["report"], "推进阶段需要明确选中的报告")
        facts = dict(
            facts,
            previous_stage=path,
            previous_report=str(evidence.bound(chosen["report"]["report"])),
            previous_receipt=str(evidence.bound(chosen["report"]["receipt"])),
        )
    elif root.get("prior_finalization"):
        repository.require(root.get("resume_stage"), "最终 attempt 缺少恢复阶段")
    previous_path = facts.get("previous_stage", root.get("resume_stage"))
    continuation = facts.get("continuation", "resume")
    repository.require(continuation in ("resume", "repair"), "continuation 必须为 resume 或 repair")
    sources = (
        resume_stage_sources(root, previous_path, facts, head, continuation)
        if previous_path
        else initial_stage_sources(root, dispatch_path, facts, head, continuation)
    )
    previous = sources["previous"]
    report = sources["report"]
    stage = sources["stage"]
    base = sources["base"]
    reviews = sources["reviews"]
    fixes = sources["fixes"]
    history = sources["history"]
    verification = sources["verification"]
    repository.require(
        0 <= stage < len(workflow_policy.FINAL_STAGE_MODELS), "六阶段已用尽，停止并保留现场"
    )
    repository.require(
        not repository.status(root["worktree"]) or stage > 0, "首次验收不能包含 dirty 现场"
    )
    repository.git(root["worktree"], "merge-base", "--is-ancestor", base, head)
    directory = Path(root["attempt_path"]) / ("stage-" + uuid.uuid4().hex)
    directory.mkdir()
    d = {
        **root,
        "stage": stage,
        "stage_base": base,
        "previous_stages": history,
        "prior_reviews": reviews,
        "prior_fixes": fixes,
        "prior_verification": verification,
        "models": models(stage, previous, facts),
        "dispatch_path": str(directory / "dispatch.json"),
        "report_path": str(directory / "report.json"),
        "report_schema_path": str(directory / "report-schema.json"),
        "receipt_schema_path": str(directory / "receipt-schema.json"),
        "previous_result": evidence.binding(facts["previous_report"]) if report else None,
        "previous_receipt": evidence.binding(facts["previous_receipt"]) if report else None,
    }
    gate_repair.inherit(d, previous)
    if facts.get("model_overrides"):
        d["model_override_reason"] = facts["model_override_reason"]
    evidence.write(d["report_schema_path"], report_io.verifier("finalizer", "--schema"))
    evidence.write(d["receipt_schema_path"], report_io.verifier("finalizer", "--receipt-schema"))
    draft_contracts.publish(d, "finalizer")
    evidence.write(d["dispatch_path"], d)
    # 已通过 fixer 的同阶段恢复只接续验证/review，不再派 writer。
    fixer_done = False
    for source in fixes:
        worker, result, _ = read_fixer(source, d)
        if (
            worker.get("stage", 1) == stage
            and result["status"] == "DONE"
            and result["head_commit"] == head
        ):
            fixer_done = True
    fixer_path = publish_fixer(d, previous, fixer_done)
    fs.start(d, fixer_path)
    return fs.result(d)


read_fixer = fixer_reports.read_fixer


def check_report(expected, report, *, review_checks=None):
    review_checks = set() if review_checks is None else review_checks
    import workflow_contract

    workflow_contract.require_current(expected)
    repository.require(
        report.get("attempt_id") == expected["attempt_id"] and report.get("stage_sources"),
        "缺少最终阶段身份或来源",
    )
    stages = [
        dispatch_contract.dispatch(str(evidence.bound(source)))
        for source in report["stage_sources"]
    ]
    d = stages[-1]
    same_attempt(expected, d)
    if fs.strict(expected):
        repository.require(fs.strict(d), "最终交付协议版本不符")
        fs.check_sources(d, report)
        fv.check(d, report)
        if "stage" not in expected:
            fs.check_delivery(expected, report)
    check_stage_history(expected, report, d, stages)
    reviews, fixes = report["review_sources"], report["fix_sources"]
    repository.require(reviews[: len(d["prior_reviews"])] == d["prior_reviews"], "丢失历史 review")
    repository.require(fixes[: len(d["prior_fixes"])] == d["prior_fixes"], "丢失历史 fixer 交付")
    historical_verification = d["prior_verification"]
    if fs.strict(d) and report.get("verification_issues"):
        unavailable_dirs = {
            Path(issue["dispatch"]["path"]).parent for issue in report["verification_issues"]
        }
        historical_verification = [
            v
            for v in historical_verification
            if Path(v["log_path"]).parent.parent not in unavailable_dirs
        ]
    repository.require(
        report["verification"][: len(historical_verification)] == historical_verification,
        "丢失历史验证",
    )
    check_review_history(d, report, reviews, review_checks=review_checks)
    code_failure_evidence = any(
        not item["passed"] and item["head_commit"] == report["head_commit"]
        for item in report["verification"][len(d["prior_verification"]) :]
    )
    if len(reviews) > len(d["prior_reviews"]):
        code_failure_evidence |= any(
            f["blocking"] for axis in report["review_rounds"][-1].values() for f in axis["findings"]
        )
    commits = []
    for source in fixes:
        fd, fr, fc = read_fixer(
            source, d, tolerate_verification=report["outcome"] in ("blocked", "interrupted")
        )
        if source not in d["prior_fixes"] and fr.get("outcome") == "code_failure":
            code_failure_evidence = True
            repository.require(report["outcome"] == "code_failure", "fixer 代码失败不能伪装成中断")
        for commit in fc:
            if commit not in commits:
                commits.append(commit)
        unavailable = any(
            issue["dispatch"] == source["dispatch"]
            for issue in report.get("verification_issues", [])
        )
        repository.require(
            unavailable or all(v in report["verification"] for v in fr["verification"]),
            "遗漏 fixer 验证",
        )
    if fs.strict(d) and report["outcome"] == "code_failure":
        new_blocking = len(reviews) > len(d["prior_reviews"]) and any(
            f["blocking"] for axis in report["review_rounds"][-1].values() for f in axis["findings"]
        )
        if not new_blocking:
            if d["stage"] == 0:
                rows = fv.check(d, report)
                code_failure_evidence = any(
                    row[-1]["gate"] == "gate-full"
                    and row[2].get("delivery") is True
                    and row[4]
                    and row[3]["exit_code"] > 0
                    and row[2]["dispatch_path"] == d["dispatch_path"]
                    and row[2]["before"]["head"] == report["head_commit"]
                    for row in rows
                )
            else:
                code_failure_evidence = bool(
                    fixes
                    and evidence.read(evidence.bound(fixes[-1]["dispatch"]))["stage"] == d["stage"]
                    and evidence.read(evidence.bound(fixes[-1]["report"]))["outcome"]
                    == "code_failure"
                )
    if report["outcome"] == "code_failure":
        repository.require(
            code_failure_evidence, "代码失败须有当前阶段失败验证或 blocking review/fixer 依据"
        )
    repository.require(report["fix"]["commits"] == commits, "最终 fix commits 与原始报告不符")
    if report["head_commit"]:
        actual = repository.git(
            d["worktree"], "rev-list", "--reverse", d["start_head"] + ".." + report["head_commit"]
        ).splitlines()
        repository.require(actual == commits, "集成后提交遗漏或超出修复来源")
    if report["outcome"] == "passed":
        repository.require(report["status"] == "READY_TO_MERGE", "passed 必须 READY_TO_MERGE")
        repository.require(
            reviews
            and report["review_rounds"][-1]["spec"]["reviewed_head"] == report["head_commit"],
            "最终 review 未覆盖 HEAD",
        )
    else:
        repository.require(report["status"] == "BLOCKED", "未通过必须 BLOCKED")


def assemble(dispatch_path, draft_path, output_path):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(fs.strict(d) and "stage" in d, "需要当前最终阶段 dispatch")
    _, selected = fs.selected(d)
    selected_reviews = list(d["prior_reviews"]) + (
        [selected["review"]] if selected["review"] else []
    )
    reviews = [str(evidence.bound(item)) for item in selected_reviews]
    fixes = selected["fixes"]
    r = draft_contracts.read(d, draft_path, "finalizer")
    review_checks = set()
    r["verification_notes"] = {**selected_verification_notes(d), **r.get("verification_notes", {})}
    head = repository.sha(d["worktree"], "HEAD")
    r.update(
        parent_id=d["parent_id"],
        expected_children=d["expected_children"],
        reviewed_main=d["reviewed_main"],
        start_head=d["start_head"],
        head_commit=head,
        stage=d["stage"],
        attempt_id=d["attempt_id"],
        stage_sources=d["previous_stages"] + [evidence.binding(dispatch_path)],
        review_sources=[evidence.binding(path) for path in reviews],
        fix_sources=fixes,
        review_rounds=[
            review_evidence.collection(path, dispatch_path, verified=review_checks)[0]
            for path in reviews
        ],
        workspace={
            "branch": d["branch"],
            "observed_head": head,
            "clean": not repository.status(d["worktree"]),
        },
    )
    current_verification = r["verification"]
    r["verification"] = list(d["prior_verification"])
    commits, dispositions = [], []
    for source in fixes:
        _, fr, fc = read_fixer(
            source, d, tolerate_verification=r["outcome"] in ("blocked", "interrupted")
        )
        commits += [commit for commit in fc if commit not in commits]
        dispositions += [item["source"] + "：" + item["action"] for item in fr["dispositions"]]
        for v in fr["verification"]:
            if v not in r["verification"]:
                r["verification"].append(v)
    r["verification"].extend(current_verification)
    r["fix"] = {"used": d["stage"] > 0, "commits": commits, "dispositions": dispositions}
    inherited = []
    for source in fixes:
        fr = evidence.read(evidence.bound(source["report"]))
        inherited += [s for s in fr["verification_sources"] if s not in inherited]
        r.setdefault("verification_notes", {}).update(fr.get("verification_notes", {}))
    if d.get("previous_result"):
        prior = evidence.read(evidence.bound(d["previous_result"]))
        inherited = prior["verification_sources"] + [
            s for s in inherited if s not in prior["verification_sources"]
        ]
        r.setdefault("verification_notes", {}).update(prior.get("verification_notes", {}))
    fv.populate(d, r, inherited)
    check_report(d, r, review_checks=review_checks)
    output = dispatch_contract.output_path(output_path, Path(dispatch_path).parent)
    evidence.write(output, r)
    checked = report_io.verifier("finalizer", "--check-report", output, "--expected", dispatch_path)
    result = {
        "status": r["status"],
        "report_path": str(output),
        "report_sha256": checked["report_sha256"],
    }
    receipt_path = output.parent / ("result-" + uuid.uuid4().hex + ".json")
    evidence.write(receipt_path, result)
    fs.select_report(d, output, receipt_path)
    return result


require_writer = final_state.require_writer
fixer_check = fixer_reports.fixer_check
fixer_assemble = fixer_reports.fixer_assemble


def accept_fixer(stage_path, report_path, receipt_path, closure=None):
    d = dispatch_contract.dispatch(stage_path)
    value, item = fs.selected(d)
    repository.require(item["fixer"], "本阶段没有 fixer")
    path = str(evidence.bound(item["fixer"]))
    fixer_check(path, report_path, receipt_path)
    handoff.check_close(path, report_path, closure)
    source = {
        k: evidence.binding(str(p))
        for k, p in (("dispatch", path), ("report", report_path), ("receipt", receipt_path))
    }
    if source in item["fixes"]:
        return {"accepted": True, "source": source}
    repository.require(not item["round_path"], "review 后不能重新选择 fixer")
    r = evidence.read(report_path)
    if item["fixes"] and item["fixes"][-1]["dispatch"] == item["fixer"]:
        prior = evidence.read(evidence.bound(item["fixes"][-1]["report"]))
        if prior["outcome"] in ("passed", "code_failure"):
            repository.require(
                prior["head_commit"] == r["head_commit"] and prior["outcome"] == r["outcome"],
                "fixer 终态不能改报中断或改变 HEAD",
            )
    item["fixes"].append(source)
    item["closures"][source["report"]["sha256"]] = closure
    item["report"] = None
    fs.save(d, value)
    return {"accepted": True, "source": source}


def selected_verification_notes(d):
    """只读取本阶段已选报告的绑定来源；不从目录扫描收尾说明。"""
    _, item = fs.selected(d)
    source = item.get("verification_notes_source") or (
        item["report"]["report"] if item["report"] else None
    )
    if not source:
        return {}
    report = evidence.read(evidence.bound(source))
    repository.require(
        report["stage_sources"][-1] == evidence.binding(d["dispatch_path"]),
        "收尾说明不属于当前阶段",
    )
    # 原报告已经过组装验收；当前运行仍由 populate/check 核对，允许损坏日志形成新的 BLOCKED。
    return dict(report.get("verification_notes", {})) if report["stopped_tasks"] else {}


def review_ready(d):
    _, item = fs.selected(d)
    repository.require(item["round"] is None, "本阶段已有 review；复用原 round")
    head = repository.sha(d["worktree"], "HEAD")
    if d["stage"]:
        repository.require(item["fixes"], "review 需要已验收 fixer")
        source = item["fixes"][-1]
        fd, report, _ = read_fixer(source, d)
        repository.require(
            fd["stage"] == d["stage"]
            and report["status"] == "DONE"
            and report["head_commit"] == head,
            "当前 fixer 未通过或 HEAD 不符",
        )
    # 同 HEAD 的 finalizer 补充验证与 fixer 验证共同形成覆盖。
    r = {
        "status": "READY_TO_MERGE",
        "outcome": "passed",
        "head_commit": head,
        "stage_sources": d["previous_stages"] + [evidence.binding(d["dispatch_path"])],
        "fix_sources": item["fixes"],
        "verification_notes": selected_verification_notes(d),
    }
    inherited = []
    for source in item["fixes"]:
        fr = evidence.read(evidence.bound(source["report"]))
        inherited += [s for s in fr["verification_sources"] if s not in inherited]
        r["verification_notes"].update(fr.get("verification_notes", {}))
    fv.populate(d, r, inherited)
    fv.check(d, r, live=True)


def deliver(root_path, output):
    root = dispatch_contract.dispatch(root_path)
    repository.require(fs.strict(root) and "stage" not in root, "final-deliver 需要 root dispatch")
    value, _, _ = fs.state(root)
    repository.require(value["current"] is not None, "尚无最终阶段")
    source = value["stages"][str(value["current"])]["report"]
    repository.require(source, "尚无已选阶段报告")
    report = evidence.bound(source["report"])
    stage = dispatch_contract.dispatch(str(evidence.bound(source["dispatch"])))
    read_stage_report(stage, str(report), str(evidence.bound(source["receipt"])))
    r = evidence.read(report)
    repository.require(
        r["outcome"] != "code_failure" or r["stage"] == len(workflow_policy.FINAL_STAGE_MODELS) - 1,
        "代码失败需在六阶段用尽后交付 controller",
    )
    check_report(root, r)
    repository.require(
        repository.sha(root["worktree"], "HEAD") == r["head_commit"], "交付 HEAD 已变化"
    )
    target = dispatch_contract.output_path(output, Path(root_path).parent)
    target.write_bytes(report.read_bytes())
    receipt = {
        "status": r["status"],
        "report_path": str(target),
        "report_sha256": evidence.digest(target),
    }
    receipt_path = target.with_name(target.stem + "-receipt.json")
    evidence.write(receipt_path, receipt)
    inspect_delivery(root_path, str(target), str(receipt_path))
    return receipt


def inspect_delivery(dispatch_path, report_path, receipt_path):
    """最终交付与 controller 共用的完整只读验收，保留原检查顺序。"""
    d, r, result = report_io.inspect_report(dispatch_path, report_path, receipt_path)
    check_report(d, r)
    repository.topology(d)
    wt = d["worktree"]
    head = repository.sha(wt, "HEAD")
    repository.require(r["head_commit"] is None or head == r["head_commit"], "实际 HEAD 与报告不符")
    repository.git(wt, "merge-base", "--is-ancestor", d["start_head"], head)
    repository.check_batch_beads(wt, d["reviewed_main"], head)
    repository.require(
        not repository.git(wt, "status", "--porcelain=v1", "--untracked-files=no", "--", ".beads"),
        ".beads 有未提交改动",
    )
    if r["status"] == "READY_TO_MERGE":
        repository.require(not repository.status(wt), "最终 implementation worktree 必须干净")
        repository.git(wt, "merge-base", "--is-ancestor", d["reviewed_main"], head)
    repository.require(
        evidence.digest(report_path) == result["report_sha256"], "验收期间报告发生变化"
    )
    return d, r, result


def resume_stage_sources(root, previous_path, facts, head, continuation):
    previous = report = None
    stage, base, reviews, fixes, history = 0, head, [], [], []
    verification = []
    previous = dispatch_contract.dispatch(previous_path)
    same_attempt(root, previous)
    for path in Path(root["attempt_path"]).glob("stage-*/dispatch.json"):
        later = evidence.read(path)
        repository.require(
            not any(
                source["path"] == str(previous_path) for source in later.get("previous_stages", [])
            ),
            "已有后续阶段，必须从最近 dispatch 恢复",
        )
    stage, base = previous["stage"], previous["stage_base"]
    history = previous["previous_stages"] + [evidence.binding(previous_path)]
    reviews, fixes = previous["prior_reviews"], previous["prior_fixes"]
    verification = previous["prior_verification"]
    repository.require(
        bool(facts.get("previous_report")) == bool(facts.get("previous_receipt")),
        "报告和回执须成对提供",
    )
    if facts.get("previous_report"):
        report = read_stage_report(previous, facts["previous_report"], facts["previous_receipt"])
        repository.require(report["stopped_tasks"], "前阶段任务未确认停止")
        repository.require(report["status"] != "READY_TO_MERGE", "已通过阶段应交付 controller")
        if report["head_commit"]:
            repository.require(head == report["head_commit"], "阶段交接 HEAD 已变化")
        reviews, fixes = report["review_sources"], report["fix_sources"]
        verification = report["verification"]
    else:
        repository.require(
            not list(Path(previous_path).parent.glob("result-*.json")),
            "已有阶段结果，必须显式选择报告和回执",
        )
    if continuation == "repair":
        repository.require(
            report is not None and report["outcome"] == "code_failure",
            "下一修复阶段需要 code_failure 证据",
        )
        stage += 1
        base = head
    elif report:
        repository.require(
            report["outcome"] in ("interrupted", "blocked"), "代码失败必须进入下一阶段"
        )
    return {
        "previous": previous,
        "report": report,
        "stage": stage,
        "base": base,
        "reviews": reviews,
        "fixes": fixes,
        "history": history,
        "verification": verification,
    }


def initial_stage_sources(root, dispatch_path, facts, head, continuation):
    previous = report = None
    stage, base, reviews, fixes, history = 0, head, [], [], []
    verification = []
    repository.require(
        not list(Path(root["attempt_path"]).glob("stage-*/dispatch.json")),
        "已有阶段，不能重新从阶段 0 开始",
    )
    repository.require(continuation == "resume", "首次验收不能跳过阶段 0")
    return {
        "previous": previous,
        "report": report,
        "stage": stage,
        "base": base,
        "reviews": reviews,
        "fixes": fixes,
        "history": history,
        "verification": verification,
    }


def publish_fixer(d, previous, fixer_done):
    fixer_path = None
    if d["stage"] > 0 and not fixer_done:
        folder = Path(d["dispatch_path"]).parent / "fixer"
        folder.mkdir()
        fd = {
            **d,
            "role": "fixer",
            "base_commit": d["stage_base"],
            "stage_dispatch": evidence.binding(d["dispatch_path"]),
            "model": d["models"]["fixer"]["model"],
            "reasoning_effort": d["models"]["fixer"]["reasoning_effort"],
            "resume": bool(previous and previous["stage"] == d["stage"]),
            "dispatch_path": str(folder / "dispatch.json"),
            "report_path": str(folder / "report.json"),
            "report_schema_path": str(folder / "report-schema.json"),
            "receipt_schema_path": str(folder / "receipt-schema.json"),
        }
        for name, flag in (
            ("report_schema_path", "--schema"),
            ("receipt_schema_path", "--receipt-schema"),
        ):
            evidence.write(fd[name], report_io.fixer(flag))
        fd["self_check_argv"] = beadwork_argv(
            "executor",
            "fixer-check",
            "--dispatch",
            fd["dispatch_path"],
            "--report",
            fd["report_path"],
        )
        draft_contracts.publish(fd, "fixer")
        evidence.write(fd["dispatch_path"], fd)
        fixer_path = fd["dispatch_path"]
    return fixer_path


def check_stage_history(expected, report, d, stages):
    repository.require(report["stage"] == d["stage"], "阶段编号不符")
    if "stage" in expected:
        repository.require(expected["dispatch_path"] == d["dispatch_path"], "报告不属于指定阶段")
    repository.require(d["previous_stages"] == report["stage_sources"][:-1], "阶段历史丢失或重排")
    for index, current in enumerate(stages):
        same_attempt(expected, current)
        repository.require(
            current["previous_stages"] == report["stage_sources"][:index], "阶段历史链不完整"
        )
    for a, b in zip(stages, stages[1:], strict=False):
        repository.require(b["stage"] in (a["stage"], a["stage"] + 1), "阶段跳跃或重置")
        if b.get("previous_result"):
            previous_report = str(evidence.bound(b["previous_result"]))
            previous_receipt = str(evidence.bound(b["previous_receipt"]))
            report_io.verifier(
                "finalizer",
                "--check-report",
                previous_report,
                previous_receipt,
                "--expected",
                a["dispatch_path"],
            )
            prior = evidence.read(previous_report)
            repository.require(prior["stopped_tasks"], "历史任务未确认停止")
            repository.require(
                b["prior_reviews"] == prior["review_sources"]
                and b["prior_fixes"] == prior["fix_sources"],
                "阶段交接丢失报告来源",
            )
            repository.require(
                prior["outcome"] == "code_failure"
                if b["stage"] > a["stage"]
                else prior["outcome"] in ("blocked", "interrupted"),
                "阶段交接结果不符",
            )
            if b["stage"] > a["stage"]:
                repository.require(b["stage_base"] == prior["head_commit"], "新修复阶段 BASE 不符")
        else:
            repository.require(
                b["stage"] == a["stage"]
                and b["prior_reviews"] == a["prior_reviews"]
                and b["prior_fixes"] == a["prior_fixes"],
                "无结果恢复不能推进或重写历史",
            )
        if b["stage"] == a["stage"]:
            repository.require(b["stage_base"] == a["stage_base"], "同阶段恢复改变 BASE")


def check_review_history(d, report, reviews, *, review_checks=None):
    repository.require(
        len(reviews) == len(report["review_rounds"]) <= len(workflow_policy.FINAL_STAGE_MODELS),
        "review 历史数量不符",
    )
    repository.require(len(reviews) <= len(d["prior_reviews"]) + 1, "每阶段最多新增一轮 review")
    previous_head = d["reviewed_main"]
    previous_review_stage = -1
    for index, (source, pair) in enumerate(zip(reviews, report["review_rounds"], strict=True)):
        actual, gate = review_evidence.collection(
            str(evidence.bound(source)), d["dispatch_path"], verified=review_checks
        )
        repository.require(actual == pair, "review 与原始来源不符")
        head = pair["spec"]["reviewed_head"]
        repository.git(d["worktree"], "merge-base", "--is-ancestor", previous_head, head)
        repository.require(head != previous_head or index == 0, "review HEAD 重复")
        previous_head = head
        collection = evidence.read(evidence.bound(source))
        origin = evidence.read(
            evidence.bound(evidence.read(evidence.bound(collection["round"]))["dispatch"])
        )
        review_stage = origin.get("stage", index)
        repository.require(
            previous_review_stage < review_stage <= d["stage"], "同阶段重复 review 或阶段顺序不符"
        )
        previous_review_stage = review_stage
    if len(reviews) > len(d["prior_reviews"]):
        item = evidence.read(evidence.bound(reviews[-1]))
        origin = evidence.read(
            evidence.bound(evidence.read(evidence.bound(item["round"]))["dispatch"])
        )
        repository.require(origin.get("stage") == d["stage"], "新增 review 不属于当前阶段")
        if any(
            f["blocking"] for axis in report["review_rounds"][-1].values() for f in axis["findings"]
        ):
            repository.require(
                report["outcome"] in ("code_failure", "blocked"),
                "完整 BLOCKED review 必须明确代码失败或非代码阻塞",
            )

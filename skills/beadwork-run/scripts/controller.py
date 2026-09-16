#!/usr/bin/env python3
"""controller 的确定性操作；用 --help 查看入口。只使用标准库。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
import evidence

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return evidence.read(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        handle.write(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run(args, cwd=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True, text=True)
    require(result.returncode == 0, f"命令失败 {args[0]} {args[1:]}：{result.stderr.strip()}")
    return result.stdout.rstrip("\n")


def git(root, *args):
    return run(["git", "-C", root, *args])


def status(root):
    return git(root, "status", "--porcelain=v1", "--untracked-files=all")


def sha(root, ref):
    result = git(root, "rev-parse", "--verify", ref)
    require(re.fullmatch(r"[0-9a-f]{40}", result), "需要完整 commit SHA")
    require(git(root, "cat-file", "-t", result) == "commit", "引用必须指向 commit")
    return result


def primary(root):
    entries = git(root, "worktree", "list", "--porcelain").split("\n\n")
    matches = [entry.splitlines()[0][9:] for entry in entries if "branch refs/heads/main" in entry.splitlines()]
    require(len(matches) == 1, "必须有唯一 checkout main 的 primary worktree")
    return str(Path(matches[0]).resolve())


def topology(d, allow_missing=False):
    root = d["repository_root"]
    require(primary(root) == root, "primary worktree 已变化")
    expected = Path(root) / ".worktrees" / d["parent_id"]
    require(Path(d["worktree"]) == expected, "worktree 不符合固定布局")
    require(d["branch"] == "implement/" + d["parent_id"], "branch 不符合固定布局")
    if allow_missing and not expected.exists():
        return
    require(str(expected.resolve()) == str(expected), "worktree 路径不能经过 symlink")
    require(git(expected, "rev-parse", "--show-toplevel") == str(expected), "目标不是预期 worktree")
    require(git(expected, "symbolic-ref", "--short", "HEAD") == d["branch"], "implementation branch 不符")
    require(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir") == git(expected, "rev-parse", "--path-format=absolute", "--git-common-dir"), "worktree 不属于同一仓库")


def verifier(role, option, *args, cwd=None):
    script = "verify-ticket.py" if role == "executor" else "verify-phase.py"
    command = [sys.executable, "-B", SCRIPTS / script, option]
    if role != "executor":
        command.append(role)
    output = json.loads(run(command + list(args), cwd))
    if option == "--check-report":
        require(output.get("ok") is True, "报告校验失败：" + json.dumps(output, ensure_ascii=False))
    return output


# 阶段 0 为首次实现，1..3 为修复；矩阵是派发模型的单一来源。
MODEL_LEVELS = [
    {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
    {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
    {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
    {"model": "gpt-6-astra", "reasoning_effort": "medium"},
]
STAGE_MODELS = [(0, 0, 2), (1, 0, 2), (2, 1, 2), (3, 2, 3)]
FINAL_STAGE_MODELS = [(2, 1, 2), (2, 1, 2), (2, 2, 2), (3, 2, 3)]
MODEL_ROLES = ("executor", "standards", "spec")


def executor_ops():
    spec = importlib.util.spec_from_file_location("executor_operations", SCRIPTS / "executor-operations.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_stage(d, head):
    previous = None
    report = None
    stage = 0
    prior_reviews = []
    continuation = d.get("continuation", "resume")
    require(continuation in ("resume", "repair"), "continuation 必须为 resume 或 repair")
    if d["mode"] == "new":
        require(not any(d.get(k) for k in ("previous_dispatch", "previous_report", "previous_receipt"))
                and continuation == "resume", "新票不能携带恢复输入")
    else:
        require(d.get("previous_dispatch"), "恢复必须提供前次 dispatch")
        previous = read(d["previous_dispatch"])
        keys = ("repository_root", "worktree", "branch", "parent_id", "ticket_id", "base_commit")
        require(previous.get("role") == "executor" and all(previous.get(k) == d[k] for k in keys),
                "前次 dispatch 不属于同票同 BASE")
        require(previous.get("dispatch_path") == str(Path(d["previous_dispatch"]).resolve()), "前次 dispatch 路径不符")
        require(bool(d.get("previous_report")) == bool(d.get("previous_receipt")), "前次报告和回执必须成对提供")
        if d.get("previous_report"):
            for key in ("previous_report", "previous_receipt"):
                require(Path(d[key]).resolve().parent == Path(d["previous_dispatch"]).resolve().parent,
                        "前次报告和回执必须位于原 dispatch 目录")
            verifier("executor", "--check-report", d["previous_report"], d["previous_receipt"])
            report = read(d["previous_report"])
            require(report["base_commit"] in (None, d["base_commit"]), "前次报告 BASE 不符")
            if report["head_commit"]:
                git(d["worktree"], "merge-base", "--is-ancestor", report["head_commit"], head)
            require(report["status"] != "DONE", "已完成报告应验收关闭，不再派发 writer")
        if "stage" in previous:
            stage = previous["stage"]
            prior_reviews = previous["prior_reviews"]
            if report:
                check_stage_report(previous, report)
                prior_reviews = (report.get("review") or {}).get("sources", [])
            if continuation == "repair":
                require(report is not None and report["outcome"] == "code_failure",
                        "下一修复阶段需要前阶段 code_failure 报告")
                stage += 1
            elif report:
                require(len(prior_reviews) == len(previous["prior_reviews"]),
                        "本阶段已有完整 review，保留报告并更正/验收或进入下一修复阶段")
                require(report["outcome"] in ("interrupted", "blocked"),
                        "代码失败必须进入下一阶段，不能作为中断恢复")
        else:
            # 旧 executor 最多初审和一次复审；原始报告及 collection 保持不变。
            require(report is not None, "旧 dispatch 恢复需要原始报告和回执")
            review = report.get("review")
            expected = [] if review is None else ([review["initial"]] if "initial" in review else []) + [review["final"]]
            paths = d.get("legacy_reviews", [])
            require(len(paths) == len(expected), "必须显式提供旧报告的全部 review collections")
            ops = executor_ops()
            prior_reviews = [ops.binding(path) for path in paths]
            for item, pair in zip(prior_reviews, expected):
                require(ops.collection(item["path"], d["previous_dispatch"])[0] == pair,
                        "旧 collection 与原报告不符")
            stage = max(0, len(expected) - 1)
            if continuation == "repair":
                require(report["status"] == "BLOCKED" and d.get("legacy_code_failure_reason"),
                        "旧报告进入修复须说明代码失败依据")
                require(review is None or review["gate"] == "BLOCKED", "旧 PASS 不进入修复")
                stage += 1
        d["previous_dispatch_sha256"] = digest(d["previous_dispatch"])
        if report:
            d["previous_report_sha256"] = digest(d["previous_report"])
    require(type(stage) is int and 0 <= stage < len(STAGE_MODELS), "四阶段已用尽，停止并保留现场")
    levels = dict(zip(MODEL_ROLES, STAGE_MODELS[stage]))
    if d.get("complex_ticket"):
        levels["executor"] = max(levels["executor"], 2)
        levels["standards"] = max(levels["standards"], 1)
    if previous and "models" in previous:
        for role in MODEL_ROLES:
            levels[role] = max(levels[role], MODEL_LEVELS.index(previous["models"][role]))
    overrides = d.get("model_overrides", {})
    require(isinstance(overrides, dict) and set(overrides) <= set(MODEL_ROLES), "model_overrides 角色无效")
    if overrides:
        require(isinstance(d.get("model_override_reason"), str) and d["model_override_reason"].strip(),
                "提前升级必须记录理由")
        for role, model in overrides.items():
            require(model in MODEL_LEVELS and MODEL_LEVELS.index(model) >= levels[role], "模型只能升级，不能降档")
            levels[role] = MODEL_LEVELS.index(model)
    d.update(stage=stage, start_head=head, prior_reviews=prior_reviews,
             models={role: MODEL_LEVELS[level] for role, level in levels.items()})


def check_stage_report_core(d, report):
    if d.get("execution_contract") != 2:
        require("delivery_kind" not in report, "旧 dispatch 不接受新交付分支")
    elif report["status"] == "DONE":
        require(report.get("delivery_kind") in ("changed", "already_satisfied"), "新契约完成报告需要 delivery_kind")
    validate_plan(d)
    if "stage" not in d:
        return  # 历史报告继续使用原校验，原文件不迁移。
    require(report.get("stage") == d["stage"] and report.get("outcome") in
            ("passed", "code_failure", "interrupted", "blocked"), "报告阶段或 outcome 不符")
    review = report.get("review")
    sources = review.get("sources", []) if review else []
    prior = d["prior_reviews"]
    require(sources[:len(prior)] == prior, "报告丢失或改写前序 review")
    require(len(sources) <= len(prior) + 1 and len(sources) <= d["stage"] + 1,
            "每阶段最多新增一轮 review")
    if review:
        require("rounds" in review and len(sources) == len(review["rounds"]), "需要完整 review rounds 和来源")
        ops = executor_ops()
        for source, pair in zip(sources, review["rounds"]):
            path = ops.bound(source)
            actual, _ = ops.collection(str(path), d["dispatch_path"])
            require(actual == pair, "报告轮次与原始 collection 不符")
        if len(sources) > len(prior):
            item = read(sources[-1]["path"])
            origin = read(ops.bound(read(ops.bound(item["round"]))["dispatch"]))
            require(origin.get("stage") == d["stage"], "新增 review 不属于当前阶段")
    if len(sources) > len(prior) and review["gate"] == "BLOCKED":
        require(report["outcome"] in ("code_failure", "blocked"), "完整 BLOCKED review 必须明确代码失败或非代码阻塞")
    if report["outcome"] == "passed":
        require(report["status"] == "DONE" and len(sources) == len(prior) + 1, "完成需要当前阶段的 review")
    elif report["outcome"] == "code_failure":
        require(report["status"] == "BLOCKED", "代码失败必须为 BLOCKED")
        if len(sources) > len(prior):
            require(review["gate"] == "BLOCKED", "当前 review PASS 不能标为代码失败")
    else:
        require(report["status"] != "DONE", "未完成阶段不能返回 DONE")


def check_stage_report(d, report):
    if d.get("ticket_execution_version"):
        import ticket_execution
        if d.get("ticket_scope") == "root":
            return ticket_execution.check_ticket(d, report)
        else:
            return ticket_execution.check_stage(d, report)
    else:
        check_stage_report_core(d, report)


def sync_main(args):
    import main_sync
    return main_sync.sync(args)


def prepare(args):
    d = read(args.input)
    d.pop("primary_snapshot_path", None)
    fields = ["repository_root", "parent_id", "rules_paths"]
    if args.role == "executor":
        fields += ["ticket_id", "mode", "test_mode", "approved_seams", "testing_seams_doc", "linked_spec", "required_boundary_gates"]
    elif args.role == "finalizer":
        fields += ["expected_children", "linked_spec", "ticket_evidence", "required_boundary_gates", "prior_finalization", "reviewed_main"]
    require(all(k in d for k in fields), "准备输入缺少必填字段")
    root = primary(d["repository_root"])
    parent = d["parent_id"]
    require(isinstance(parent, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parent) and parent not in (".", ".."), "parent ID 无效")
    branch = "implement/" + parent
    git(root, "check-ref-format", "--branch", branch)
    git(root, "check-ignore", "-q", "--", ".worktrees/probe")
    if args.role != 'preflight':
        require(isinstance(d['linked_spec'], str) and d['linked_spec'].strip(), '需要明确 linked_spec，parent 即 spec 时填写 parent ID')
        require(isinstance(d['required_boundary_gates'], list) and all(isinstance(g, str) and g.startswith('gate-') for g in d['required_boundary_gates']), '需要显式 boundary gate 列表，允许空列表')
    d["execution_contract"] = 2
    d.update(repository_root=root, parent_id=parent, branch=branch,
             worktree=str(Path(root) / ".worktrees" / parent), skill_dir=str(SCRIPTS.parent), role=args.role)
    if args.role != "preflight":
        topology(d)
        head = sha(d["worktree"], "HEAD")
        if args.role == "executor":
            require(d.get("ticket_id"), "缺少 ticket_id")
            require(d.get("mode") in ("new", "resume"), "必须显式指定 mode=new 或 resume")
            if d["mode"] == "new":
                require(not status(d["worktree"]), "新 ticket 必须从干净 worktree 开始")
                import main_sync
                require(d.get("sync_result"), "新 ticket 需要 sync-main 返回的 sync_result")
                main_sync.check_result(d, d["sync_result"])
                d["base_commit"] = head
                import handoff
                handoff.preflight_input(d)
            else:
                require(re.fullmatch(r"[0-9a-f]{40}", d.get("base_commit", "")), "恢复必须提供 start comment 中的完整 BASE")
                sha(d["worktree"], d["base_commit"])
                git(d["worktree"], "merge-base", "--is-ancestor", d["base_commit"], head)
            if d["mode"] == "resume" and d.get("previous_dispatch"):
                previous = read(d["previous_dispatch"])
                validate_plan(previous)
                if previous.get("plan_adjustment"):
                    require(d["test_mode"] == previous["test_mode"] and d["approved_seams"] == previous["approved_seams"], "恢复须沿用已调整计划；改模式使用 adapt-plan")
                    d["plan_adjustment"] = previous["plan_adjustment"]
                    d["required_boundary_gates"] = list(dict.fromkeys(previous.get("required_boundary_gates", []) + d.get("required_boundary_gates", [])))
                d["verification_dispatches"] = list(dict.fromkeys(previous.get("verification_dispatches", []) + [d["previous_dispatch"]]))
            plan = {"mode": d["test_mode"], "approved_seams": d["approved_seams"]}
            require(plan["mode"] in ("TDD", "direct_verification"), "test mode 无效")
            seams = plan["approved_seams"]
            require(isinstance(seams, list) and all(isinstance(s, str) and s for s in seams) and len(set(seams)) == len(seams), "seams 无效")
            require(plan["mode"] != "TDD" or bool(seams), "TDD 需要 approved seams")
            import ticket_execution
            if d["mode"] == "resume":
                require(d.get("previous_dispatch"), "恢复需要原 executor root dispatch")
                return ticket_execution.resume_root(d)
            ticket_execution.root_fields(d)
        else:
            require(isinstance(d["reviewed_main"], str) and re.fullmatch(r"[0-9a-f]{40}", d["reviewed_main"]), "需要已合入的完整 reviewed_main SHA")
            git(d["worktree"], "merge-base", "--is-ancestor", d["reviewed_main"], head)
            d["start_head"] = head
            d["required_boundary_gates"] = list(dict.fromkeys(
                gate for gate in d["required_boundary_gates"] if gate not in ("gate-unit", "gate-full")))
            require("prior_finalization" in d, "必须明确 prior_finalization，首次为 null")
            import finalization
            finalization.prepare_attempt(d, head)
    else:
        d.update(expected_branch=branch, expected_worktree=d["worktree"])
    directory = Path(root) / ".worktrees" / ".evidence" / parent
    if args.role != "executor":
        directory /= "preflight" if args.role == "preflight" else "final-review"
    directory /= uuid.uuid4().hex
    require(directory.resolve() == directory, "证据路径不能经过 symlink")
    directory.mkdir(parents=True, exist_ok=False)
    d.update(dispatch_path=str(directory / "dispatch.json"), report_path=str(directory / "report.json"))
    if args.role == "finalizer":
        d.setdefault("attempt_id", directory.name)
        d.setdefault("attempt_path", str(directory))
    if args.role == "executor":
        d["expected_plan_path"] = str(directory / "expected-plan.json")
        write(d["expected_plan_path"], plan)
    d["report_schema_path"] = str(directory / "report-schema.json")
    d["receipt_schema_path"] = str(directory / "receipt-schema.json")
    write(d["report_schema_path"], verifier(args.role, "--schema"))
    write(d["receipt_schema_path"], verifier(args.role, "--receipt-schema"))
    if args.role == "preflight":
        d["self_check_argv"] = [sys.executable, "-B", str(SCRIPTS / "verify-phase.py"), "--check-report", "preflight", d["report_path"], "--expected", d["dispatch_path"], "--emit-receipt"]
    write(d["dispatch_path"], d)
    return {"repository_root": root, "worktree": d["worktree"], "branch": branch,
            "dispatch_path": d["dispatch_path"], "report_path": d["report_path"],
            "report_schema_path": str(directory / "report-schema.json"), "receipt_schema_path": str(directory / "receipt-schema.json"),
            "base_commit": d.get("base_commit"), "start_head": d.get("start_head"), "reviewed_main": d.get("reviewed_main"),
            **({"coordinator_model": d["coordinator_model"]} if args.role == "executor" else {})}


def adapt_plan(args):
    """记录已核准的执行计划；新单票由 ticket-adapt-plan 调用并更新检查点。"""
    ops = executor_ops()
    d = ops.dispatch(args.dispatch)
    require(d["role"] == "executor" and d.get("execution_contract") == 2, "需要新契约 executor")
    if d.get("ticket_execution_version"):
        require(d.get("ticket_scope") == "stage", "整票 root 不适配计划；由 executor 使用 ticket-adapt-plan 更新当前 stage")
    ops.workspace(d)
    directory = Path(args.dispatch).parent
    require(not (directory / "gate-review-started.json").exists()
            and not any(x.is_dir() for x in directory.glob("review-*")) and not Path(d["report_path"]).exists(),
            "计划适配须在当前阶段 review/交付前完成")
    facts = read(args.input)
    require(set(facts) == {"reason", "acceptance", "verification", "boundary_gates", "mode"}, "计划适配字段不符")
    require(isinstance(facts["reason"], str) and facts["reason"].strip(), "需要基线适配原因")
    require(facts["mode"] in ("TDD", "direct_verification"), "执行模式无效")
    old_plan = read(d["expected_plan_path"])
    require(facts["mode"] != old_plan["mode"], "执行模式未变化")
    for key, fields in (("acceptance", {"criterion", "evidence"}), ("verification", {"command", "result"})):
        require(isinstance(facts[key], list) and facts[key] and all(
            isinstance(x, dict) and set(x) == fields and all(isinstance(v, str) and v.strip() for v in x.values())
            for x in facts[key]), key + " 需要实测证据")
    require(isinstance(facts["boundary_gates"], list) and all(isinstance(x, str) and x.startswith("gate-") for x in facts["boundary_gates"]), "boundary gates 无效")
    require(set(d.get("required_boundary_gates", [])).issubset(facts["boundary_gates"]), "计划调整丢失 gate 下限")
    require(facts["mode"] != "TDD" or bool(old_plan["approved_seams"]), "恢复 TDD 需要既有 approved seams")
    target = directory.parent / uuid.uuid4().hex
    target.mkdir()
    record = {**facts, "kind": "execution-plan-adjustment", "dispatch": ops.binding(args.dispatch),
              "base_commit": d["base_commit"], "observed_head": sha(d["worktree"], "HEAD"),
              "original_plan": old_plan, "effective_plan": {**old_plan, "mode": facts["mode"]}}
    write(target / "plan-adjustment.json", record)
    result = dict(d, mode="resume", dispatch_path=str(target / "dispatch.json"), report_path=str(target / "report.json"),
                  report_schema_path=str(target / "report-schema.json"), receipt_schema_path=str(target / "receipt-schema.json"),
                  expected_plan_path=str(target / "expected-plan.json"), test_mode=facts["mode"],
                  plan_adjustment=ops.binding(str(target / "plan-adjustment.json")),
                  required_boundary_gates=facts["boundary_gates"],
                  verification_dispatches=list(dict.fromkeys(d.get("verification_dispatches", []) + [args.dispatch])))
    # 保留 BASE、stage、models、prior_reviews；不是新的 writer 或阶段。
    write(result["expected_plan_path"], record["effective_plan"])
    write(result["report_schema_path"], verifier("executor", "--schema"))
    write(result["receipt_schema_path"], verifier("executor", "--receipt-schema"))
    write(result["dispatch_path"], result)
    return result


def validate_plan(d):
    if d.get('plan_source'):
        executor_ops().bound(d['plan_source']['report'])
    for source in d.get('environment_evidence', []):
        executor_ops().bound(source)
    if d.get("ticket_execution_version") and d.get("expected_plan_path"):
        require(read(d["expected_plan_path"]) == {"mode": d["test_mode"], "approved_seams": d["approved_seams"]}, "执行计划文件与 dispatch 不符")
    if not d.get("plan_adjustment"):
        return
    ops = executor_ops()
    record = read(ops.bound(d["plan_adjustment"]))
    previous = read(ops.bound(record["dispatch"]))
    keys = ("repository_root", "worktree", "branch", "parent_id", "ticket_id", "base_commit")
    require(all(d.get(k) == previous.get(k) for k in keys), "计划调整属于其他 ticket 或 BASE")
    validate_plan(previous)
    require(record["original_plan"] == read(previous["expected_plan_path"]), "原执行计划已变化")
    require(record["effective_plan"] == read(d["expected_plan_path"]), "实际执行计划与调整记录不符")
    require(record["effective_plan"]["approved_seams"] == record["original_plan"]["approved_seams"], "计划调整不得改变 seam")
    require(set(record["boundary_gates"]).issubset(d.get("required_boundary_gates", [])), "恢复丢失 gate 下限")


def check_batch_beads(wt, main, head):
    commit_range = main + ".." + head
    # 普通提交仍逐个检查，不能用后续还原掩盖本批次写入。
    require(not git(wt, "log", "--full-history", "--no-merges", "-1", "--format=%H",
                    commit_range, "--", ".beads"), "批次包含 .beads commit")
    for line in git(wt, "rev-list", "--min-parents=2", "--parents", commit_range).splitlines():
        commit, *parents = line.split()
        # 合入 main 时允许继承该父提交的 .beads；其余 merge 沿用第一父提交。
        upstream = [parent for parent in parents if git(wt, "merge-base", parent, main) == parent]
        source = upstream[-1] if upstream else parents[0]
        require(not git(wt, "diff", "--name-only", source, commit, "--", ".beads"),
                "merge 引入非 main 来源的 .beads 改动：" + commit)


def inspect(dispatch_path, report_path, receipt_path):
    d = read(dispatch_path)
    directory = Path(dispatch_path).resolve().parent
    for path in (report_path, receipt_path):
        require(Path(path).resolve().parent == directory, "报告和回执必须位于 dispatch 证据目录")
    role = d["role"]
    extra = [] if role == "executor" else ["--expected", dispatch_path]
    result = verifier(role, "--check-report", report_path, receipt_path, *extra)
    r = read(report_path)
    if role == "executor":
        if d.get("ticket_execution_version"):
            require(d.get("ticket_scope") == "root", "controller 只验收整票 root")
        d_plan = check_stage_report(d, r) or d
        topology(d)
        head = r["head_commit"] or sha(d["worktree"], "HEAD")
        checked = json.loads(run([sys.executable, "-B", SCRIPTS / "verify-ticket.py", d["branch"], d["base_commit"], head, r["status"], report_path, d_plan["expected_plan_path"]], d["worktree"]))
        require(checked.get("ok") and checked["report_sha256"] == result["report_sha256"], "Git 验收失败：" + json.dumps(checked, ensure_ascii=False))
    elif role == "finalizer":
        import finalization
        finalization.check_report(d, r)
        topology(d)
        root, wt = d["repository_root"], d["worktree"]
        head = sha(wt, "HEAD")
        require(r["head_commit"] is None or head == r["head_commit"], "实际 HEAD 与报告不符")
        git(wt, "merge-base", "--is-ancestor", d["start_head"], head)
        check_batch_beads(wt, d["reviewed_main"], head)
        require(not git(wt, "status", "--porcelain=v1", "--untracked-files=no", "--", ".beads"), ".beads 有未提交改动")
        if r["status"] == "READY_TO_MERGE":
            require(not status(wt), "最终 implementation worktree 必须干净")
            git(wt, "merge-base", "--is-ancestor", d["reviewed_main"], head)
    require(digest(report_path) == result["report_sha256"], "验收期间报告发生变化")
    return d, r, result


def accept(args):
    require(Path(args.output).resolve().parent == Path(args.dispatch).resolve().parent, "验收记录必须留在 dispatch 证据目录")
    d, r, result = inspect(args.dispatch, args.report, args.receipt)
    import handoff
    closure = read(args.closure) if getattr(args, 'closure', None) else None
    handoff.check_close(str(args.dispatch), str(args.report), closure,
                        required=d.get('finalization_version') == 2 or bool(d.get('preflight_acceptance')))
    record = {"kind": "mechanical_acceptance", "role": d["role"], "status": r["status"],
              "dispatch_path": str(Path(args.dispatch).resolve()), "dispatch_sha256": digest(args.dispatch),
              "report_path": str(Path(args.report).resolve()), "report_sha256": result["report_sha256"],
              "receipt_path": str(Path(args.receipt).resolve()), "receipt_sha256": digest(args.receipt)}
    if closure:
        record['closure_source'] = closure
    write(args.output, record)
    return record


def accepted(path):
    a = read(path)
    require(Path(path).resolve().parent == Path(a["dispatch_path"]).resolve().parent, "验收记录不属于 dispatch 目录")
    require(a.get("kind") == "mechanical_acceptance", "需要机械验收记录")
    for kind in ("dispatch", "report", "receipt"):
        require(digest(a[kind + "_path"]) == a[kind + "_sha256"], "已验收证据发生变化：" + kind)
    d, r, _ = inspect(a["dispatch_path"], a["report_path"], a["receipt_path"])
    import handoff
    handoff.check_close(a['dispatch_path'], a['report_path'], a.get('closure_source'),
                        required=d.get('finalization_version') == 2 or bool(d.get('preflight_acceptance')))
    require(r["status"] in ("DONE", "READY_TO_MERGE"), "只有成功报告可生成完成记录或合入")
    return a, d, r


def comment(args):
    a, d, r = accepted(args.acceptance)
    require(Path(args.output).resolve().parent == Path(a["dispatch_path"]).resolve().parent, "comment 文件必须留在 dispatch 证据目录")
    final = d["role"] == "finalizer"
    require(d["role"] in ("executor", "finalizer"), "该角色没有完成 comment")
    pair = r["review_rounds"][-1] if final else r["review"]["final"]
    metadata = {"kind": "integration-ready" if final else "ticket-completion", "parent_id": d["parent_id"],
                "reviewed_main": r["reviewed_main"] if final else r["base_commit"], "reviewed_head": r["head_commit"],
                "acceptance_path": str(Path(args.acceptance).resolve()), "report_sha256": a["report_sha256"]}
    lines = ["## " + metadata["kind"], args.summary, "", "```json", json.dumps(metadata, ensure_ascii=False), "```", "",
             "提交范围：`" + metadata["reviewed_main"] + ".." + metadata["reviewed_head"] + "`",
             "Review：PASS；轮次：" + str(len(r["review_rounds"]) if final else r["review"]["attempts"])]
    if metadata["reviewed_main"] == metadata["reviewed_head"]:
        lines += ["受审行为已在基线满足；本次无新增提交。"]
    if not final:
        if d.get("ticket_execution_version"):
            d = read(executor_ops().bound(r["execution"]["stage_dispatch"]))
            gates = list(d.get("required_boundary_gates", []))
            for item in r["execution"]["implementers"]:
                implementation = read(executor_ops().bound(item["report"]))
                gates += implementation["required_boundary_gates"]
            lines += ["Boundary gates：" + json.dumps(list(dict.fromkeys(gates)), ensure_ascii=False),
                      "阶段与实现来源：" + json.dumps(r["execution"], ensure_ascii=False)]
        if d.get("plan_adjustment"):
            adjustment = read(executor_ops().bound(d["plan_adjustment"]))
            lines += ["执行计划调整：" + adjustment["original_plan"]["mode"] + " → " + adjustment["effective_plan"]["mode"],
                      "调整原因：" + adjustment["reason"], "调整证据：" + json.dumps(d["plan_adjustment"], ensure_ascii=False)]
        if "stage" in d:
            lines += ["交付阶段：" + str(d["stage"]) + "（0 为首次实现）",
                      "本阶段模型：" + json.dumps(d["models"], ensure_ascii=False)]
        lines += ["Test mode：" + r["test_plan"]["mode"], "Approved seams：" + json.dumps(r["test_plan"]["approved_seams"], ensure_ascii=False),
                  "Commits：" + ", ".join(c["sha"] for c in r["implementation_commits"])]
    lines += ["", "验证记录：", "```json", json.dumps(r["verification"], ensure_ascii=False, indent=2), "```",
              "", "残留非阻塞 smells：", "```json", json.dumps([f for axis in pair.values() for f in axis["findings"] if f["kind"] == "smell"], ensure_ascii=False, indent=2), "```",
              "", "证据：", a["report_path"], a["receipt_path"], str(Path(args.acceptance).resolve())]
    if final:
        if "stage" in r:
            lines += ["交付阶段：" + str(r["stage"]), "阶段证据：", json.dumps(r["stage_sources"], ensure_ascii=False)]
        lines.extend(r["sources"])
    for evidence in args.evidence:
        require(Path(evidence).is_file(), "补证文件不存在")
        lines.append(str(Path(evidence).resolve()))
    write(args.output, "\n".join(lines) + "\n")
    return {"comment_path": str(Path(args.output).resolve()), "metadata": metadata}


def bd(root, *args):
    return json.loads(run(["bd", *args, "--readonly", "--json"], root))


def primary_writable(root):
    require(primary(root) == root, "primary 必须 checkout main")
    require(not status(root), "primary 有未提交改动，暂不能更新 main")
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
        path = git(root, "rev-parse", "--path-format=absolute", "--git-path", name)
        require(not Path(path).exists(), "primary 存在未完成 Git 操作：" + path)


def update_main(args):
    root = primary(args.repository_root)
    primary_writable(root)
    fetched = subprocess.run(["git", "-C", root, "fetch", "origin"], capture_output=True, text=True)
    target = sha(root, "refs/remotes/origin/main")
    primary_writable(root)
    git(root, "merge", "--ff-only", target)
    return {"repository_root": root, "main_commit": sha(root, "refs/heads/main"),
            "fetch_failed": fetched.returncode != 0,
            "note": "fetch 失败，以本地 ref 为准" if fetched.returncode else ""}


def merge(args):
    a, d, r = accepted(args.acceptance)
    require(Path(args.output).resolve().parent == Path(a["dispatch_path"]).resolve().parent, "合入记录必须留在 dispatch 证据目录")
    require(d["role"] == "finalizer", "合入需要 finalizer 验收")
    root, wt = d["repository_root"], d["worktree"]
    comments = bd(root, "comments", d["parent_id"])
    matches = [c for c in comments if str(c.get("id")) == args.comment_id]
    require(len(matches) == 1, "integration-ready comment 不存在或不唯一")
    body = matches[0].get("text", matches[0].get("body", ""))
    blocks = re.findall(r"```json\s*\n(.*?)\n```", body, re.S)
    metadata = [json.loads(b) for b in blocks]
    require(any(isinstance(m, dict) and m.get("kind") == "integration-ready" and m.get("parent_id") == d["parent_id"] and m.get("reviewed_main") == r["reviewed_main"] and m.get("reviewed_head") == r["head_commit"] and m.get("report_sha256") == a["report_sha256"] and m.get("acceptance_path") == str(Path(args.acceptance).resolve()) for m in metadata), "integration-ready comment 未绑定本次证据")
    topology(d)
    primary_writable(root)
    require(not status(wt), "合入前 implementation worktree 不干净")
    current_main = sha(root, "HEAD")
    require(current_main == r["reviewed_main"] or (Path(args.output).exists() and current_main == r["head_commit"]), "main 已移动，必须重新最终集成")
    require(sha(wt, "HEAD") == r["head_commit"], "受审 HEAD 已移动")
    record = {"kind": "merge_checkpoint", **{k: d[k] for k in ("repository_root", "worktree", "branch", "parent_id")},
              "reviewed_head": r["head_commit"], "integration_comment_id": args.comment_id,
              "acceptance_path": str(Path(args.acceptance).resolve())}
    if Path(args.output).exists():
        require(read(args.output) == record, "已有合入 checkpoint 与本次操作不符")
    else:
        write(args.output, record)
    if current_main != r["head_commit"]:
        git(root, "merge", "--ff-only", r["head_commit"])
    require(sha(root, "HEAD") == r["head_commit"], "合入后 HEAD 不符")
    return {**record, "merged": True}


def cleanup(args):
    d = read(args.merge_record)
    require(d.get("kind") == "merge_checkpoint", "需要合入 checkpoint")
    topology(d, allow_missing=True)
    root, wt = d["repository_root"], Path(d["worktree"])
    parents = bd(root, "show", d["parent_id"])
    require(len(parents) == 1 and parents[0]["id"] == d["parent_id"] and parents[0]["status"] == "closed", "parent 尚未关闭")
    git(root, "merge-base", "--is-ancestor", d["reviewed_head"], "main")
    refs = git(root, "for-each-ref", "--format=%(refname)", "refs/heads/" + d["branch"]).splitlines()
    branch_exists = "refs/heads/" + d["branch"] in refs
    if branch_exists:
        require(sha(root, "refs/heads/" + d["branch"]) == d["reviewed_head"], "implementation branch 已移动")
    if wt.exists():
        require(not status(wt), "implementation worktree 不干净")
        git(root, "worktree", "remove", str(wt))
    if branch_exists:
        git(root, "branch", "-d", d["branch"])
    return {"cleaned": True, "parent_id": d["parent_id"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare"); p.add_argument("role", choices=("preflight", "executor", "finalizer")); p.add_argument("--input", required=True)
    p = commands.add_parser("update-main"); p.add_argument("--repository-root", required=True)
    p = commands.add_parser("sync-main"); p.add_argument("--input", required=True)
    p = commands.add_parser("adapt-plan")
    p.add_argument("--dispatch", required=True); p.add_argument("--input", required=True)
    p = commands.add_parser("accept")
    p.add_argument("--closure", help="收尾来源 path/sha256 JSON")
    for name in ("dispatch", "report", "receipt", "output"): p.add_argument("--" + name, required=True)
    p = commands.add_parser("comment")
    for name in ("acceptance", "summary", "output"): p.add_argument("--" + name, required=True)
    p.add_argument("--evidence", action="append", default=[])
    p = commands.add_parser("merge")
    for name in ("acceptance", "comment-id", "output"): p.add_argument("--" + name, required=True)
    p = commands.add_parser("cleanup"); p.add_argument("--merge-record", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(globals()[args.command.replace("-", "_")](args), ensure_ascii=False))
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

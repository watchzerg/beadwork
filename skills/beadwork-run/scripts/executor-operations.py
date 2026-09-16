#!/usr/bin/env python3
"""ticket 开工、implementer 提交检查、阶段调度及报告组装；仅写证据，不派发 agent。"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
import controller as c


AXES = ("standards", "spec")


def load(path):
    # 与现有 verifier 一样拒绝重复 JSON key 和非有限数值。
    return json.loads(Path(path).read_text(), object_pairs_hook=unique,
                      parse_constant=lambda value: fail("无效 JSON 数值：" + value))


def fail(message):
    raise ValueError(message)


def unique(pairs):
    result = {}
    for key, value in pairs:
        c.require(key not in result, "重复 JSON key：" + key)
        result[key] = value
    return result


def absolute(path):
    p = Path(path)
    c.require(p.is_absolute() and p.resolve() == p, "需要无 symlink 的绝对路径")
    return p


def output_path(path, directory):
    p = absolute(path)
    c.require(p.parent == directory, "输出必须位于指定证据目录")
    c.require(not p.exists(), "证据文件已存在，请使用新文件名")
    return p


def binding(path):
    return {"path": str(absolute(path)), "sha256": c.digest(path)}


def bound(item):
    path = absolute(item["path"])
    c.require(c.digest(path) == item["sha256"], "证据文件已变化：" + str(path))
    return path


def dispatch(path):
    p = absolute(path)
    d = load(p)
    c.require(d["role"] in ("executor", "finalizer", "implementer"), "需要 executor、implementer 或 finalizer dispatch")
    c.require(Path(d["dispatch_path"]) == p, "dispatch 路径不符")
    c.require(Path(d["report_path"]).parent == p.parent, "报告目录与 dispatch 不符")
    c.validate_plan(d)
    return d


def reviewed_state(d, base, head):
    c.topology(d)
    wt = d["worktree"]
    c.require(c.sha(wt, "HEAD") == head, "受审 HEAD 已变化")
    c.require(c.sha(wt, base) == base, "需要完整 BASE SHA")
    c.git(wt, "merge-base", "--is-ancestor", base, head)
    c.require(not c.status(wt), "review 要求 worktree 干净")
    if not c.git(wt, "diff", base + "..." + head):
        c.require(d.get("execution_contract") == 2 and base == head, "review diff 为空")
        if d["role"] == "executor":
            c.require(load(d["expected_plan_path"])["mode"] == "direct_verification", "无提交完成需要 direct_verification")


def worker(option, *args):
    result = load_command([sys.executable, "-B", c.SCRIPTS / "verify-worker.py", option, "reviewer", *args])
    if option == "--check-report":
        c.require(result.get("ok") is True, "reviewer 验收失败：" + json.dumps(result, ensure_ascii=False))
    return result


def load_command(args, cwd=None):
    return json.loads(c.run(args, cwd))


def prepare_review(args):
    d = dispatch(args.dispatch)
    if d.get("ticket_execution_version"):
        import ticket_execution
        c.require(d.get("ticket_scope") == "stage", "review 由 stage executor 派发")
        ticket_execution.review_ready(d)
    base = d["base_commit"] if d["role"] == "executor" else d["reviewed_main"]
    head = c.sha(d["worktree"], "HEAD")
    reviewed_state(d, base, head)
    review_kind = "existing_behavior" if base == head else "change"
    evidence = None
    if review_kind == "existing_behavior":
        c.require(getattr(args, "evidence", None), "已有行为审查需要 acceptance 证据文件")
        evidence = binding(args.evidence)
        entries = load(bound(evidence))
        c.require(isinstance(entries, list) and entries and all(
            isinstance(x, dict) and set(x) == {"criterion", "evidence"} and
            all(isinstance(v, str) and v.strip() for v in x.values()) for x in entries), "acceptance 证据无效")
    if "stage" in d:
        import gate_repair
        gate_repair.freeze(d)
    directory = absolute(args.dispatch).parent / ("review-" + uuid.uuid4().hex)
    directory.mkdir()
    record = {"dispatch": binding(args.dispatch), "reviewed_base": base,
              "reviewed_head": head, "axes": {}, "review_kind": review_kind, "acceptance_evidence": evidence}
    commits = c.git(d["worktree"], "log", "--format=%H %s", base + ".." + head)
    for axis in AXES:
        folder = directory / axis
        folder.mkdir()
        identity = {"review_kind": review_kind, "acceptance_evidence": evidence, "axis": axis, "reviewed_base": base, "reviewed_head": head,
                    "skill_dir": d["skill_dir"], "worktree": d["worktree"],
                    "rules_paths": d["rules_paths"], "parent_id": d["parent_id"],
                    "ticket_id": d.get("ticket_id"), "linked_spec": d.get("linked_spec"),
                    "dispatch_path": str(folder / "dispatch.json"),
                    "report_path": str(folder / "report.json"),
                    "report_schema_path": str(folder / "report-schema.json"),
                    "receipt_schema_path": str(folder / "receipt-schema.json"),
                    "commits": commits,
                    "diff_argv": ["git", "-C", d["worktree"], "diff", base + "..." + head]}
        if "stage" in d:
            identity.update(stage=d["stage"], **d["models"][axis])
        identity["self_check_argv"] = [sys.executable, "-B", str(c.SCRIPTS / "verify-worker.py"),
            "--check-report", "reviewer", identity["report_path"], "--expected", identity["dispatch_path"], "--emit-receipt"]
        c.write(identity["report_schema_path"], worker("--schema"))
        c.write(identity["receipt_schema_path"], worker("--receipt-schema"))
        c.write(identity["dispatch_path"], identity)
        record["axes"][axis] = binding(identity["dispatch_path"])
    path = directory / "round.json"
    c.write(path, record)
    return {"round_path": str(path), "axes": {axis: item["path"] for axis, item in record["axes"].items()}}


def pair_from_sources(round_path, sources):
    record = load(round_path)
    d = dispatch(bound(record["dispatch"]))
    base = d["base_commit"] if d["role"] == "executor" else d["reviewed_main"]
    c.require(record["reviewed_base"] == base, "round BASE 与派发不符")
    if base == record["reviewed_head"]:
        c.require(d.get("execution_contract") == 2 and record.get("review_kind") == "existing_behavior", "空 diff 缺少已有行为审查身份")
        bound(record["acceptance_evidence"])
    c.require(set(sources) == set(AXES), "必须明确提供两个轴的报告与回执")
    pair = {}
    for axis in AXES:
        c.require(set(sources[axis]) == {"report", "receipt"}, "每轴仅提供 report 和 receipt")
        identity_path = bound(record["axes"][axis])
        c.require(identity_path.parent == round_path.parent / axis, "轴目录不符")
        identity = load(identity_path)
        c.require(identity["axis"] == axis and identity["reviewed_base"] == base
                  and identity["reviewed_head"] == record["reviewed_head"], "轴身份与 round 不符")
        c.require(identity.get("review_kind") == record.get("review_kind") and
                  identity.get("acceptance_evidence") == record.get("acceptance_evidence"), "轴审查范围与 round 不符")
        report = absolute(sources[axis]["report"])
        receipt = absolute(sources[axis]["receipt"])
        c.require(report.parent == identity_path.parent and receipt.parent == identity_path.parent,
                  "报告和回执必须位于该轴证据目录")
        checked = worker("--check-report", report, receipt, "--expected", identity_path)
        c.require(checked["status"] == "COMPLETED", "reviewer 未完成，保留失败证据并返回 BLOCKED")
        pair[axis] = load(report)
        c.require(c.digest(report) == checked["report_sha256"], "验收期间报告发生变化")
    gate = "BLOCKED" if any(f["blocking"] for r in pair.values() for f in r["findings"]) else "PASS"
    return record, d, pair, gate


def collect_review(args):
    path = absolute(args.round)
    sources = load(absolute(args.input))
    record, d, pair, gate = pair_from_sources(path, sources)
    reviewed_state(d, record["reviewed_base"], record["reviewed_head"])
    result = {"round": binding(path), "sources": {
        axis: {key: binding(value) for key, value in sources[axis].items()} for axis in AXES},
        "pair": pair, "gate": gate}
    output = output_path(args.output, path.parent)
    c.write(output, result)
    if d.get("ticket_execution_version"):
        import ticket_execution
        ticket_execution.select_review(d, output)
    return {"collection_path": str(output), "gate": gate}


def collection(path, dispatch_path):
    item = load(absolute(path))
    round_path = bound(item["round"])
    sources = {axis: {key: str(bound(value)) for key, value in entries.items()}
               for axis, entries in item["sources"].items()}
    record, previous, pair, gate = pair_from_sources(round_path, sources)
    current = dispatch(dispatch_path)
    # 接替显式选择旧证据时，保留同票、同 BASE 的已完成轮次。
    keys = ("role", "repository_root", "worktree", "branch", "parent_id", "ticket_id", "base_commit")
    if current.get("ticket_execution_version"):
        keys += ("ticket_root",)
    if current["role"] == "finalizer":
        keys += ("reviewed_main",)
        if "attempt_id" in previous and "attempt_id" in current:
            keys += ("attempt_id",)
    c.require(all(previous.get(key) == current.get(key) for key in keys), "review 属于其他 ticket 或 BASE")
    c.require(item["pair"] == pair and item["gate"] == gate, "聚合结果与原始报告不符")
    return pair, gate


def check_report(dispatch_path, report_path):
    d = dispatch(dispatch_path)
    c.require(d["role"] == "executor", "需要 executor dispatch")
    p = absolute(report_path)
    c.require(p.parent == absolute(dispatch_path).parent, "报告必须位于本轮 dispatch 目录")
    report = load(p)
    plan_d = c.check_stage_report(d, report) or d
    c.topology(d)
    head = report["head_commit"] or c.sha(d["worktree"], "HEAD")
    checked = load_command([sys.executable, "-B", c.SCRIPTS / "verify-ticket.py",
        d["branch"], d["base_commit"], head, report["status"], p, plan_d["expected_plan_path"]], d["worktree"])
    c.require(checked.get("ok") is True, "executor 完整自检失败：" + json.dumps(checked, ensure_ascii=False))
    return {"status": report["status"], "report_path": str(p), "report_sha256": checked["report_sha256"]}


def paths(wt, *args):
    # 保留文件名中的空格、换行及末尾字符；禁用 rename 合并以列出旧、新路径。
    result = subprocess.run(["git", "--literal-pathspecs", "-C", wt, *args],
                            capture_output=True)
    c.require(result.returncode == 0, os.fsdecode(result.stderr))
    return sorted({os.fsdecode(p) for p in result.stdout.split(b"\0") if p})


def workspace(d):
    c.require(d["role"] in ("executor", "implementer"), "需要 ticket dispatch")
    c.topology(d)
    wt = d["worktree"]
    c.require(c.sha(wt, d["base_commit"]) == d["base_commit"], "需要完整 BASE")
    c.git(wt, "merge-base", "--is-ancestor", d["base_commit"], "HEAD")
    return {"head": c.sha(wt, "HEAD"),
            "staged": paths(wt, "diff", "--cached", "--name-only", "--no-renames", "-z"),
            "unstaged": paths(wt, "diff", "--name-only", "--no-renames", "-z"),
            "untracked": paths(wt, "ls-files", "--others", "--exclude-standard", "-z")}


def inspect_context(args):
    d = dispatch(args.dispatch)
    directory = absolute(args.dispatch).parent / ("context-" + uuid.uuid4().hex)
    directory.mkdir()
    result = {"evidence_directory": str(directory), "sources": {}}
    try:
        result["workspace"] = state = workspace(d)
        c.require(d["mode"] in ("new", "resume"), "mode 无效")
        fresh = d["mode"] == "new"
        if d.get("ticket_scope") == "root":
            import ticket_execution
            fresh = fresh and ticket_execution.checkpoints(d)[0]["stage_dispatch"] is None
        if fresh:
            c.require(state["head"] == d["base_commit"] and not c.status(d["worktree"]),
                      "新票派发后现场已变化")
        for key in ("report_schema_path", "receipt_schema_path", "expected_plan_path"):
            load(absolute(d[key]))
        for name, command, identity in (("ticket", "show", d["ticket_id"]),
                                        ("comments", "comments", d["ticket_id"]),
                                        ("parent", "show", d["parent_id"])):
            raw = c.run(["bd", command, identity, "--json"], d["worktree"])
            target = directory / (name + ".json")
            c.write(target, raw)
            result["sources"][name] = str(target)
            value = load(target)
            c.require(isinstance(value, list), name + " 必须返回数组")
            if command == "show":
                c.require(len(value) == 1 and value[0].get("id") == identity, name + " 身份不符")
                if name == "ticket":
                    c.require(value[0].get("status") == "in_progress", "ticket 未处于 in_progress")
                description = value[0].get("description")
                c.require(isinstance(description, str) and description.strip(), name + " description 缺失")
                description_path = directory / (name + "-description.md")
                c.write(description_path, description)
                result["sources"][name + "_description"] = str(description_path)
        result["commits"] = c.git(d["worktree"], "log", "--reverse", "--format=%H %s",
                                  d["base_commit"] + "..HEAD").splitlines()
        result["ok"] = True
    except Exception as error:
        result.update(ok=False, error=str(error))
        c.write(directory / "inspection.json", result)
        fail(json.dumps(result, ensure_ascii=False))
    c.write(directory / "inspection.json", result)
    return result


def check_layer(args):
    d = dispatch(args.dispatch)
    if d.get("ticket_execution_version"):
        import ticket_execution
        ticket_execution.require_writer(d)
    layer = load(absolute(args.input))
    c.require(set(layer) == {"files", "message"}, "本层输入仅包含 files 和 message")
    files = layer["files"]
    c.require(isinstance(files, list) and files and all(isinstance(p, str) and p for p in files),
              "files 必须为非空路径列表")
    c.require(len(set(files)) == len(files), "files 有重复路径")
    for name in files:
        c.require(not Path(name).is_absolute() and all(p not in ("", ".", "..") for p in name.split("/")),
                  "需要规范的 worktree 相对文件路径")
        c.require(name != ".beads" and not name.startswith(".beads/"), "不得提交 .beads")
    message = layer["message"]
    c.require(isinstance(message, str) and re.search(
        r"(?<![A-Za-z0-9._-])" + re.escape(d["ticket_id"]) + r"(?![A-Za-z0-9._-])", message),
        "commit message 必须包含完整 ticket_id")
    state = workspace(d)
    c.require(set(state["staged"]) == set(files), "staged 路径与本层 files 不一致")
    c.require(not set(files).intersection(state["unstaged"] + state["untracked"]),
              "本层路径仍有未暂存内容")
    return {"ok": True, **state, "remaining": sorted(set(state["unstaged"] + state["untracked"]))}


def assemble(args):
    d = dispatch(args.dispatch)
    c.require(d["role"] == "executor", "需要 executor dispatch")
    report = load(absolute(args.draft))
    fields = {"status", "test_plan", "acceptance", "verification", "requested_context", "blockers", "concerns"}
    notes = report.pop("verification_notes", {})
    outcome = report.pop("outcome", None)
    c.require(set(report) == fields, "draft 仅提供原语义字段及可选 verification_notes")
    spec = importlib.util.spec_from_file_location("verification", c.SCRIPTS / "run-verification.py")
    verification = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verification)
    if not d.get("ticket_execution_version"):
        report["verification"] = verification.collect(args.dispatch, list(dict.fromkeys(d.get("verification_dispatches", []) + args.verification_dispatch)), notes, report["status"]) + report["verification"]
    else:
        c.require(getattr(args, "report_extra", None), "阶段报告使用 ticket-assemble")
    if report["test_plan"] is not None:
        c.require(set(report["test_plan"]) == {"decision_source", "red_evidence"},
                  "draft test_plan 仅提供 decision_source 和 red_evidence")
        report["test_plan"] = {**load(d["expected_plan_path"]), **report["test_plan"]}
    base, head = d["base_commit"], c.sha(d["worktree"], "HEAD")
    commits = c.git(d["worktree"], "log", "--reverse", "--format=%H %s", base + ".." + head)
    report.update(base_commit=base, head_commit=head,
                  implementation_commits=[dict(zip(("sha", "subject"), line.split(" ", 1))) for line in commits.splitlines()],
                  review=None)
    if d.get("execution_contract") == 2:
        report["delivery_kind"] = ("already_satisfied" if base == head else "changed") if report["status"] == "DONE" else None
    if "stage" in d:
        c.require(outcome in ("passed", "code_failure", "interrupted", "blocked"), "draft 必须明确 outcome")
        report.update(stage=d["stage"], outcome=outcome)
    c.require(len(args.review) <= 4, "最多四轮 review")
    if args.review:
        rounds = [collection(path, args.dispatch) for path in args.review]
        review = {"attempts": len(rounds), "gate": rounds[-1][1], "final": rounds[-1][0],
                  "rounds": [pair for pair, gate in rounds], "sources": [binding(path) for path in args.review]}
        if len(rounds) > 1:
            c.require(all(gate == "BLOCKED" for _, gate in rounds[:-1]), "PASS 不进入修复复审")
            review["initial"] = rounds[0][0]
        report["review"] = review
    report.update(getattr(args, "report_extra", {}))
    output = output_path(args.output, absolute(args.dispatch).parent)
    c.write(output, report)
    # 自检失败保留候选报告供诊断；更正使用新文件名。
    return check_report(args.dispatch, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("ticket-stage")
    p.add_argument("--dispatch", required=True); p.add_argument("--input", required=True)
    p = commands.add_parser("ticket-deliver")
    p.add_argument("--dispatch", required=True); p.add_argument("--output", required=True)
    p = commands.add_parser("ticket-adapt-plan")
    p.add_argument("--dispatch", required=True); p.add_argument("--input", required=True)
    for command in ("ticket-assemble", "implementer-assemble"):
        p = commands.add_parser(command)
        for name in ("dispatch", "draft", "output"):
            p.add_argument("--" + name, required=True)
        if command == "ticket-assemble":
            p.add_argument("--review", action="append", default=[])
    p = commands.add_parser("implementer-check")
    p.add_argument("--dispatch", required=True); p.add_argument("--report", required=True)
    p = commands.add_parser("implementer-accept")
    for name in ("dispatch", "report", "receipt"):
        p.add_argument("--" + name, required=True)
    p = commands.add_parser("begin-gate-repair")
    p.add_argument("--dispatch", required=True); p.add_argument("--failure", required=True)
    p = commands.add_parser("final-stage")
    p.add_argument("--dispatch", required=True); p.add_argument("--input", required=True)
    p = commands.add_parser("final-assemble")
    for name in ("dispatch", "draft", "output"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--review", action="append", default=[])
    p.add_argument("--fixers", required=True, help="fixer dispatch/report/receipt 的 hash 绑定数组 JSON")
    p = commands.add_parser("inspect"); p.add_argument("--dispatch", required=True)
    p = commands.add_parser("check-layer")
    p.add_argument("--dispatch", required=True); p.add_argument("--input", required=True)
    p = commands.add_parser("review-prepare"); p.add_argument("--dispatch", required=True)
    p.add_argument("--evidence", help="无提交审查的 acceptance 映射 JSON")
    p = commands.add_parser("review-collect")
    for name in ("round", "input", "output"):
        p.add_argument("--" + name, required=True)
    p = commands.add_parser("assemble")
    for name in ("dispatch", "draft", "output"):
        p.add_argument("--" + name, required=True)
    p.add_argument("--review", action="append", default=[])
    p.add_argument("--verification-dispatch", action="append", default=[], help="显式恢复同票旧 dispatch 的验证历史")
    p = commands.add_parser("check")
    p.add_argument("--dispatch", required=True); p.add_argument("--report", required=True)
    args = parser.parse_args()
    import finalization
    import ticket_execution
    import gate_repair
    action = {"ticket-stage": lambda a: ticket_execution.prepare_stage(a.dispatch, load(a.input)),
              "ticket-deliver": lambda a: ticket_execution.deliver(a.dispatch, a.output),
              "ticket-adapt-plan": ticket_execution.adapt_plan,
              "ticket-assemble": ticket_execution.assemble_stage,
              "implementer-assemble": ticket_execution.implementer_assemble,
              "implementer-check": lambda a: ticket_execution.implementer_check(a.dispatch, a.report),
              "implementer-accept": lambda a: ticket_execution.accept_implementer(a.dispatch, a.report, a.receipt),
              "begin-gate-repair": gate_repair.begin,
              "final-stage": lambda a: finalization.prepare_stage(a.dispatch, load(a.input)),
              "final-assemble": lambda a: finalization.assemble(a.dispatch, a.draft, a.output, a.review, load(a.fixers)),
              "inspect": inspect_context, "check-layer": check_layer,
              "review-prepare": prepare_review, "review-collect": collect_review,
              "assemble": assemble, "check": lambda a: check_report(a.dispatch, a.report)}
    print(json.dumps(action[args.command](args), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        sys.exit(1)

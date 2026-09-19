#!/usr/bin/env python3
"""ticket 开工、implementer 提交检查、阶段调度及报告组装；仅写证据，不派发 agent。"""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import re
import sys
import uuid

sys.dont_write_bytecode = True

import dispatch_contract
import evidence
import final_state
import finalization
import gate_repair
import handoff
import report_io
import repository
import review_evidence
import review_operations
import ticket_execution
import ticket_reports
import ticket_state


AXES = review_operations.AXES
load = evidence.read


def fail(message):
    raise ValueError(message)


absolute = evidence.absolute
output_path = dispatch_contract.output_path
binding = evidence.binding
bound = evidence.bound
dispatch = dispatch_contract.dispatch
reviewed_state = review_operations.reviewed_state
worker = report_io.reviewer
prepare_review = review_operations.prepare_review
pair_from_sources = review_evidence.pair_from_sources
collect_review = review_operations.collect_review
collection = review_evidence.collection
check_report = ticket_reports.check_report
paths = repository.paths
workspace = repository.workspace


def inspect_context(args):
    d = dispatch(args.dispatch)
    directory = absolute(args.dispatch).parent / ("context-" + uuid.uuid4().hex)
    directory.mkdir()
    result = {"evidence_directory": str(directory), "sources": {}}
    try:
        result["workspace"] = state = workspace(d)
        repository.require(d["mode"] in ("new", "resume"), "mode 无效")
        fresh = d["mode"] == "new"
        if d.get("ticket_scope") == "root":
            fresh = fresh and ticket_state.checkpoints(d)[0]["stage_dispatch"] is None
        if fresh:
            repository.require(state["head"] == d["base_commit"] and not repository.status(d["worktree"]),
                      "新票派发后现场已变化")
        for key in ("report_schema_path", "receipt_schema_path", "expected_plan_path"):
            load(absolute(d[key]))
        for name, command, identity in (("ticket", "show", d["ticket_id"]),
                                        ("comments", "comments", d["ticket_id"]),
                                        ("parent", "show", d["parent_id"])):
            raw = repository.run(["bd", command, identity, "--json"], d["worktree"])
            target = directory / (name + ".json")
            evidence.write(target, raw)
            result["sources"][name] = str(target)
            value = load(target)
            repository.require(isinstance(value, list), name + " 必须返回数组")
            if command == "show":
                repository.require(len(value) == 1 and value[0].get("id") == identity, name + " 身份不符")
                if name == "ticket":
                    repository.require(value[0].get("status") == "in_progress", "ticket 未处于 in_progress")
                description = value[0].get("description")
                repository.require(isinstance(description, str) and description.strip(), name + " description 缺失")
                description_path = directory / (name + "-description.md")
                evidence.write(description_path, description)
                result["sources"][name + "_description"] = str(description_path)
        result["commits"] = repository.git(d["worktree"], "log", "--reverse", "--format=%H %s",
                                  d["base_commit"] + "..HEAD").splitlines()
        result["ok"] = True
    except Exception as error:
        result.update(ok=False, error=str(error))
        evidence.write(directory / "inspection.json", result)
        fail(json.dumps(result, ensure_ascii=False))
    evidence.write(directory / "inspection.json", result)
    return result


def check_layer(args):
    d = dispatch(args.dispatch)
    if d.get("ticket_scope"):
        ticket_state.require_writer(d)
    layer = load(absolute(args.input))
    repository.require(set(layer) == {"files", "message"}, "本层输入仅包含 files 和 message")
    files = layer["files"]
    repository.require(isinstance(files, list) and files and all(isinstance(p, str) and p for p in files),
              "files 必须为非空路径列表")
    repository.require(len(set(files)) == len(files), "files 有重复路径")
    for name in files:
        repository.require(not Path(name).is_absolute() and all(p not in ("", ".", "..") for p in name.split("/")),
                  "需要规范的 worktree 相对文件路径")
        repository.require(name != ".beads" and not name.startswith(".beads/"), "不得提交 .beads")
    message = layer["message"]
    repository.require(isinstance(message, str) and re.search(
        r"(?<![A-Za-z0-9._-])" + re.escape(d["ticket_id"]) + r"(?![A-Za-z0-9._-])", message),
        "commit message 必须包含完整 ticket_id")
    state = workspace(d)
    repository.require(set(state["staged"]) == set(files), "staged 路径与本层 files 不一致")
    repository.require(not set(files).intersection(state["unstaged"] + state["untracked"]),
              "本层路径仍有未暂存内容")
    return {"ok": True, **state, "remaining": sorted(set(state["unstaged"] + state["untracked"]))}


assemble = ticket_reports.assemble


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser('context-add')
    p.add_argument('--dispatch', required=True); p.add_argument('--input', required=True)
    p = commands.add_parser('handoff-close')
    for name in ('dispatch', 'report', 'input'):
        p.add_argument('--' + name, required=True)
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
    p = commands.add_parser("implementer-check")
    p.add_argument("--dispatch", required=True); p.add_argument("--report", required=True)
    p = commands.add_parser("implementer-accept")
    p.add_argument("--closure")
    for name in ("dispatch", "report", "receipt"):
        p.add_argument("--" + name, required=True)
    p = commands.add_parser("begin-gate-repair")
    p.add_argument("--dispatch", required=True); p.add_argument("--failure", required=True)
    p = commands.add_parser('final-deliver')
    p.add_argument('--dispatch', required=True); p.add_argument('--output', required=True)
    p = commands.add_parser('fixer-assemble')
    for name in ('dispatch', 'draft', 'output'):
        p.add_argument('--' + name, required=True)
    p = commands.add_parser('fixer-check')
    p.add_argument('--dispatch', required=True); p.add_argument('--report', required=True)
    p = commands.add_parser('fixer-accept')
    p.add_argument('--closure')
    for name in ('dispatch', 'report', 'receipt'):
        p.add_argument('--' + name, required=True)
    p = commands.add_parser('final-gates')
    p.add_argument('--dispatch', required=True); p.add_argument('--input', required=True)
    p = commands.add_parser("final-stage")
    p.add_argument("--dispatch", required=True); p.add_argument("--input", required=True)
    p = commands.add_parser("final-assemble")
    for name in ("dispatch", "draft", "output"):
        p.add_argument("--" + name, required=True)
    p = commands.add_parser("inspect"); p.add_argument("--dispatch", required=True)
    p = commands.add_parser("check-layer")
    p.add_argument("--dispatch", required=True); p.add_argument("--input", required=True)
    p = commands.add_parser("review-prepare"); p.add_argument("--dispatch", required=True)
    p.add_argument("--resume", action="store_true", help="仅恢复原 round 的未完成准备")
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
    action = {'context-add': lambda a: handoff.add_context(a.dispatch, load(a.input)),
              'handoff-close': lambda a: handoff.close(a.dispatch, a.report, load(a.input)),
              "ticket-stage": lambda a: ticket_execution.prepare_stage(a.dispatch, load(a.input)),
              "ticket-deliver": lambda a: ticket_execution.deliver(a.dispatch, a.output),
              "ticket-adapt-plan": ticket_execution.adapt_plan,
              "ticket-assemble": ticket_execution.assemble_stage,
              "implementer-assemble": ticket_execution.implementer_assemble,
              "implementer-check": lambda a: ticket_execution.implementer_check(a.dispatch, a.report),
              "implementer-accept": lambda a: ticket_execution.accept_implementer(a.dispatch, a.report, a.receipt, load(a.closure) if a.closure else None),
              "begin-gate-repair": gate_repair.begin,
              'final-deliver': lambda a: finalization.deliver(a.dispatch, a.output),
              'fixer-assemble': lambda a: finalization.fixer_assemble(a.dispatch, a.draft, a.output),
              'fixer-check': lambda a: finalization.fixer_check(a.dispatch, a.report),
              'fixer-accept': lambda a: finalization.accept_fixer(a.dispatch, a.report, a.receipt, load(a.closure) if a.closure else None),
              'final-gates': lambda a: final_state.gates(dispatch(a.dispatch), **load(a.input)),
              "final-stage": lambda a: finalization.prepare_stage(a.dispatch, load(a.input)),
              "final-assemble": lambda a: finalization.assemble(a.dispatch, a.draft, a.output),
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

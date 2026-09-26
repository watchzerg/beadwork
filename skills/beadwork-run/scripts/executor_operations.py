#!/usr/bin/env python3
"""ticket 开工、implementer 提交检查、阶段调度及报告组装；仅写证据，不派发 agent。"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from pathlib import Path

sys.dont_write_bytecode = True

import dispatch_contract
import document_closeout
import document_sync
import evidence
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
            repository.require(
                state["head"] == d["base_commit"] and not repository.status(d["worktree"]),
                "新票派发后现场已变化",
            )
        for key in ("report_schema_path", "receipt_schema_path", "expected_plan_path"):
            load(absolute(d[key]))
        for name, command, identity in (
            ("ticket", "show", d["ticket_id"]),
            ("comments", "comments", d["ticket_id"]),
            ("parent", "show", d["parent_id"]),
        ):
            raw = repository.run(["bd", command, identity, "--json"], d["worktree"])
            target = directory / (name + ".json")
            try:
                value = evidence.loads(raw)
                repository.require(isinstance(value, list), name + " 必须返回数组")
                if command == "show":
                    repository.require(
                        len(value) == 1 and value[0].get("id") == identity, name + " 身份不符"
                    )
                    if name == "ticket":
                        repository.require(
                            value[0].get("status") == "in_progress",
                            "ticket 未处于 in_progress",
                        )
                    description = value[0].get("description")
                    repository.require(
                        isinstance(description, str) and description.strip(),
                        name + " description 缺失",
                    )
            except Exception:
                evidence.write(target, raw)
                result["sources"][name] = evidence.binding(target)
                raise
            if command == "show":
                evidence.write(target, without_descriptions(value))
                result["sources"][name] = evidence.binding(target)
                result["sources"][name + "_description"] = evidence.binding(
                    description_source(d, description)
                )
            else:
                evidence.write(target, raw)
                result["sources"][name] = evidence.binding(target)
        result["commits"] = repository.git(
            d["worktree"], "log", "--reverse", "--format=%H %s", d["base_commit"] + "..HEAD"
        ).splitlines()
        result["ok"] = True
    except Exception as error:
        result.update(ok=False, error=str(error))
        evidence.write(directory / "inspection.json", result)
        fail(json.dumps(result, ensure_ascii=False))
    evidence.write(directory / "inspection.json", result)
    return result


def without_descriptions(value):
    if isinstance(value, dict):
        return {
            key: without_descriptions(item) for key, item in value.items() if key != "description"
        }
    if isinstance(value, list):
        return [without_descriptions(item) for item in value]
    return value


def description_source(d, description):
    data = description.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    directory = handoff.context_root(d) / "context-content"
    directory.mkdir(exist_ok=True)
    target = directory / (digest + ".md")
    if target.exists():
        repository.require(target.read_bytes() == data, "上下文正文内容寻址冲突")
    else:
        try:
            evidence.write(target, description)
        except FileExistsError:
            repository.require(target.read_bytes() == data, "上下文正文内容寻址冲突")
    return target


def check_layer(args):
    d = dispatch(args.dispatch)
    if d.get("ticket_scope"):
        ticket_state.require_writer(d)
    layer = load(absolute(args.input))
    repository.require(set(layer) == {"files", "message"}, "本层输入仅包含 files 和 message")
    files = layer["files"]
    repository.require(
        isinstance(files, list) and files and all(isinstance(p, str) and p for p in files),
        "files 必须为非空路径列表",
    )
    repository.require(len(set(files)) == len(files), "files 有重复路径")
    for name in files:
        repository.require(
            not Path(name).is_absolute() and all(p not in ("", ".", "..") for p in name.split("/")),
            "需要规范的 worktree 相对文件路径",
        )
        repository.require(name != ".beads" and not name.startswith(".beads/"), "不得提交 .beads")
    message = layer["message"]
    repository.require(
        isinstance(message, str)
        and re.search(
            r"(?<![A-Za-z0-9._-])" + re.escape(d["ticket_id"]) + r"(?![A-Za-z0-9._-])", message
        ),
        "commit message 必须包含完整 ticket_id",
    )
    state = workspace(d)
    repository.require(set(state["staged"]) == set(files), "staged 路径与本层 files 不一致")
    repository.require(
        not set(files).intersection(state["unstaged"] + state["untracked"]),
        "本层路径仍有未暂存内容",
    )
    return {"ok": True, **state, "remaining": sorted(set(state["unstaged"] + state["untracked"]))}


assemble = ticket_reports.assemble


def execute(args):
    """执行已经由统一 CLI 解析的 executor 命令。"""
    action = {
        "context-add": lambda a: handoff.add_context(a.dispatch, load(a.input)),
        "handoff-close": lambda a: handoff.close(a.dispatch, a.report, load(a.input)),
        "ticket-stage": lambda a: ticket_execution.prepare_stage(a.dispatch, load(a.input)),
        "ticket-deliver": lambda a: ticket_execution.deliver(a.dispatch, a.output),
        "ticket-adapt-plan": ticket_execution.adapt_plan,
        "ticket-assemble": ticket_execution.assemble_stage,
        "implementer-assemble": ticket_execution.implementer_assemble,
        "implementer-check": lambda a: ticket_execution.implementer_check(a.dispatch, a.report),
        "implementer-accept": lambda a: ticket_execution.accept_implementer(
            a.dispatch, a.report, a.receipt, handoff.acceptance_closure(a)
        ),
        "begin-gate-repair": gate_repair.begin,
        "final-deliver": lambda a: finalization.deliver(a.dispatch, a.output),
        "fixer-assemble": lambda a: finalization.fixer_assemble(a.dispatch, a.draft, a.output),
        "fixer-check": lambda a: finalization.fixer_check(a.dispatch, a.report),
        "fixer-accept": lambda a: finalization.accept_fixer(
            a.dispatch, a.report, a.receipt, handoff.acceptance_closure(a)
        ),
        "document-closeout-prepare": lambda a: document_closeout.prepare(a.dispatch, load(a.input)),
        "document-closeout-accept": lambda a: document_closeout.accept(
            a.dispatch, a.report, a.receipt, load(a.input), handoff.acceptance_closure(a)
        ),
        "document-assemble": lambda a: document_sync.assemble(a.dispatch, a.draft, a.output),
        "document-check": lambda a: document_sync.check(a.dispatch, a.report),
        "document-accept": lambda a: document_sync.accept(
            a.dispatch, a.report, a.receipt, handoff.acceptance_closure(a)
        ),
        "final-stage": lambda a: finalization.prepare_stage(a.dispatch, load(a.input)),
        "final-assemble": lambda a: finalization.assemble(a.dispatch, a.draft, a.output),
        "inspect": inspect_context,
        "check-layer": check_layer,
        "review-prepare": prepare_review,
        "review-collect": collect_review,
        "assemble": assemble,
        "check": lambda a: check_report(a.dispatch, a.report),
    }
    return action[args.command](args)

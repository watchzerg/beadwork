"""为 reviewer 生成可复核的紧凑验证视图，完整来源另行绑定。"""

from __future__ import annotations

import shlex
from collections import defaultdict
from pathlib import Path

import evidence
import repository
import verification_records

VERSION = 1


def _record(item):
    _, started, _, result, _ = verification_records.read(item)
    before = started["before"]
    valid = bool(
        result
        and result["outcome"] == "exited"
        and result["process_group_gone"] is True
        and before == result["after"]
        and type(result["exit_code"]) is int
        and result["exit_code"] >= 0
    )
    return {
        "run_path": item["directory"],
        "command": shlex.join(started["argv"]),
        "recipe": started["argv"][3],
        "head_commit": before["head"],
        "dirty": bool(before["status"]),
        "started_ns": started["started_ns"],
        "delivery_attempt": started.get("delivery_attempt"),
        "outcome": result["outcome"] if result else "unknown",
        "exit_code": result["exit_code"] if result else None,
        "duration_seconds": result["duration_seconds"] if result else None,
        "passed": bool(valid and result["exit_code"] == 0),
    }


def build(sources, reviewed_head, notes, context_source, source_manifest):
    repository.require(isinstance(notes, dict), "review verification notes 无效")
    rows = sorted(
        ((_record(item), item) for item in sources),
        key=lambda pair: (pair[0]["started_ns"], pair[0]["run_path"]),
    )
    reasons = defaultdict(set)
    by_command = defaultdict(list)
    by_delivery = defaultdict(list)
    for index, (row, _) in enumerate(rows):
        by_command[row["command"]].append(index)
        if row["delivery_attempt"] is not None and row["head_commit"] == reviewed_head:
            by_delivery[row["recipe"]].append(index)
        if row["run_path"] in notes:
            reasons[index].add("verification_note")
        if row["outcome"] == "unknown":
            reasons[index].add("unknown_result")
    for indexes in by_command.values():
        failures = [index for index in indexes if not rows[index][0]["passed"]]
        if failures:
            reasons[failures[0]].add("earliest_failure")
        reasons[indexes[-1]].add("latest_command_result")
        current = [index for index in indexes if rows[index][0]["head_commit"] == reviewed_head]
        if current:
            reasons[current[-1]].add("latest_reviewed_head_result")
    for indexes in by_delivery.values():
        reasons[indexes[-1]].add("latest_delivery_attempt")
    entries = []
    selected = []
    for index, (row, item) in enumerate(rows):
        why = sorted(reasons[index])
        entries.append({**row, "selected_reasons": why})
        if why:
            selected.append(item)
    return {
        "version": VERSION,
        "reviewed_head": reviewed_head,
        "context_source": context_source,
        "source_manifest": source_manifest,
        "entries": entries,
        "selected_sources": selected,
    }


def publish(directory, sources, reviewed_head, notes, context_source, publish_or_match):
    manifest = Path(directory) / "verification-sources.json"
    publish_or_match(manifest, sources)
    manifest_source = evidence.binding(manifest)
    view = Path(directory) / "verification-view.json"
    publish_or_match(
        view,
        build(sources, reviewed_head, notes, context_source, manifest_source),
    )
    return evidence.binding(view)


def check(dispatch):
    source = dispatch.get("verification_view_source")
    repository.require(source, "reviewer 缺少 verification view")
    view = evidence.read(evidence.bound(source))
    repository.require(view.get("version") == VERSION, "verification view 版本无效")
    repository.require(view.get("reviewed_head") == dispatch["reviewed_head"], "view HEAD 不符")
    evidence.bound(view["context_source"])
    sources = evidence.read(evidence.bound(view["source_manifest"]))
    notes = {}
    writer = dispatch.get("writer_source")
    expected_context = dispatch["stage_source"]
    expected_sources = []
    if writer:
        report = evidence.read(evidence.bound(writer["report"]))
        notes = report.get("verification_notes", {})
        expected_context = writer["report"]
        expected_sources = list(report.get("verification_sources", []))
    if dispatch["scope"] == "batch":
        stage = evidence.bound(dispatch["stage_source"])
        expected_sources += [
            item for item in verification_records.snapshot(stage) if item not in expected_sources
        ]
    repository.require(sources == expected_sources, "verification source manifest 不完整")
    repository.require(view["context_source"] == expected_context, "view 上下文来源不符")
    expected = build(
        sources,
        dispatch["reviewed_head"],
        notes,
        view["context_source"],
        view["source_manifest"],
    )
    repository.require(view == expected, "verification view 与完整来源不符")
    return view

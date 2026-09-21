"""为后续 ticket stage 生成可复核的当前修复上下文。"""

from __future__ import annotations

from pathlib import Path

import evidence
import repository
import review_context
import ticket_state

VERSION = 1


def _transition(dispatch):
    previous = dispatch.get("previous_stage")
    if dispatch.get("stage_recovery"):
        recovery = evidence.read(evidence.bound(dispatch["stage_recovery"]))
        if recovery.get("selected_stage") == previous:
            return "recover"
    if dispatch.get("stage_extension"):
        extension = evidence.read(evidence.bound(dispatch["stage_extension"]))
        if extension.get("selected_stage") == previous:
            return "extend"
    return "repair"


def _blocking_findings(report):
    final = (report.get("review") or {}).get("final", {})
    return [
        finding
        for axis in ("standards", "spec")
        for finding in final.get(axis, {}).get("findings", [])
        if finding.get("blocking") is True
    ]


def _check_review_source(source):
    collection = evidence.read(evidence.bound(source))
    round_record = evidence.read(evidence.bound(collection["round"]))
    evidence.bound(round_record["dispatch"])
    if round_record.get("acceptance_evidence"):
        evidence.bound(round_record["acceptance_evidence"])
    for axis_dispatch in round_record["axes"].values():
        evidence.bound(axis_dispatch)
    for axis_sources in collection["sources"].values():
        for item in axis_sources.values():
            evidence.bound(item)


def _sources(dispatch, *, validate_sources=False):
    previous_source = dispatch.get("previous_stage")
    repository.require(previous_source, "后续 stage 缺少前阶段来源")
    previous, report = ticket_state.resolve_source(previous_source)
    implementers = report.get("execution", {}).get("implementers", [])
    writer_source = implementers[-1] if implementers else None
    review_sources = (report.get("review") or {}).get("sources", [])
    review_source = review_sources[-1] if review_sources else None
    if validate_sources:
        if writer_source:
            ticket_state.resolve_source(writer_source)
        if review_source:
            _check_review_source(review_source)
    return previous, report, writer_source, review_source


def _verification(directory, report, writer_source):
    sources = []
    notes = {}
    context_source = report["execution"]["stage_dispatch"]
    if writer_source:
        writer = evidence.read(evidence.bound(writer_source["report"]))
        sources = list(writer.get("verification_sources", []))
        notes = writer.get("verification_notes", {})
        context_source = writer_source["report"]
    manifest = Path(directory) / "active-verification-sources.json"
    evidence.write(manifest, sources)
    manifest_source = evidence.binding(manifest)
    view = Path(directory) / "active-verification-view.json"
    evidence.write(
        view,
        review_context.build(
            sources,
            report["head_commit"],
            notes,
            context_source,
            manifest_source,
        ),
    )
    return evidence.binding(view)


def build(dispatch, verification_view_source):
    previous, report, writer_source, review_source = _sources(dispatch)
    return {
        "version": VERSION,
        "kind": "active-stage-context",
        "ticket_id": dispatch["ticket_id"],
        "continuation": _transition(dispatch),
        "from_stage": previous["stage"],
        "stage": dispatch["stage"],
        "base_commit": dispatch["base_commit"],
        "stage_base": dispatch["stage_base"],
        "previous_head": report["head_commit"],
        "previous_stage_source": dispatch["previous_stage"],
        "previous_implementer_source": writer_source,
        "selected_review_source": review_source,
        "verification_view_source": verification_view_source,
        "transition_evidence": {
            "recovery": dispatch.get("stage_recovery"),
            "extension": dispatch.get("stage_extension"),
        },
        "status": report["status"],
        "outcome": report["outcome"],
        "blockers": report["blockers"],
        "requested_context": report["requested_context"],
        "concerns": report["concerns"],
        "blocking_findings": _blocking_findings(report),
    }


def publish(directory, dispatch):
    _, report, writer_source, _ = _sources(dispatch, validate_sources=True)
    verification_view_source = _verification(directory, report, writer_source)
    path = Path(directory) / "active-stage-context.json"
    evidence.write(path, build(dispatch, verification_view_source))
    source = evidence.binding(path)
    check({**dispatch, "active_stage_context_source": source})
    return source


def check(dispatch, *, validate_sources=False):
    source = dispatch.get("active_stage_context_source")
    if dispatch.get("stage") == 0:
        repository.require(source is None, "stage 0 不应包含 active stage context")
        return None
    repository.require(source, "后续 stage 缺少 active stage context")
    context = evidence.read(evidence.bound(source))
    repository.require(context.get("version") == VERSION, "active stage context 版本无效")
    view_source = context.get("verification_view_source")
    view = evidence.read(evidence.bound(view_source))
    manifest = evidence.read(evidence.bound(view["source_manifest"]))
    _, report, writer_source, _ = _sources(dispatch, validate_sources=validate_sources)
    sources = []
    notes = {}
    expected_context = report["execution"]["stage_dispatch"]
    if writer_source:
        writer = evidence.read(evidence.bound(writer_source["report"]))
        sources = list(writer.get("verification_sources", []))
        notes = writer.get("verification_notes", {})
        expected_context = writer_source["report"]
    repository.require(manifest == sources, "active verification source manifest 不完整")
    expected_view = review_context.build(
        sources,
        report["head_commit"],
        notes,
        expected_context,
        view["source_manifest"],
    )
    repository.require(view == expected_view, "active verification view 与来源不符")
    repository.require(
        context == build(dispatch, view_source), "active stage context 与前阶段来源不符"
    )
    repository.require(
        context["from_stage"] + 1 == context["stage"]
        and context["stage_base"] == context["previous_head"],
        "active stage context 的阶段或 HEAD 不连续",
    )
    return context

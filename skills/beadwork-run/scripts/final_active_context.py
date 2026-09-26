"""最终修复的当前失败视图；累计报告继续作为可复核来源。"""

from pathlib import Path

import evidence
import repository
import review_context


def inputs(dispatch):
    source = dispatch["previous_result"]
    report = evidence.read(evidence.bound(source))
    stage_source = dispatch["previous_stages"][-1]
    previous = evidence.read(evidence.bound(stage_source))
    repository.require(
        all(
            previous[key] == dispatch[key]
            for key in ("parent_id", "attempt_id", "reviewed_main", "worktree")
        )
        and report["attempt_id"] == dispatch["attempt_id"]
        and report["stage"] == previous["stage"] == dispatch["stage"] - 1
        and report["head_commit"] == dispatch["stage_base"]
        and report["outcome"] == "code_failure"
        and report["stage_sources"][-1] == stage_source,
        "最终修复上下文的阶段、身份或 HEAD 不连续",
    )
    evidence.bound(dispatch["previous_receipt"])
    writers = report["fix_sources"] if previous["stage"] else report["document_sources"]
    writer = writers[-1] if writers else None
    directories = {Path(stage_source["path"]).parent}
    dispositions = []
    if writer:
        wd = evidence.read(evidence.bound(writer["dispatch"]))
        wr = evidence.read(evidence.bound(writer["report"]))
        evidence.bound(writer["receipt"])
        repository.require(wd["stage"] == previous["stage"], "当前失败缺少对应 writer")
        directories.add(Path(writer["dispatch"]["path"]).parent)
        dispositions = wr.get("dispositions", [])
    sources = [
        item
        for item in report["verification_sources"]
        if Path(item["directory"]).parent in directories
    ]
    notes = {
        key: value
        for key, value in report.get("verification_notes", {}).items()
        if key in {item["directory"] for item in sources}
    }
    review = None
    findings = []
    if report["review_sources"]:
        candidate = report["review_sources"][-1]
        collection = evidence.read(evidence.bound(candidate))
        round_record = evidence.read(evidence.bound(collection["round"]))
        review_stage_source = round_record["dispatch"]
        repository.require(
            review_stage_source in report["stage_sources"], "最终修复 review 不属于阶段来源"
        )
        review_stage = evidence.read(evidence.bound(review_stage_source))["stage"]
        review = candidate
        for axis in ("standards", "spec"):
            for binding in collection["sources"][axis].values():
                evidence.bound(binding)
            findings += [f for f in collection["pair"][axis]["findings"] if f["blocking"]]
        dispositions = []
        for fix in report["fix_sources"]:
            fd = evidence.read(evidence.bound(fix["dispatch"]))
            if fd["stage"] > review_stage:
                fr = evidence.read(evidence.bound(fix["report"]))
                evidence.bound(fix["receipt"])
                dispositions.extend(fr.get("dispositions", []))
    return report, writer, dispositions, sources, notes, review, findings


def build(dispatch, view_source):
    report, writer, dispositions, _, _, review, findings = inputs(dispatch)
    return {
        "kind": "final-active-stage-context",
        "parent_id": dispatch["parent_id"],
        "attempt_id": dispatch["attempt_id"],
        "stage": dispatch["stage"],
        "stage_base": dispatch["stage_base"],
        "previous_report_source": dispatch["previous_result"],
        "previous_writer_source": writer,
        "selected_review_source": review,
        "verification_view_source": view_source,
        "blockers": report["blockers"],
        "remaining_work": report["remaining_work"],
        "document_closeout": report.get("document_closeout"),
        "blocking_findings": findings,
        "previous_dispositions": dispositions,
        "document_source": report["document_sources"][-1],
    }


def publish(directory, dispatch):
    directory = Path(directory) / "active-context"
    directory.mkdir()
    report, _, _, sources, notes, _, _ = inputs(dispatch)
    view = review_context.publish(
        directory,
        sources,
        report["head_commit"],
        notes,
        dispatch["previous_result"],
        evidence.write,
    )
    path = Path(directory) / "active-stage-context.json"
    evidence.write(path, build(dispatch, view))
    return evidence.binding(path)


def check(dispatch):
    if dispatch.get("role") == "fixer":
        stage = evidence.read(evidence.bound(dispatch["stage_dispatch"]))
        repository.require(
            all(
                dispatch[key] == stage[key]
                for key in (
                    "parent_id",
                    "attempt_id",
                    "stage",
                    "stage_base",
                    "active_stage_context_source",
                )
            ),
            "fixer 当前上下文与阶段不符",
        )
        dispatch = stage
    context = evidence.read(evidence.bound(dispatch["active_stage_context_source"]))
    report, _, _, sources, notes, _, _ = inputs(dispatch)
    view_source = context["verification_view_source"]
    view = evidence.read(evidence.bound(view_source))
    repository.require(
        evidence.read(evidence.bound(view["source_manifest"])) == sources,
        "最终修复验证来源不完整",
    )
    repository.require(
        view
        == review_context.build(
            sources,
            report["head_commit"],
            notes,
            dispatch["previous_result"],
            view["source_manifest"],
        )
        and context == build(dispatch, view_source),
        "最终修复上下文与来源不符",
    )
    return context

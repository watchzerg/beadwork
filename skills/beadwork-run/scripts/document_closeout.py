"""review 后一次性文档收尾；保留原 gate/review，绑定限定修复与派发者验收。"""

from pathlib import Path

import dispatch_contract
import evidence
import final_state
import handoff
import repository
import review_evidence
import ticket_state
import workflow_contract
from schema_validation import TEXT, TEXTS, object_schema, schema_errors


def schema():
    binding = object_schema({"path": TEXT, "sha256": TEXT})
    return {
        "anyOf": [
            object_schema(
                {"dispatch": binding, "acceptance": {"anyOf": [binding, {"type": "null"}]}}
            ),
            {"type": "null"},
        ]
    }


def selected(d, current=False):
    if d.get("ticket_scope"):
        state, _, _ = ticket_state.checkpoints(d)
        if current:
            repository.require(
                state["stage_dispatch"] == evidence.binding(d["dispatch_path"]),
                "文档收尾需要当前 stage",
            )
        return state.get("document_closeouts", {}).get(d["dispatch_path"])
    return final_state.selected(d, current=current)[1].get("document_closeout")


def save(d, value, record=None):
    if d.get("ticket_scope"):
        state, _, _ = ticket_state.checkpoints(d)
        repository.require(
            state["stage_dispatch"] == evidence.binding(d["dispatch_path"]), "只能更新当前 stage"
        )
        state.setdefault("document_closeouts", {})[d["dispatch_path"]] = value
        state["selected_stage"] = None
        ticket_state.checkpoint(d, state)
    else:
        state, item = final_state.selected(d)
        item["document_closeout"] = value
        item["report"] = None
        if record:
            item["documents"].append(
                {key: record[key] for key in ("dispatch", "report", "receipt")}
            )
            item["closures"][record["report"]["sha256"]] = record["closure"]
        final_state.save(d, state)


def review_source(d):
    if d.get("ticket_scope"):
        return ticket_state.checkpoints(d)[0]["selected_review"]
    return final_state.selected(d)[1]["review"]


def prepare(dispatch_path, facts):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(
        d["role"] in ("executor", "finalizer") and "stage" in d, "文档收尾由 stage 协调者派发"
    )
    repository.require(not selected(d, current=True), "本阶段文档收尾已派发；不得自动再派一轮")
    errors = schema_errors(facts, object_schema({"files": TEXTS, "reason": TEXT}))
    repository.require(not errors, "需要文档路径清单和范围依据：" + "; ".join(errors))
    for name in facts["files"]:
        path = Path(name)
        repository.require(
            not path.is_absolute()
            and ".." not in path.parts
            and name not in ("", ".")
            and path.parts[0] not in (".git", ".beads"),
            "文档路径必须为 worktree 内明确文件",
        )
        repository.require(
            (Path(d["worktree"]) / path).resolve().is_relative_to(Path(d["worktree"]).resolve()),
            "文档路径越出 worktree",
        )
    source = review_source(d)
    repository.require(source, "文档收尾需要当前完整双轴 review")
    pair, _ = review_evidence.collection(str(evidence.bound(source)), dispatch_path)
    repository.require(
        review_evidence.repair_route(pair) == "docs", "只有全部阻塞项为 docs 才能文档收尾"
    )
    head = pair["spec"]["reviewed_head"]
    repository.topology(d)
    repository.require(
        repository.sha(d["worktree"], "HEAD") == head and not repository.status(d["worktree"]),
        "文档收尾必须从原干净 review HEAD 开始",
    )
    import document_sync

    path = document_sync.publish(d, dict(facts, review=source, head=head))
    value = {"dispatch": evidence.binding(path), "acceptance": None}
    save(d, value)
    assessment_schema = Path(path).parent / "acceptance-schema.json"
    evidence.write(assessment_schema, acceptance_schema())
    return {
        "acceptance_schema_path": str(assessment_schema),
        "document_dispatch": path,
        "document_launch_context": workflow_contract.launch_context(evidence.read(path)),
        "document_closeout": value,
    }


def check_writer(writer, stage, current=False):
    value = selected(stage, current=current)
    repository.require(
        value and value["dispatch"] == evidence.binding(writer["dispatch_path"]),
        "不是本阶段文档收尾 writer",
    )
    facts = writer["closeout_input"]
    pair, _ = review_evidence.collection(
        str(evidence.bound(facts["review"])), stage["dispatch_path"]
    )
    repository.require(
        review_evidence.repair_route(pair) == "docs"
        and pair["spec"]["reviewed_head"] == writer["base_commit"] == facts["head"],
        "文档收尾原 review 或 BASE 不符",
    )
    # 历史阶段不重新选择；当前阶段仍须保留派发时的 review。
    if current:
        repository.require(review_source(stage) == facts["review"], "文档收尾原 review 已变化")
    return value


def require_writer(writer):
    stage = dispatch_contract.dispatch(str(evidence.bound(writer["stage_dispatch"])))
    value = check_writer(writer, stage, current=True)
    repository.require(not value["acceptance"], "文档收尾已验收，不能再次写入或派发")


def acceptance_schema():
    return object_schema(
        {
            "outcome": {"enum": ["passed", "blocked", "code_required"]},
            "dispositions": {
                "type": "array",
                "items": object_schema(
                    {
                        "axis": {"enum": ["standards", "spec"]},
                        "finding_index": {"type": "integer", "minimum": 0},
                        "resolved": {"type": "boolean"},
                        "evidence": TEXT,
                    }
                ),
            },
            "scope_evidence": TEXT,
            "checks_evidence": TEXT,
            "blockers": TEXTS,
        }
    )


def check_acceptance(writer, record, report):
    facts = record["assessment"]
    errors = schema_errors(facts, acceptance_schema())
    repository.require(not errors, "文档定点验收字段无效：" + "; ".join(errors))
    stage = evidence.read(evidence.bound(writer["stage_dispatch"]))
    pair, _ = review_evidence.collection(
        str(evidence.bound(writer["closeout_input"]["review"])), stage["dispatch_path"]
    )
    expected = {
        (axis, i) for axis, r in pair.items() for i, f in enumerate(r["findings"]) if f["blocking"]
    }
    rows = facts["dispositions"]
    actual = [(row["axis"], row["finding_index"]) for row in rows]
    repository.require(
        len(actual) == len(set(actual)) and set(actual) == expected,
        "定点验收必须逐项覆盖全部原文档 findings",
    )
    if facts["outcome"] == "passed":
        repository.require(
            report["status"] == "DONE"
            and all(row["resolved"] for row in rows)
            and not facts["blockers"],
            "文档 findings 或检查尚未完成",
        )
        repository.require(
            set(report["changed_files"]) <= set(writer["closeout_input"]["files"]),
            "文档修改超出派发范围，不能复用原代码 gate",
        )
        # 所有提交都受范围约束，不能通过后续 revert 隐藏越界修改。
        touched = repository.git(
            writer["worktree"],
            "log",
            "--format=",
            "--name-only",
            "--no-renames",
            "-z",
            writer["base_commit"] + ".." + report["head_commit"],
        ).split("\0")[:-1]
        repository.require(
            set(touched) <= set(writer["closeout_input"]["files"]), "文档提交包含越界修改"
        )
    else:
        repository.require(facts["blockers"], "未通过文档收尾必须说明阻塞或代码修复依据")
    closure = handoff.check_close(
        writer["dispatch_path"], str(evidence.bound(record["report"])), record["closure"]
    )
    if facts["outcome"] in ("passed", "code_required"):
        repository.require(
            report["stopped_tasks"] and closure["stopped"] and not closure["unresolved"],
            "推进前必须确认文档任务停止",
        )
        repository.require(report["worktree_clean"], "推进前文档现场必须干净")


def accept(stage_path, report_path, receipt_path, facts, closure):
    stage = dispatch_contract.dispatch(stage_path)
    value = selected(stage, current=True)
    repository.require(value and not value["acceptance"], "没有待验收文档收尾，或本轮已结束")
    writer = dispatch_contract.dispatch(str(evidence.bound(value["dispatch"])))
    import document_sync

    document_sync.check(writer["dispatch_path"], report_path, receipt_path)
    record = {
        "dispatch": value["dispatch"],
        "report": evidence.binding(report_path),
        "receipt": evidence.binding(receipt_path),
        "closure": handoff.closure_binding(closure),
        "assessment": facts,
    }
    check_acceptance(writer, record, evidence.read(report_path))
    path = Path(writer["dispatch_path"]).parent / "acceptance.json"
    evidence.write(path, record)
    value["acceptance"] = evidence.binding(path)
    save(stage, value, record)
    return {"accepted": True, "outcome": facts["outcome"], "document_closeout": value}


def validate(report):
    """供报告与独立 verifier 共用；没有有效收尾时绝不放宽 HEAD 或 PASS。"""
    value = report.get("document_closeout")
    if not value:
        return None
    writer = dispatch_contract.dispatch(str(evidence.bound(value["dispatch"])))
    repository.require(writer.get("document_mode") == "review_closeout", "需要文档收尾来源")
    stage = dispatch_contract.dispatch(str(evidence.bound(writer["stage_dispatch"])))
    repository.require(selected(stage) == value, "报告遗漏或改写文档收尾选择")
    check_writer(writer, stage)
    stage_source = (report.get("execution") or {}).get("stage_dispatch") or report.get(
        "stage_sources", [None]
    )[-1]
    repository.require(stage_source == writer["stage_dispatch"], "文档收尾不属于交付阶段")
    reviews = (report.get("review") or {}).get("sources", report.get("review_sources", []))
    repository.require(
        reviews and reviews[-1] == writer["closeout_input"]["review"], "交付未保留文档收尾原 review"
    )
    result = {"head": writer["base_commit"], "outcome": "pending"}
    if value["acceptance"]:
        record = evidence.read(evidence.bound(value["acceptance"]))
        repository.require(record["dispatch"] == value["dispatch"], "文档验收属于其他 writer")
        import document_sync

        document_sync.check(
            writer["dispatch_path"],
            str(evidence.bound(record["report"])),
            str(evidence.bound(record["receipt"])),
            live=False,
        )
        r = evidence.read(evidence.bound(record["report"]))
        check_acceptance(writer, record, r)
        repository.require(r["head_commit"] == report["head_commit"], "文档收尾未覆盖交付 HEAD")
        result["outcome"] = record["assessment"]["outcome"]
    if report.get("outcome") == "passed" or report["status"] in ("DONE", "READY_TO_MERGE"):
        repository.require(result["outcome"] == "passed", "文档收尾未通过，不得完成交付")
    if report.get("outcome") == "code_failure":
        repository.require(result["outcome"] == "code_required", "仅文档阻塞不能启动代码修复 stage")
    return result


def candidate_head(report):
    result = validate(report)
    return result["head"] if result else report["head_commit"]

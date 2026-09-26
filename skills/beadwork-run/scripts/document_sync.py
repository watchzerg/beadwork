"""文档同步 writer 的派发、报告与验收；复用最终阶段证据和收尾机制。"""

from pathlib import Path

import dispatch_contract
import document_closeout
import draft_contracts
import evidence
import final_state as fs
import final_verification as fv
import handoff
import repository
import workflow_policy
from command_argv import beadwork_argv
from schema_validation import SHA, TEXT, TEXTS, object_schema, schema_errors

ROLE = "document-syncer"


def schema():
    fields = dict(draft_contracts.schema(ROLE)["properties"])
    fields.update(
        parent_id=TEXT,
        branch=TEXT,
        attempt_id={"anyOf": [TEXT, {"type": "null"}]},
        stage={"type": "integer", "minimum": 0},
        base_commit=SHA,
        head_commit=SHA,
        commits={"type": "array", "items": SHA, "uniqueItems": True},
        changed_files=TEXTS,
        worktree_clean={"type": "boolean"},
        verification={"type": "array", "items": {"type": "object"}},
        verification_sources={"type": "array", "items": {"type": "object"}},
        verification_issues={"type": "array", "items": {"type": "object"}},
    )
    return object_schema(fields)


def receipt_schema():
    return object_schema(
        {"status": {"enum": ["DONE", "BLOCKED"]}, "report_path": TEXT, "report_sha256": SHA}
    )


def publish(stage, closeout=None):
    if stage["stage"] != 0 and closeout is None:
        return None
    directory = Path(stage["dispatch_path"]).parent / ("document-closeout" if closeout else ROLE)
    directory.mkdir()
    d = dict(
        stage,
        role=ROLE,
        base_commit=stage["stage_base"],
        stage_dispatch=evidence.binding(stage["dispatch_path"]),
        **workflow_policy.DOCUMENT_SYNC_MODEL,
        dispatch_path=str(directory / "dispatch.json"),
        report_path=str(directory / "report.json"),
        report_schema_path=str(directory / "report-schema.json"),
        receipt_schema_path=str(directory / "receipt-schema.json"),
    )
    d.setdefault("attempt_id", None)
    if closeout:
        # 文档 BASE 是受审 HEAD；测试计划适配仍由绑定的 stage 校验。
        d.pop("plan_adjustment", None)
        d.update(
            document_mode="review_closeout", base_commit=closeout["head"], closeout_input=closeout
        )
    d["self_check_argv"] = beadwork_argv(
        "executor", "document-check", "--dispatch", d["dispatch_path"], "--report", d["report_path"]
    )
    draft_contracts.publish(d, ROLE)
    evidence.write(d["report_schema_path"], schema())
    evidence.write(d["receipt_schema_path"], receipt_schema())
    evidence.write(d["dispatch_path"], d)
    return d["dispatch_path"]


def git_facts(d, head):
    repository.git(d["worktree"], "merge-base", "--is-ancestor", d["base_commit"], head)
    span = d["base_commit"] + ".." + head
    return {
        "commits": repository.git(d["worktree"], "rev-list", "--reverse", span).splitlines(),
        "changed_files": repository.git(
            d["worktree"], "diff", "--name-only", "--no-renames", "-z", span
        ).split("\0")[:-1],
    }


def check(dispatch_path, report_path, receipt_path=None, *, live=True):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(d["role"] == ROLE, "需要文档同步 dispatch")
    stage = dispatch_contract.dispatch(str(evidence.bound(d["stage_dispatch"])))
    if d.get("document_mode") == "review_closeout":
        document_closeout.check_writer(d, stage, current=live)
    else:
        dispatch_contract.same_attempt(d, stage)
        _, selected = fs.selected(stage, current=live)
        repository.require(
            d["stage"] == 0
            and selected["document_syncer"] == evidence.binding(dispatch_path)
            and stage["stage_base"] == d["base_commit"],
            "文档同步 writer 或 BASE 不符",
        )
    for path in (report_path, receipt_path):
        if path:
            repository.require(Path(path).parent == Path(dispatch_path).parent, "文档报告目录不符")
    r, digest = evidence.read_with_digest(report_path)
    errors = schema_errors(r, schema())
    repository.require(not errors, "文档报告字段无效：" + "; ".join(errors))
    for key in ("parent_id", "branch", "attempt_id", "stage", "base_commit"):
        repository.require(r[key] == d[key], "文档报告身份不符：" + key)
    facts = git_facts(d, r["head_commit"])
    repository.require(all(r[k] == v for k, v in facts.items()), "文档提交或文件范围不完整")
    repository.check_batch_beads(d["worktree"], d["base_commit"], r["head_commit"])
    passed = r["status"] == "DONE"
    repository.require(passed == (r["outcome"] == "passed"), "文档同步状态与结果不符")
    if passed:
        repository.require(
            r["stopped_tasks"]
            and r["worktree_clean"]
            and not r["blockers"]
            and not r["remaining_work"]
            and r["inspected"]
            and r["summary"].strip(),
            "文档同步未完成检查或收尾",
        )
        repository.require(
            r["result"] == ("updated" if r["changed_files"] else "no_change_needed"),
            "文档同步结论与实际变更不符",
        )
    else:
        repository.require(r["result"] == "incomplete", "未完成同步不能声明完成结论")
    fv.check(d, r, live=live)
    receipt = {"status": r["status"], "report_path": str(report_path), "report_sha256": digest}
    if receipt_path:
        repository.require(evidence.read(receipt_path) == receipt, "文档回执与报告不符")
    if live:
        repository.topology(d)
        repository.require(
            repository.sha(d["worktree"], "HEAD") == r["head_commit"], "文档 HEAD 已变化"
        )
        repository.require(
            r["worktree_clean"] == (not repository.status(d["worktree"])), "文档现场与报告不符"
        )
        repository.require(not passed or r["worktree_clean"], "文档交付现场不干净")
    return receipt


def assemble(dispatch_path, draft_path, output):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(d["role"] == ROLE, "需要文档同步 dispatch")
    stage = evidence.read(evidence.bound(d["stage_dispatch"]))
    if d.get("document_mode") == "review_closeout":
        document_closeout.require_writer(d)
        selected = {"round_path": None, "documents": []}
    else:
        _, selected = fs.selected(stage)
    repository.require(not selected["round_path"], "review 已开始，文档报告不能重新选择")
    if selected["documents"]:
        prior = evidence.read(evidence.bound(selected["documents"][-1]["report"]))
        repository.require(prior["status"] != "DONE", "文档同步已完成")
        # 仅补写证据允许更正未知停止事实；源码写入仍受 require_writer 限制。
        repository.require(
            fs.document_stopped(selected)
            or prior["head_commit"] == repository.sha(d["worktree"], "HEAD"),
            "未知停止状态下不能改变文档候选",
        )
    r = draft_contracts.read(d, draft_path, ROLE)
    head = repository.sha(d["worktree"], "HEAD")
    r.update({key: d[key] for key in ("parent_id", "branch", "attempt_id", "stage", "base_commit")})
    r.update(
        head_commit=head, worktree_clean=not repository.status(d["worktree"]), **git_facts(d, head)
    )
    fv.populate(d, r)
    target = dispatch_contract.output_path(output, Path(dispatch_path).parent)
    evidence.write(target, r)
    return check(dispatch_path, str(target))


def accept(stage_path, report_path, receipt_path, closure=None):
    d = dispatch_contract.dispatch(stage_path)
    value, item = fs.selected(d)
    repository.require(d["stage"] == 0 and item["document_syncer"], "本阶段没有文档同步 writer")
    path = str(evidence.bound(item["document_syncer"]))
    check(path, report_path, receipt_path)
    handoff.check_close(path, report_path, closure)
    source = {
        k: evidence.binding(str(p))
        for k, p in (("dispatch", path), ("report", report_path), ("receipt", receipt_path))
    }
    if source in item["documents"]:
        return {"accepted": True, "source": source}
    repository.require(not item["round_path"], "review 后不能重新选择文档同步报告")
    if item["documents"]:
        prior = evidence.read(evidence.bound(item["documents"][-1]["report"]))
        repository.require(prior["status"] != "DONE", "文档同步已完成，不能重新交付")
        repository.require(
            fs.document_stopped(item)
            or prior["head_commit"] == evidence.read(report_path)["head_commit"],
            "未知停止状态下不能改变文档候选",
        )
    item["documents"].append(source)
    item["closures"][source["report"]["sha256"]] = closure
    item["report"] = None
    fs.save(d, value)
    return {"accepted": True, "source": source}


def read_sources(d, sources):
    commits = []
    for source in sources:
        paths = {k: str(evidence.bound(source[k])) for k in ("dispatch", "report", "receipt")}
        writer = dispatch_contract.dispatch(paths["dispatch"])
        dispatch_contract.same_attempt(d, writer)
        check(paths["dispatch"], paths["report"], paths["receipt"], live=False)
        stage = evidence.read(evidence.bound(writer["stage_dispatch"]))
        _, item = fs.selected(stage, current=False)
        repository.require(source in item["documents"], "文档来源未经验收")
        if writer.get("document_mode") == "review_closeout":
            selection = document_closeout.selected(stage)
            record = evidence.read(evidence.bound(selection["acceptance"]))
            repository.require(all(record[k] == source[k] for k in source), "文档收尾来源未经验收")
            document_closeout.check_acceptance(writer, record, evidence.read(paths["report"]))
        handoff.check_close(
            paths["dispatch"], paths["report"], item["closures"].get(source["report"]["sha256"])
        )
        r = evidence.read(paths["report"])
        commits += [c for c in r["commits"] if c not in commits]
    return commits


def require_done(d, sources, *, exact_head=False, head=None):
    repository.require(sources, "缺少已验收文档同步结果")
    read_sources(d, sources)
    # 批次同步前置条件由初始同步承担；后续收尾通过独立验收记录证明。
    initial = [
        s
        for s in sources
        if evidence.read(evidence.bound(s["dispatch"])).get("document_mode") != "review_closeout"
    ]
    repository.require(initial, "缺少初始批次文档同步")
    report = evidence.read(evidence.bound(initial[-1]["report"]))
    repository.require(report["status"] == "DONE", "文档同步尚未完成")
    head = head or repository.sha(d["worktree"], "HEAD")
    repository.git(d["worktree"], "merge-base", "--is-ancestor", report["head_commit"], head)
    repository.require(
        not exact_head or report["head_commit"] == head, "文档同步未覆盖 stage 0 HEAD"
    )

"""fixer 报告来源、组装与事实验收；不选择 fixer 或推进阶段。"""

from pathlib import Path

import dispatch_contract
import draft_contracts
import evidence
import final_state as fs
import final_verification as fv
import handoff
import repository


def read_fixer(source, current, tolerate_verification=False):
    paths = {key: str(evidence.bound(source[key])) for key in ("dispatch", "report", "receipt")}
    d, r = evidence.read(paths["dispatch"]), evidence.read(paths["report"])
    for key in ("parent_id", "branch"):
        repository.require(d[key] == current[key], "fixer 来源属于其他批次")
    if "attempt_id" in d:
        dispatch_contract.same_attempt(d, current)
        repository.require(d["stage"] <= current["stage"], "fixer 来源阶段超前")
        stage_dispatch = evidence.read(evidence.bound(d["stage_dispatch"]))
        repository.require(
            stage_dispatch["stage_base"] == d["base_commit"], "fixer BASE 与阶段不符"
        )
    for key in ("report", "receipt"):
        repository.require(
            Path(paths[key]).parent == Path(paths["dispatch"]).parent, "fixer 报告不在派发目录"
        )
    import worker_validation

    checked = worker_validation.check("fixer", paths["report"], paths["dispatch"], paths["receipt"])
    repository.require(
        checked["ok"]
        or (
            tolerate_verification
            and checked.get("failures")
            and all(f.startswith("fixer_verification: ") for f in checked["failures"])
        ),
        "fixer 验收失败",
    )
    repository.require(
        checked["report_sha256"] == source["report"]["sha256"] == evidence.digest(paths["report"]),
        "验收期间 fixer 报告发生变化",
    )
    if r["status"] == "DONE" or r.get("outcome") == "code_failure":
        repository.require(r["stopped_tasks"], "fixer 交付必须确认任务停止")
    if fs.strict(current):
        repository.require(fs.strict(d), "严格阶段不能复用未校验运行来源的 fixer")
        _, selection = fs.selected(stage_dispatch, current=False)
        handoff.check_close(
            paths["dispatch"],
            paths["report"],
            selection["closures"].get(source["report"]["sha256"]),
        )
    head = r["head_commit"]
    commits = r.get("fix_commits", [r["fix_commit"]] if r.get("fix_commit") else [])
    if head:
        repository.git(current["worktree"], "merge-base", "--is-ancestor", d["base_commit"], head)
        actual = repository.git(
            current["worktree"], "rev-list", "--reverse", d["base_commit"] + ".." + head
        ).splitlines()
        repository.require(commits == actual, "fixer 提交列表与实际阶段范围不符")
    return d, r, commits


def fixer_check(dispatch_path, report_path, receipt_path=None, live=True):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(d["role"] == "fixer" and fs.strict(d), "需要新版 fixer dispatch")
    repository.require(Path(report_path).parent == Path(dispatch_path).parent, "fixer 报告目录不符")
    if receipt_path:
        repository.require(
            Path(receipt_path).parent == Path(dispatch_path).parent, "fixer 回执目录不符"
        )
    import worker_validation

    checked = worker_validation.check("fixer", report_path, dispatch_path, receipt_path)
    repository.require(checked["ok"], "fixer 报告校验失败：" + str(checked.get("failures")))
    r, digest = evidence.read_with_digest(report_path)
    repository.require(digest == checked["report_sha256"], "验收期间 fixer 报告发生变化")
    if live:
        fv.check_snapshot(d, r)
    actual = repository.git(
        d["worktree"], "rev-list", "--reverse", d["base_commit"] + ".." + r["head_commit"]
    ).splitlines()
    repository.require(actual == r["fix_commits"], "fixer 提交列表不完整")
    repository.check_batch_beads(d["worktree"], d["base_commit"], r["head_commit"])
    if live:
        repository.topology(d)
        repository.require(
            repository.sha(d["worktree"], "HEAD") == r["head_commit"], "fixer 交付 HEAD 已变化"
        )
        repository.require(
            r["status"] != "DONE" or not repository.status(d["worktree"]), "fixer 成功需要干净现场"
        )
    return {"status": r["status"], "report_path": str(report_path), "report_sha256": digest}


def fixer_assemble(dispatch_path, draft_path, output):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(d["role"] == "fixer" and fs.strict(d), "需要新版 fixer dispatch")
    r = draft_contracts.read(d, draft_path, "fixer")
    head = repository.sha(d["worktree"], "HEAD")
    r.update(
        stage=d["stage"],
        attempt_id=d["attempt_id"],
        parent_id=d["parent_id"],
        branch=d["branch"],
        base_commit=d["base_commit"],
        head_commit=head,
        fix_commits=repository.git(
            d["worktree"], "rev-list", "--reverse", d["base_commit"] + ".." + head
        ).splitlines(),
        worktree_clean=not repository.status(d["worktree"]),
    )
    fv.populate(d, r)
    target = dispatch_contract.output_path(output, Path(dispatch_path).parent)
    evidence.write(target, r)
    return fixer_check(dispatch_path, str(target))

"""共享临时证据与工具级 stage fixture；不包含测试用例或真实项目数据。"""

import json
import uuid
from pathlib import Path

import dispatch_contract
import evidence
import gate_repair
import handoff
import report_io
import repository
import workflow_contract
import workflow_policy

SCRIPT = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"


def prepare_utility_stage(data):
    """为既有工具级测试构造 stage 输入；真实 root 调度另由公开 CLI 套件覆盖。"""
    d = dict(data)
    d.pop("primary_snapshot_path", None)
    repository.require(
        all(
            k in d
            for k in (
                "repository_root",
                "parent_id",
                "ticket_id",
                "mode",
                "test_mode",
                "approved_seams",
                "testing_seams_doc",
                "rules_paths",
            )
        ),
        "缺少必填字段",
    )
    root = repository.primary(d["repository_root"])
    d.update(
        repository_root=root,
        branch="implement/" + d["parent_id"],
        worktree=str(Path(root) / ".worktrees" / d["parent_id"]),
        skill_dir=str(SCRIPT.parent.parent),
        role="executor",
    )
    workflow_contract.stamp(d)
    repository.topology(d)
    head = repository.sha(d["worktree"], "HEAD")
    if d["mode"] == "new":
        repository.require(not repository.status(d["worktree"]), "新票需要干净现场")
        d["base_commit"] = head
    else:
        repository.require(d.get("base_commit"), "恢复需要 BASE")
        repository.git(d["worktree"], "merge-base", "--is-ancestor", d["base_commit"], head)
    previous = evidence.read(d["previous_dispatch"]) if d.get("previous_dispatch") else None
    if previous:
        dispatch_contract.validate_plan(previous)
        if previous.get("plan_adjustment"):
            repository.require(
                d["test_mode"] == previous["test_mode"]
                and d["approved_seams"] == previous["approved_seams"],
                "恢复须沿用已调整计划",
            )
            d["plan_adjustment"] = previous["plan_adjustment"]
        d["verification_dispatches"] = list(
            dict.fromkeys(previous.get("verification_dispatches", []) + [d["previous_dispatch"]])
        )
    number = d.pop("fixture_stage", 0)
    levels = dict(
        zip(workflow_policy.MODEL_ROLES, workflow_policy.STAGE_MODELS[number], strict=True)
    )
    if d.get("complex_ticket"):
        levels["executor"] = 2
        levels["standards"] = max(levels["standards"], 1)
    d.update(
        stage=number,
        start_head=head,
        prior_reviews=d.pop("fixture_reviews", []),
        models={role: workflow_policy.MODEL_LEVELS[level] for role, level in levels.items()},
    )
    folder = Path(root) / ".worktrees/.evidence" / d["parent_id"] / uuid.uuid4().hex
    folder.mkdir(parents=True)
    d.update(
        dispatch_path=str(folder / "dispatch.json"),
        report_path=str(folder / "report.json"),
        report_schema_path=str(folder / "report-schema.json"),
        receipt_schema_path=str(folder / "receipt-schema.json"),
        expected_plan_path=str(folder / "expected-plan.json"),
    )
    gate_repair.inherit(d, previous)
    evidence.write(
        d["expected_plan_path"], {"mode": d["test_mode"], "approved_seams": d["approved_seams"]}
    )
    evidence.write(d["report_schema_path"], report_io.verifier("executor", "--schema"))
    evidence.write(d["receipt_schema_path"], report_io.verifier("executor", "--receipt-schema"))
    evidence.write(d["dispatch_path"], d)
    return d


def closure_source(dispatch, report, *, observed_stopped=None):
    stopped = json.loads(Path(report).read_text()).get("stopped_tasks", True)
    if observed_stopped is not None:
        stopped = observed_stopped
    result = handoff.close(
        str(dispatch),
        str(report),
        {
            "task_id": "fixture-task",
            "stopped": stopped,
            "observed_at": "2026-09-16T00:00:00Z",
            "evidence": "测试 CLI 已退出",
            "unresolved": [],
        },
    )
    path = Path(dispatch).parent / ("closure-source-" + uuid.uuid4().hex + ".json")
    path.write_text(json.dumps(result["closure_source"]))
    return path

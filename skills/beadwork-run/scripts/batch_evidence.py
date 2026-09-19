"""批次恢复事实、ticket manifest 与停止/完成摘要的只读生成器。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import evidence


def require(value, message):
    if not value:
        raise ValueError(message)


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    require(result.returncode == 0, "git 查询失败：" + result.stderr.strip())
    return result.stdout.rstrip("\n")


def bd(root, *args):
    result = subprocess.run(
        ["bd", *args, "--readonly", "--json"], cwd=root, capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or "bd 查询失败"
    try:
        return json.loads(result.stdout), None
    except ValueError:
        return None, "bd 返回非法 JSON"


def inspect(repository_root, parent_id):
    root = evidence.absolute(repository_root)
    worktree = root / ".worktrees" / parent_id
    evidence_root = root / ".worktrees/.evidence" / parent_id
    pending, pointers = [], []
    if evidence_root.exists():
        for path in sorted(evidence_root.rglob("*.json")):
            if path.name.endswith("intent.json") or path.name == "intent.json":
                candidates = [
                    path.with_name(path.stem + "-result.json"),
                    path.parent / "ready.json",
                ]
                if not any(candidate.exists() for candidate in candidates):
                    pending.append(str(path))
            if (
                path.name.startswith("checkpoint-")
                or "accept" in path.name
                or path.name in ("ready.json", "merge.json")
            ):
                pointers.append(evidence.binding(path))
    worktrees = git(root, "worktree", "list", "--porcelain")
    branch = "implement/" + parent_id
    facts = {
        "repository_root": str(root),
        "parent_id": parent_id,
        "primary_head": git(root, "rev-parse", "HEAD"),
        "worktree": str(worktree),
        "worktree_exists": worktree.exists(),
        "branch": branch,
        "branch_exists": bool(
            git(root, "for-each-ref", "--format=%(refname)", "refs/heads/" + branch)
        ),
        "worktree_list": worktrees,
        "worktree_head": None,
        "worktree_status": None,
        "pending_operations": pending,
        "evidence_pointers": pointers,
        "external_stop_observation_required": True,
        "conflicts": [],
    }
    parent, parent_error = bd(root, "show", parent_id)
    comments, comments_error = bd(root, "comments", parent_id)
    facts.update(
        parent=parent,
        comments=comments,
        tracker_diagnostics=[error for error in (parent_error, comments_error) if error],
    )
    if worktree.exists():
        facts["worktree_head"] = git(worktree, "rev-parse", "HEAD")
        facts["worktree_status"] = git(
            worktree, "status", "--porcelain=v1", "--untracked-files=all"
        )
        if git(worktree, "symbolic-ref", "--short", "HEAD") != branch:
            facts["conflicts"].append("implementation worktree branch 不符")
    if len({Path(p).parent for p in pending}) > 1:
        facts["conflicts"].append("存在多个未完成操作，不能按时间自动选择")
    return facts


def manifest(input_path):
    data = evidence.read(input_path)
    require(set(data) == {"parent_id", "expected_children", "acceptances"}, "manifest 输入字段不符")
    require(
        len(data["expected_children"]) == len(set(data["expected_children"])),
        "expected children 重复",
    )
    tickets = []
    for binding in data["acceptances"]:
        path = evidence.bound(binding)
        acceptance = evidence.read(path)
        require(
            acceptance.get("kind") == "mechanical_acceptance"
            and acceptance.get("role") == "executor"
            and acceptance.get("status") == "DONE",
            "manifest 只接受成功 ticket 验收",
        )
        for kind in ("dispatch", "report", "receipt"):
            require(
                evidence.digest(acceptance[kind + "_path"]) == acceptance[kind + "_sha256"],
                "ticket 验收来源已变化",
            )
        dispatch = evidence.read(acceptance["dispatch_path"])
        report = evidence.read(acceptance["report_path"])
        require(dispatch["parent_id"] == data["parent_id"], "ticket 属于其他 parent")
        gates = report.get("required_boundary_gates", report.get("boundary_gates", []))
        tickets.append(
            {
                "ticket_id": dispatch["ticket_id"],
                "base_commit": report["base_commit"],
                "head_commit": report["head_commit"],
                "implementation_commits": report["implementation_commits"],
                "boundary_gates": gates,
                "acceptance": binding,
                "test_plan": report.get("test_plan"),
                "concerns": report.get("concerns", []),
                "report": evidence.binding(acceptance["report_path"]),
            }
        )
    require(
        [row["ticket_id"] for row in tickets] == data["expected_children"],
        "验收来源必须按固定 children 一一对应",
    )
    return {
        "version": 1,
        "parent_id": data["parent_id"],
        "expected_children": data["expected_children"],
        "tickets": tickets,
        "required_boundary_gates": list(
            dict.fromkeys(gate for row in tickets for gate in row["boundary_gates"])
        ),
    }


def summary(input_path):
    data = evidence.read(input_path)
    require(
        set(data) == {"facts", "manifest", "status", "cause", "uncertainties", "recommendation"},
        "摘要输入字段不符",
    )
    facts = evidence.read(evidence.bound(data["facts"]))
    manifest_data = evidence.read(evidence.bound(data["manifest"])) if data["manifest"] else None
    machine = {
        "parent_id": facts["parent_id"],
        "head": facts["worktree_head"],
        "dirty": bool(facts["worktree_status"]),
        "pending_operations": facts["pending_operations"],
        "conflicts": facts["conflicts"],
        "external_stop_observation_required": facts["external_stop_observation_required"],
        "tickets": [] if manifest_data is None else manifest_data["expected_children"],
        "gates": [] if manifest_data is None else manifest_data["required_boundary_gates"],
    }
    lines = [
        "## Beadwork 批次事实",
        "",
        "```json",
        json.dumps(machine, ensure_ascii=False, indent=2),
        "```",
        "",
        "状态：" + data["status"],
        "原因：" + data["cause"],
        "不确定性：" + ("；".join(data["uncertainties"]) or "无"),
        "建议：" + data["recommendation"],
    ]
    return {"facts": machine, "text": "\n".join(lines) + "\n"}


def execute(args):
    """执行已经由统一 CLI 解析的批次证据命令。"""
    result = (
        inspect(args.repository_root, args.parent_id)
        if args.command == "inspect"
        else manifest(args.input)
        if args.command == "manifest"
        else summary(args.input)
    )
    evidence.write(evidence.absolute(args.output), result)
    return {"output": str(evidence.absolute(args.output)), "sha256": evidence.digest(args.output)}

"""从已验收 preflight 初始化或恢复批次 worktree、基础 gates 与 parent claim。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import evidence
import process_runner
import tracker_operations


def require(value, message):
    if not value: raise ValueError(message)


def git(root, *args):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    require(p.returncode == 0, "git 操作失败：" + p.stderr.strip())
    return p.stdout.rstrip("\n")


def prepare(input_path, output):
    data = evidence.read(input_path)
    required = {"repository_root", "parent_id", "expected_children", "preflight_acceptance",
                "install_inputs", "expected_assignee"}
    require(set(data) == required, "初始化输入字段不符")
    accepted = evidence.read(evidence.bound(data["preflight_acceptance"]))
    require(accepted.get("kind") == "mechanical_acceptance" and accepted.get("role") == "preflight"
            and accepted.get("status") == "READY", "初始化需要 READY preflight 验收")
    for kind in ("dispatch", "report", "receipt"):
        require(evidence.digest(accepted[kind + "_path"]) == accepted[kind + "_sha256"],
                "preflight 验收来源已变化")
    dispatch = evidence.read(accepted["dispatch_path"]); report = evidence.read(accepted["report_path"])
    require(dispatch["parent_id"] == data["parent_id"] and report["expected_children"] == data["expected_children"],
            "初始化范围与 preflight 不符")
    require(report.get('gate_plan') and report.get('gate_plan_source'), '初始化需要 preflight gate-plan')
    require(evidence.read(evidence.bound(report['gate_plan_source'])) == report['gate_plan'],
            '初始化 gate-plan 来源已变化')
    intent = {"version": 2, **data, "gate_plan": report['gate_plan'], "gate_plan_source": report['gate_plan_source'],
              "target_main": git(data["repository_root"], "rev-parse", "refs/heads/main")}
    evidence.write(evidence.absolute(output), intent)
    return {"intent_path": str(evidence.absolute(output)), "intent_sha256": evidence.digest(output)}


def run_step(folder, number, name, argv, cwd):
    path = folder / f"step-{number:02d}-{name}.json"
    if path.exists():
        result = evidence.read(path)
        require(result["argv"] == argv and result["cwd"] == str(cwd), "初始化恢复步骤身份不符")
        require(result["outcome"] == "exited" and result["exit_code"] == 0 and result["process_group_gone"],
                "已有初始化步骤未成功")
        return result
    log = folder / f"step-{number:02d}-{name}.log"
    executed = process_runner.run(argv, str(cwd), log)
    result = {"argv": argv, "cwd": str(cwd), **executed,
              "log_sha256": evidence.digest(log), "log_bytes": log.stat().st_size}
    evidence.write(path, result)
    require(executed["outcome"] == "exited" and executed["exit_code"] == 0 and executed["process_group_gone"],
            "初始化步骤失败，见 " + str(log))
    return result


def execute(intent_path):
    path = evidence.absolute(intent_path); intent = evidence.read(path); folder = path.parent
    ready = folder / "ready.json"
    if ready.exists():
        result = evidence.read(ready); require(result["intent_sha256"] == evidence.digest(path), "初始化 intent 已变化"); return result
    root = Path(intent["repository_root"]); worktree = root / ".worktrees" / intent["parent_id"]
    branch = "implement/" + intent["parent_id"]
    if not worktree.exists():
        require(not git(root, "for-each-ref", "--format=%(refname)", "refs/heads/" + branch),
                "branch 已存在但 worktree 缺失，需先核实恢复现场")
        run_step(folder, 1, "worktree", ["git", "-C", str(root), "worktree", "add", "-b", branch,
                                              str(worktree), intent["target_main"]], root)
    require(git(worktree, "symbolic-ref", "--short", "HEAD") == branch, "初始化 worktree branch 不符")
    require(not git(worktree, "status", "--porcelain=v1", "--untracked-files=all"), "初始化要求干净 worktree")
    run_step(folder, 2, "install", ["just", "--one", "--", "install"], worktree)
    run_step(folder, 3, "env-facts", ["just", "--one", "--", "env-facts"], worktree)
    run_step(folder, 4, "gate-full", ["just", "--one", "--", "gate-full"], worktree)
    tracker_input = folder / "claim-input.json"; tracker_intent = folder / "claim-intent.json"
    if not tracker_intent.exists():
        evidence.write(tracker_input, {"repository_root": str(root), "parent_id": intent["parent_id"],
                       "issue_id": intent["parent_id"], "kind": "claim",
                       "expected_assignee": intent["expected_assignee"]})
        tracker_operations.prepare(tracker_input, tracker_intent)
    claim = tracker_operations.execute(tracker_intent)
    result = {"intent_sha256": evidence.digest(path), "repository_root": str(root), "worktree": str(worktree),
              "branch": branch, "base_commit": git(worktree, "rev-parse", "HEAD"),
              "expected_children": intent["expected_children"], "gate_plan": intent['gate_plan'],
              "gate_plan_source": intent['gate_plan_source'],
              "claim": claim}
    evidence.write(ready, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--input", required=True); p.add_argument("--output", required=True)
    p = sub.add_parser("execute"); p.add_argument("--intent", required=True)
    args = parser.parse_args(); result = prepare(args.input, args.output) if args.command == "prepare" else execute(args.intent)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try: main()
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr); sys.exit(1)

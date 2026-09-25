"""新票或最终集成前同步 main；由 controller 调用，保留合并、安装和验证证据。"""

import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

import evidence
import execution_plan
import graph
import process_runner
import repository


def ancestor(wt, base, head):
    result = subprocess.run(
        ["git", "-C", str(wt), "merge-base", "--is-ancestor", base, head],
        capture_output=True,
        text=True,
    )
    repository.require(result.returncode in (0, 1), "无法检查提交 ancestry：" + result.stderr)
    return result.returncode == 0


def clean(d):
    repository.topology(d)
    for wt in (d["repository_root"], d["worktree"]):
        if wt == d["worktree"]:
            repository.require(
                not repository.status(wt), "同步要求 implementation worktree 干净：" + wt
            )
        for name in (
            "MERGE_HEAD",
            "CHERRY_PICK_HEAD",
            "REVERT_HEAD",
            "rebase-merge",
            "rebase-apply",
            "sequencer",
        ):
            path = repository.git(wt, "rev-parse", "--path-format=absolute", "--git-path", name)
            repository.require(not Path(path).exists(), "存在未完成 Git 操作：" + path)


def frontier(d):
    return graph.select_next(
        d["parent_id"],
        d["expected_children"],
        d["worktree"],
        expected_source=d.get("execution_plan_source"),
    )


def command(d, directory, argv):
    """每次命令独立记录；信号中断收尾专属进程组，恢复不复用缺失的结果。"""
    folder = directory / ("command-" + uuid.uuid4().hex)
    folder.mkdir()
    evidence.write(
        folder / "started.json", {"argv": argv, "head": repository.sha(d["worktree"], "HEAD")}
    )
    executed = process_runner.run(argv, d["worktree"], folder / "output.log")
    result = {
        "argv": argv,
        "started_sha256": evidence.digest(folder / "started.json"),
        "exit_code": executed["exit_code"],
        "interrupted": executed["outcome"] == "interrupted",
        "process_group_gone": executed["process_group_gone"],
        "recorder_error": executed["error"],
        "log_sha256": evidence.digest(folder / "output.log"),
    }
    evidence.write(folder / "result.json", result)
    repository.require(
        executed["outcome"] == "exited"
        and executed["process_group_gone"]
        and executed["exit_code"] == 0,
        "同步命令失败或中断；保留现场，日志：" + str(folder / "output.log"),
    )
    return str(folder / "result.json")


def verification_commands(d, intent, head):
    unchanged = head == intent["before"] and ancestor(d["worktree"], intent["target_main"], head)
    if unchanged:
        return []
    install = bool(
        repository.git(
            d["worktree"],
            "diff",
            "--name-only",
            intent["before"],
            head,
            "--",
            *intent["install_inputs"],
        )
    )
    recipes = ["install"] if install else []
    if not intent.get("final"):
        recipes.append("gate-core")
    return [["just", "--one", "--", recipe] for recipe in recipes]


def check_result(d, path, final=False):
    clean(d)
    p = Path(path)
    root = (
        Path(d["repository_root"])
        / ".worktrees"
        / ".evidence"
        / d["parent_id"]
        / ("final-sync" if final else "main-sync")
    )
    repository.require(
        p.name == "ready.json" and p.resolve().is_relative_to(root.resolve()),
        "同步证据不属于本批次",
    )
    repository.require(
        not any(not (i.parent / "ready.json").exists() for i in root.glob("*/intent.json")),
        "存在未完成同步，不能使用旧 ready 开新票",
    )
    r = evidence.read(p)
    intent = evidence.read(p.parent / "intent.json")
    repository.require(bool(intent.get("final")) == final, "同步阶段不符")
    _, children, _, value = execution_plan.live(d["repository_root"], d["parent_id"])
    execution_plan.check_selected(
        d["repository_root"],
        d["parent_id"],
        value,
        children,
        expected=intent.get("execution_plan_source"),
    )
    repository.require(intent.get("execution_plan_source"), "同步证据缺少执行计划绑定")
    d["execution_plan_source"] = intent["execution_plan_source"]
    states = {child["id"]: child["status"] for child in children}
    remaining = [ticket for ticket in value["ticket_order"] if states[ticket] != "closed"]
    if final:
        repository.require(
            not remaining
            and intent["target_main"] == d["reviewed_main"]
            and set(intent["expected_children"]) == set(d["expected_children"]),
            "最终同步范围或 reviewed_main 不符",
        )
    else:
        repository.require(
            remaining and remaining[0] == d.get("ticket_id"),
            "新 executor 不是执行计划允许的下一张票",
        )
    repository.require(
        r["intent_sha256"] == evidence.digest(p.parent / "intent.json"), "同步意图已变化"
    )
    repository.require(
        all(intent[k] == d[k] for k in ("repository_root", "worktree", "branch", "parent_id")),
        "同步身份不符",
    )
    repository.require(r["head"] == repository.sha(d["worktree"], "HEAD"), "同步验证 HEAD 已变化")
    repository.require(ancestor(d["worktree"], intent["target_main"], r["head"]), "同步目标未合入")
    expected = verification_commands(d, intent, r["head"])
    repository.require(len(r["commands"]) == len(expected), "同步验证命令不完整")
    for entry, argv in zip(r["commands"], expected, strict=True):
        repository.require(
            Path(entry["path"]).resolve().is_relative_to(p.parent.resolve()),
            "命令证据不属于本次同步",
        )
        repository.require(evidence.digest(entry["path"]) == entry["sha256"], "同步命令证据已变化")
        record = evidence.read(entry["path"])
        start = Path(entry["path"]).parent / "started.json"
        repository.require(
            record["started_sha256"] == evidence.digest(start), "同步命令开始记录已变化"
        )
        started = evidence.read(start)
        repository.require(
            started["head"] == r["head"] and started["argv"] == argv and record["argv"] == argv,
            "同步验证 HEAD 或命令不符",
        )
        repository.require(
            record["exit_code"] == 0 and not record["interrupted"] and record["process_group_gone"],
            "同步验证未通过",
        )
        repository.require(
            evidence.digest(Path(entry["path"]).parent / "output.log") == record["log_sha256"],
            "同步日志已变化",
        )
    return r


def sync(args, final=False):
    data = evidence.read(args.input)
    root = repository.primary(data["repository_root"])
    parent = data["parent_id"]
    repository.require(
        isinstance(parent, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parent)
        and parent not in (".", ".."),
        "parent ID 无效",
    )
    d = dict(
        data,
        repository_root=root,
        worktree=str(Path(root) / ".worktrees" / parent),
        branch="implement/" + parent,
    )
    paths = d["install_inputs"]
    repository.require(
        isinstance(paths, list)
        and paths
        and all(
            isinstance(p, str)
            and p
            and not Path(p).is_absolute()
            and ".." not in Path(p).parts
            and not p.startswith(":")
            for p in paths
        ),
        "需要仓库相对安装输入路径",
    )
    clean(d)
    d["execution_plan_source"] = execution_plan.selected(root, parent)
    next_ = frontier(d)
    repository.require(
        next_["next"] == ("done" if final else "claim"),
        "当前 frontier 不允许同步：" + json.dumps(next_, ensure_ascii=False),
    )
    if final:
        repository.require(
            re.fullmatch(r"[0-9a-f]{40}", d.get("reviewed_main", ""))
            and repository.sha(root, d["reviewed_main"]) == d["reviewed_main"],
            "需要完整 reviewed_main SHA",
        )
    directory = (
        Path(root) / ".worktrees" / ".evidence" / parent / ("final-sync" if final else "main-sync")
    )
    directory.mkdir(parents=True, exist_ok=True)
    pending = [
        p.parent for p in directory.glob("*/intent.json") if not (p.parent / "ready.json").exists()
    ]
    repository.require(len(pending) <= 1, "存在多个未完成同步，需核实现场")
    if pending:
        attempt = pending[0]
        intent = evidence.read(attempt / "intent.json")
        repository.require(
            all(
                intent[k] == d[k]
                for k in (
                    "repository_root",
                    "worktree",
                    "branch",
                    "parent_id",
                    "expected_children",
                    "execution_plan_source",
                )
            ),
            "恢复同步身份或 children 不符",
        )
        repository.require(intent["install_inputs"] == paths, "恢复须沿用原同步验证输入")
        repository.require(
            not final or intent["target_main"] == d["reviewed_main"],
            "恢复最终同步须沿用原 reviewed_main",
        )
    else:
        attempt = directory / uuid.uuid4().hex
        attempt.mkdir()
        intent = {
            k: d[k]
            for k in (
                "repository_root",
                "worktree",
                "branch",
                "parent_id",
                "expected_children",
                "execution_plan_source",
            )
        }
        intent.update(
            before=repository.sha(d["worktree"], "HEAD"),
            target_main=d["reviewed_main"] if final else repository.sha(root, "refs/heads/main"),
            install_inputs=paths,
        )
        if final:
            intent["final"] = True
        evidence.write(attempt / "intent.json", intent)
    print(json.dumps({"sync_path": str(attempt)}, ensure_ascii=False), file=sys.stderr, flush=True)
    before, target = intent["before"], intent["target_main"]
    head = repository.sha(d["worktree"], "HEAD")
    repository.require(ancestor(d["worktree"], before, head), "同步前 HEAD 已不在当前历史中")
    changed = not ancestor(d["worktree"], target, before)
    if not ancestor(d["worktree"], target, head):
        repository.require(head == before, "合并未完成且 HEAD 已变化，需核实现场")
        command(d, attempt, ["git", "merge", "--ff", "--no-edit", target])
        head = repository.sha(d["worktree"], "HEAD")
    clean(d)
    repository.require(ancestor(d["worktree"], target, head), "目标 main 未合入")
    commands = []
    for argv in verification_commands(d, intent, head):
        result = command(d, attempt, argv)
        commands.append({"path": result, "sha256": evidence.digest(result)})
        clean(d)
        repository.require(
            repository.sha(d["worktree"], "HEAD") == head, "同步验证期间 HEAD 已变化"
        )
    result = {
        "head": head,
        "target_main": target,
        "changed": changed or head != before,
        "intent_sha256": evidence.digest(attempt / "intent.json"),
        "commands": commands,
    }
    clean(d)
    repository.require(repository.sha(d["worktree"], "HEAD") == head, "同步完成前 HEAD 已变化")
    pending_result = attempt / ("ready-" + uuid.uuid4().hex + ".pending")
    evidence.write(pending_result, result)
    pending_result.rename(attempt / "ready.json")
    return {**result, "sync_result": str(attempt / "ready.json"), "frontier": frontier(d)}

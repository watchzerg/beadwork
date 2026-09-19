"""controller 的批次初始化：固定基线、workspace、验证、claim 与批次 comment。"""

from __future__ import annotations

from pathlib import Path

import evidence
import execution_plan
import gate_plan
import operation_commands as commands
import repository
import tracker_operations as tracker

require = repository.require


def prepare(input_path, output):
    data = evidence.read(input_path)
    require(
        set(data)
        == {
            "repository_root",
            "parent_id",
            "expected_children",
            "preflight_acceptance",
            "update_main_result",
            "expected_assignee",
        },
        "初始化输入字段不符",
    )
    root = repository.primary(data["repository_root"])
    require(root == data["repository_root"], "初始化需要 primary 绝对路径")
    require(
        isinstance(data["expected_assignee"], str) and data["expected_assignee"].strip(),
        "缺少领取身份",
    )
    accepted = evidence.read(evidence.bound(data["preflight_acceptance"]))
    require(
        accepted.get("kind") == "mechanical_acceptance"
        and accepted.get("role") == "preflight"
        and accepted.get("status") == "READY",
        "初始化需要 READY preflight 验收",
    )
    for kind in ("dispatch", "report", "receipt"):
        require(
            evidence.digest(accepted[kind + "_path"]) == accepted[kind + "_sha256"],
            "preflight 来源变化",
        )
    dispatch, report = (
        evidence.read(accepted["dispatch_path"]),
        evidence.read(accepted["report_path"]),
    )
    require(
        dispatch["repository_root"] == root
        and dispatch["parent_id"] == data["parent_id"]
        and report["expected_children"] == data["expected_children"]
        and report["status"] == "READY"
        and report["suggested_route"] == "new_batch",
        "初始化范围或路线与 preflight 不符",
    )
    update = evidence.read(evidence.bound(data["update_main_result"]))
    require(
        update["repository_root"] == root
        and type(update["fetch_failed"]) is bool
        and isinstance(update["note"], str),
        "update-main 结果无效",
    )
    require(
        repository.sha(root, "HEAD") == update["main_commit"] and not repository.status(root),
        "初始化基线或 primary 现场变化",
    )
    parent, children, _, plan = execution_plan.live(root, data["parent_id"])
    require(report["execution_plan"] == plan, "执行计划在 preflight 后变化")
    selected = execution_plan.check_selected(
        root, data["parent_id"], plan, children, expected=accepted["execution_plan_source"]
    )
    require(
        set(plan["ticket_order"]) == set(data["expected_children"])
        and parent["status"] == "open"
        and all(c["status"] == "open" and not c.get("assignee") for c in children),
        "不是未开工批次",
    )
    branch = "implement/" + data["parent_id"]
    worktree = Path(root) / ".worktrees" / data["parent_id"]
    repository.git(root, "check-ignore", "-q", "--", ".worktrees/probe")
    require(
        not worktree.exists()
        and not repository.git(root, "for-each-ref", "--format=%(refname)", "refs/heads/" + branch),
        "初始化现场已存在；使用原 intent",
    )
    target = evidence.absolute(output)
    expected = Path(root) / ".worktrees/.evidence" / data["parent_id"] / "initialize"
    require(
        target.name == "intent.json" and target.parent.parent == expected,
        "初始化 intent 必须位于本批 initialize/<id>/intent.json",
    )
    require(not list(expected.glob("*/intent.json")), "已有初始化 intent；使用原入口恢复")
    intent = dict(
        data,
        version=3,
        branch=branch,
        worktree=str(worktree),
        target_main=update["main_commit"],
        execution_plan_source=selected,
    )
    evidence.write(target, intent)
    return {"intent_path": str(target), "intent_sha256": evidence.digest(target)}


def observation(recovery, run):
    entries = evidence.read(recovery) if recovery else []
    require(isinstance(entries, list), "恢复观察必须为数组")
    matches = [x for x in entries if x.get("run_path") == str(run)]
    require(len(matches) == 1, "命令结果未知；先确认收尾并提供 recovery 观察：" + str(run))
    value = matches[0]
    require(
        set(value) == {"run_path", "task_id", "stopped", "observed_at", "evidence", "unresolved"}
        and value["stopped"] is True
        and value["unresolved"] == []
        and all(
            isinstance(value[k], str) and value[k].strip()
            for k in ("task_id", "observed_at", "evidence")
        ),
        "恢复需要明确的任务收尾观察",
    )
    return value


def step(folder, name, argv, cwd, context, recovery=None, *, plan_recipes=None):
    directory = folder / name
    directory.mkdir(exist_ok=True)
    attempts = sorted(directory.glob("attempt-*"))
    reusable = None
    for run in attempts:
        started = evidence.read(run / "started.json")
        require(started["argv"] == argv and started["cwd"] == str(cwd), "初始化命令身份变化")
        if (run / "result.json").exists():
            result, _, _ = commands.read(evidence.binding(run / "result.json"))
            unknown = result["outcome"] != "exited" or not result["process_group_gone"]
        else:
            result, unknown = None, True
        if unknown and not (run / "closure.json").exists():
            evidence.write(run / "closure.json", observation(recovery, run))
        if result and commands.succeeded(result) and started["context"] == context:
            reusable = evidence.binding(run / "result.json")
            if plan_recipes is not None:
                raw = commands.stdout(reusable)
                try:
                    gate_plan.parse(raw, plan_recipes)
                except ValueError:
                    reusable = None
        else:
            reusable = None
    return reusable or commands.run(
        directory,
        f"attempt-{len(attempts) + 1:06d}",
        argv,
        cwd,
        context,
        capture_stdout=plan_recipes is not None,
    )


def live_unstarted(d):
    parent, children, _, plan = execution_plan.live(d["repository_root"], d["parent_id"])
    execution_plan.check_selected(
        d["repository_root"], d["parent_id"], plan, children, expected=d["execution_plan_source"]
    )
    require(
        set(plan["ticket_order"]) == set(d["expected_children"])
        and all(c["status"] == "open" and not c.get("assignee") for c in children),
        "已有 child 工作；不能重跑初始化",
    )
    require(
        not list(
            execution_plan.folder(d["repository_root"], d["parent_id"]).glob("started-*.json")
        ),
        "已有 child start 来源",
    )
    require(
        parent["status"] == "open"
        or (parent["status"] == "in_progress" and parent.get("assignee") == d["expected_assignee"]),
        "parent 归属或状态变化",
    )
    return parent


def workspace(d, folder):
    sources = []
    values = []
    for label, argv, cwd in (
        ("workspace-info", ["bd", "worktree", "info", "--json", "--readonly"], d["worktree"]),
        ("workspace-primary", ["bd", "where", "--json", "--readonly"], d["repository_root"]),
        ("workspace-child", ["bd", "where", "--json", "--readonly"], d["worktree"]),
    ):
        source = commands.run(folder, label, argv, cwd)
        _, log = commands.require_success(source)
        sources.append(source)
        values.append(evidence.loads(log.read_text()))
    require(values[0].get("is_worktree") is True, "Beads 未识别 implementation worktree")
    primary_path = Path(values[1]["path"]).resolve()
    require(
        primary_path == Path(d["repository_root"]) / ".beads"
        and Path(values[2]["path"]).resolve() == primary_path
        and values[1]["database_path"] == values[2]["database_path"],
        "worktree 未共享 primary Beads workspace",
    )
    return sources


def tracker_step(folder, name, value):
    path = folder / (name + "-intent.json")
    if not path.exists():
        source = folder / (name + "-input.json")
        if source.exists():
            require(evidence.read(source) == value, "tracker 输入变化")
        else:
            evidence.write(source, value)
        tracker.prepare(source, path)
    result = tracker.execute(path)
    return result, evidence.binding(path.with_name(path.stem + "-result.json"))


def execute(intent_path, recovery=None):
    path = evidence.absolute(intent_path)
    d = evidence.read(path)
    folder = path.parent
    require(d.get("version") == 3, "需要当前初始化 intent")
    evidence.bound(d["preflight_acceptance"])
    evidence.bound(d["update_main_result"])
    ready = folder / "ready.json"
    if ready.exists():
        result = evidence.read(ready)
        require(result["intent_sha256"] == evidence.digest(path), "初始化 intent 已变化")
        for item in result["commands"]:
            commands.require_success(item)
        for item in (result["claim_source"], result["comment_source"]):
            evidence.bound(item)
        return result
    live_unstarted(d)
    root, wt = d["repository_root"], Path(d["worktree"])
    if not wt.exists():
        require(
            repository.sha(root, "HEAD") == d["target_main"] and not repository.status(root),
            "worktree 创建前 main 已变化",
        )
        require(
            not repository.git(
                root, "for-each-ref", "--format=%(refname)", "refs/heads/" + d["branch"]
            ),
            "branch 已存在但 worktree 缺失",
        )
        source = step(
            folder,
            "create",
            ["bd", "worktree", "create", str(wt), "--branch", d["branch"]],
            root,
            d["target_main"],
            recovery,
        )
        commands.require_success(source)
    else:
        require(list((folder / "create").glob("attempt-*")), "worktree 不是本初始化创建的现场")
        # 创建可能成功但记录未落盘；先核实旧命令停止，再读现场协调。
        for run in (folder / "create").glob("attempt-*"):
            result = evidence.read(run / "result.json") if (run / "result.json").exists() else None
            if (
                not result or result["outcome"] != "exited" or not result["process_group_gone"]
            ) and not (run / "closure.json").exists():
                evidence.write(run / "closure.json", observation(recovery, run))
    repository.topology(d)
    require(
        repository.sha(wt, "HEAD") == d["target_main"] and not repository.status(wt),
        "初始化要求固定基线的干净 worktree",
    )
    require(not repository.git(root, "diff", "HEAD", "--", ".beads"), "primary .beads 已变化")
    sources = workspace(d, folder)
    context = {"head": d["target_main"]}
    plan = None
    plan_source = None
    for recipe in ("install", "env-facts", "gate-plan", "gate-core"):
        recipes = repository.run(["just", "--summary"], wt).split() if recipe == "gate-plan" else []
        source = step(
            folder,
            recipe,
            ["just", "--one", "--", recipe],
            wt,
            context,
            recovery,
            plan_recipes=recipes if recipe == "gate-plan" else None,
        )
        commands.require_success(source)
        require(
            repository.sha(wt, "HEAD") == d["target_main"] and not repository.status(wt),
            "初始化验证期间源码变化",
        )
        sources.append(source)
        if recipe == "gate-plan":
            plan = gate_plan.parse(commands.stdout(source), recipes)
            plan_source = source
        context = source  # 上游重跑后，下游不可复用旧成功。
    require(plan is not None, "初始化缺少有效 gate-plan")
    live_unstarted(d)
    common = dict(repository_root=root, parent_id=d["parent_id"], issue_id=d["parent_id"])
    claimed, claim_source = tracker_step(
        folder, "claim", dict(common, kind="claim", expected_assignee=d["expected_assignee"])
    )
    current = tracker.issue(root, d["parent_id"])
    require(
        current["status"] == "in_progress" and current.get("assignee") == d["expected_assignee"],
        "parent claim 实时读回不符",
    )
    update = evidence.read(evidence.bound(d["update_main_result"]))
    body = "\n".join(
        [
            "批次初始化完成。",
            "",
            "branch：" + d["branch"],
            "worktree：" + str(wt),
            "BASE：" + d["target_main"],
            update["note"],
            "依赖与环境准备完成，快速基线 gate-core 通过。",
            "初始化证据：" + str(path),
            *["命令证据：" + x["path"] for x in sources[-4:]],
        ]
    )
    # 发布输入一经固定，恢复复用原正文；验证来源仍留在不可变记录中。
    comment_input = folder / "comment-input.json"
    if comment_input.exists():
        body = evidence.read(comment_input)["body"]
    comment, comment_source = tracker_step(
        folder, "comment", dict(common, kind="comment", body=body)
    )
    result = dict(
        kind="batch_initialized",
        intent_sha256=evidence.digest(path),
        repository_root=root,
        parent_id=d["parent_id"],
        worktree=str(wt),
        branch=d["branch"],
        base_commit=d["target_main"],
        expected_children=d["expected_children"],
        commands=sources,
        gate_plan=plan,
        gate_plan_source=plan_source,
        claim_source=claim_source,
        comment_source=comment_source,
        comment_id=comment["comment_id"],
    )
    evidence.write(ready, result)
    return result


def execute_command(args):
    """执行已经由统一 CLI 解析的批次初始化命令。"""
    return (
        prepare(args.input, args.output)
        if args.command == "prepare"
        else execute(args.intent, args.recovery)
    )

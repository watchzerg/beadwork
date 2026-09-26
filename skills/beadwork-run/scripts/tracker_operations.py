"""controller 专用 Beads 写入与读回核对；每个 intent 只产生一个结果。"""

from __future__ import annotations

import json
import os
import subprocess

import evidence
import execution_plan
import graph
import repository

KINDS = ("claim", "comment", "close")
VERSION = 3


def require(value, message):
    if not value:
        raise ValueError(message)


def claim_identity(root):
    """固定 Beadwork 的领取身份；执行时显式传 actor，不依赖 bd 的隐式回退。"""
    if "BEADS_ACTOR" in os.environ:
        actor, source = os.environ["BEADS_ACTOR"], "BEADS_ACTOR"
    else:
        result = subprocess.run(
            ["git", "config", "--get", "user.name"],
            cwd=repository.primary(root),
            capture_output=True,
            text=True,
        )
        require(result.returncode in (0, 1), "读取 git user.name 失败：" + result.stderr.strip())
        actor, source = result.stdout.strip(), "git user.name"
    require(
        isinstance(actor, str) and actor.strip(), "缺少领取身份：设置 BEADS_ACTOR 或 git user.name"
    )
    return {"expected_assignee": actor.strip(), "assignee_source": source}


def command(root, *args, readonly=False):
    argv = ["bd", *args]
    if readonly:
        argv += ["--readonly", "--json"]
    else:
        argv += ["--json"]
    process = subprocess.run(argv, cwd=root, capture_output=True, text=True)
    return {
        "argv": argv,
        "exit_code": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
    }


def parse(result, label):
    require(result["exit_code"] == 0, f"{label} 失败：{result['stderr'].strip()}")
    try:
        return json.loads(result["stdout"])
    except ValueError as error:
        raise ValueError(f"{label} 返回非法 JSON") from error


def issue(root, issue_id):
    rows = parse(command(root, "show", issue_id, readonly=True), "bd show")
    require(isinstance(rows, list), "bd show 结果不是数组")
    matches = [row for row in rows if isinstance(row, dict) and row.get("id") == issue_id]
    require(len(matches) == 1, "无法唯一读取目标 issue")
    return matches[0]


def comments(root, issue_id):
    rows = parse(command(root, "comments", issue_id, readonly=True), "bd comments")
    require(isinstance(rows, list), "bd comments 结果不是数组")
    return rows


def comment_text(row):
    if not isinstance(row, dict):
        return ""
    return next(
        (
            row[key]
            for key in ("text", "body", "comment", "content")
            if isinstance(row.get(key), str)
        ),
        "",
    )


def matching_comment(rows, marker):
    matches = [row for row in rows if marker in comment_text(row)]
    require(len(matches) <= 1, "comment marker 匹配不唯一")
    if not matches:
        return None
    value = matches[0].get("id")
    require(type(value) in (str, int) and str(value).strip(), "comment 缺少实际 ID")
    return str(value)


def prepare(input_path, output, *, identity=None):
    value = evidence.read(input_path)
    require(
        set(value)
        <= {
            "repository_root",
            "parent_id",
            "issue_id",
            "kind",
            "body_source",
            "reason",
            "prerequisite",
        },
        "tracker intent 输入字段无效",
    )
    require(value.get("kind") in KINDS, "tracker kind 无效")
    for key in ("repository_root", "parent_id", "issue_id"):
        require(isinstance(value.get(key), str) and value[key], f"缺少 {key}")
    if value["kind"] == "claim":
        value.update(identity if identity is not None else claim_identity(value["repository_root"]))
    if value["kind"] == "comment":
        body = evidence.bound(value.get("body_source"))
        require(body.read_text(encoding="utf-8").strip(), "comment 需要非空正文来源")
    if value["kind"] == "close":
        require(isinstance(value.get("reason"), str) and value["reason"].strip(), "close 需要原因")
        require(value.get("prerequisite") is not None, "close 需要成功交付前置来源")
        evidence.bound(value["prerequisite"])
    if value["kind"] == "claim" and value["issue_id"] != value["parent_id"]:
        _, children, _, plan = execution_plan.live(value["repository_root"], value["parent_id"])
        value["execution_plan_source"] = execution_plan.check_selected(
            value["repository_root"], value["parent_id"], plan, children
        )
    target = evidence.absolute(output)
    intent = {"version": VERSION, **value}
    evidence.write(target, intent)
    return {"intent_path": str(target), "intent_sha256": evidence.digest(target)}


def state(value, *keys):
    return {key: value.get(key) for key in keys}


def receipt(result_path, result):
    return {
        "kind": result["kind"],
        "issue_id": result["issue_id"],
        "already_applied": result["already_applied"],
        **({"comment_id": result["comment_id"]} if result["kind"] == "comment" else {}),
        "result_source": evidence.binding(result_path),
    }


def execute(intent_path):
    path = evidence.absolute(intent_path)
    intent = evidence.read(path)
    require(intent.get("version") == VERSION, "需要当前 tracker intent")
    if intent["kind"] == "claim":
        require(
            isinstance(intent.get("expected_assignee"), str)
            and intent["expected_assignee"].strip(),
            "claim intent 缺少固定领取身份",
        )
    if intent["kind"] == "comment":
        evidence.bound(intent["body_source"])
    result_path = path.with_name(path.stem + "-result.json")
    if intent["kind"] == "claim" and intent["issue_id"] != intent["parent_id"]:
        require(intent.get("execution_plan_source"), "child claim 缺少执行计划绑定")
        _, children, _, plan = execution_plan.live(intent["repository_root"], intent["parent_id"])
        execution_plan.check_selected(
            intent["repository_root"],
            intent["parent_id"],
            plan,
            children,
            expected=intent["execution_plan_source"],
        )
        ready = execution_plan.bd(
            intent["repository_root"],
            "ready",
            "--parent",
            intent["parent_id"],
            "--unassigned",
            "--limit",
            "0",
        )
        decision = graph.frontier_result(
            [graph.normalize_issue(x, "child") for x in children], plan["ticket_order"], ready
        )
        require(
            decision.get("ticket_id") == intent["issue_id"]
            and decision["next"] in ("claim", "resume"),
            "child claim 不是当前执行计划允许的下一张票："
            + json.dumps(decision, ensure_ascii=False),
        )
        started = execution_plan.progress_path(
            intent["repository_root"], intent["parent_id"], intent["issue_id"], "started"
        )
        if decision["next"] == "resume":
            require(
                started.exists() and evidence.read(started)["source"] == evidence.binding(path),
                "恢复 claim 必须使用原始领取 intent",
            )
            current = next(x for x in children if x["id"] == intent["issue_id"])
            require(current.get("assignee") == intent.get("expected_assignee"), "活动票归属不同")
    if result_path.exists():
        result = evidence.read(result_path)
        require(result["intent_sha256"] == evidence.digest(path), "tracker intent 已变化")
        if (
            intent["kind"] == "close"
            and intent["issue_id"] != intent["parent_id"]
            and execution_plan.selected(intent["repository_root"], intent["parent_id"], False)
        ):
            execution_plan.record_progress(
                intent["repository_root"],
                intent["parent_id"],
                intent["issue_id"],
                "closed",
                evidence.binding(path),
            )
        return receipt(result_path, result)
    root, issue_id, kind = intent["repository_root"], intent["issue_id"], intent["kind"]
    before = {} if kind == "comment" else issue(root, issue_id)
    marker = "beadwork-operation:" + evidence.digest(path)
    write_result = None
    already = False
    if kind == "claim":
        expected = intent.get("expected_assignee")
        already = before.get("status") == "in_progress" and bool(before.get("assignee"))
        if already:
            require(
                expected and before.get("assignee") == expected,
                "issue 已被领取但无法证明属于本 intent",
            )
        else:
            if issue_id != intent["parent_id"]:
                execution_plan.record_progress(
                    root, intent["parent_id"], issue_id, "started", evidence.binding(path)
                )
            write_result = command(root, "update", issue_id, "--claim", "--actor", expected)
    elif kind == "comment":
        already = matching_comment(comments(root, issue_id), marker) is not None
        if not already:
            body_path = path.with_name(path.stem + "-body.txt")
            body = (
                evidence.bound(intent["body_source"]).read_text(encoding="utf-8").rstrip()
                + "\n\n<!-- "
                + marker
                + " -->\n"
            )
            if body_path.exists():
                require(body_path.read_text(encoding="utf-8") == body, "comment 正文证据已变化")
            else:
                with body_path.open("x", encoding="utf-8") as stream:
                    stream.write(body)
            write_result = command(root, "comments", "add", issue_id, "-f", str(body_path))
    else:
        already = before.get("status") == "closed"
        if not already:
            write_result = command(root, "close", issue_id, "--reason", intent["reason"])
    after = {} if kind == "comment" else issue(root, issue_id)
    if kind == "claim":
        require(after.get("status") == "in_progress" and after.get("assignee"), "claim 未读回")
        require(after.get("assignee") == intent["expected_assignee"], "claim assignee 不符")
    elif kind == "comment":
        comment_id = matching_comment(comments(root, issue_id), marker)
        require(comment_id is not None, "comment 写入结果未知")
    else:
        require(after.get("status") == "closed", "close 未读回")
    result = {
        "intent_sha256": evidence.digest(path),
        "kind": kind,
        "issue_id": issue_id,
        "already_applied": already,
        "write_exit_code": None if write_result is None else write_result["exit_code"],
    }
    if kind == "claim":
        result.update(
            before_state=state(before, "status", "assignee"),
            after_state=state(after, "status", "assignee"),
        )
    elif kind == "comment":
        result["comment_id"] = comment_id
    else:
        result.update(before_state=state(before, "status"), after_state=state(after, "status"))
    evidence.write(result_path, result)
    if (
        kind == "close"
        and issue_id != intent["parent_id"]
        and execution_plan.selected(root, intent["parent_id"], False)
    ):
        execution_plan.record_progress(
            root, intent["parent_id"], issue_id, "closed", evidence.binding(path)
        )
    return receipt(result_path, result)


def execute_command(args):
    """执行已经由统一 CLI 解析的 tracker 命令。"""
    return prepare(args.input, args.output) if args.command == "prepare" else execute(args.intent)

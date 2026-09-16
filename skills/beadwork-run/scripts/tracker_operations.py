"""controller 专用 Beads 写入与读回核对；每个 intent 只产生一个结果。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import evidence


KINDS = ("claim", "comment", "close")


def require(value, message):
    if not value:
        raise ValueError(message)


def command(root, *args, readonly=False):
    argv = ["bd", *args]
    if readonly:
        argv += ["--readonly", "--json"]
    else:
        argv += ["--json"]
    process = subprocess.run(argv, cwd=root, capture_output=True, text=True)
    return {"argv": argv, "exit_code": process.returncode,
            "stdout": process.stdout, "stderr": process.stderr}


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
    return next((row[key] for key in ("text", "body", "comment", "content")
                 if isinstance(row.get(key), str)), "")


def prepare(input_path, output):
    value = evidence.read(input_path)
    require(set(value) <= {"repository_root", "parent_id", "issue_id", "kind", "body",
                           "reason", "expected_assignee", "prerequisite"}, "tracker intent 输入字段无效")
    require(value.get("kind") in KINDS, "tracker kind 无效")
    for key in ("repository_root", "parent_id", "issue_id"):
        require(isinstance(value.get(key), str) and value[key], f"缺少 {key}")
    if value["kind"] == "comment":
        require(isinstance(value.get("body"), str) and value["body"].strip(), "comment 需要正文")
    if value["kind"] == "close":
        require(isinstance(value.get("reason"), str) and value["reason"].strip(), "close 需要原因")
        require(value.get("prerequisite") is not None, "close 需要成功交付前置来源")
        evidence.bound(value["prerequisite"])
    target = evidence.absolute(output)
    intent = {"version": 1, **value}
    evidence.write(target, intent)
    return {"intent_path": str(target), "intent_sha256": evidence.digest(target)}


def execute(intent_path):
    path = evidence.absolute(intent_path)
    intent = evidence.read(path)
    result_path = path.with_name(path.stem + "-result.json")
    if result_path.exists():
        result = evidence.read(result_path)
        require(result["intent_sha256"] == evidence.digest(path), "tracker intent 已变化")
        return result
    root, issue_id, kind = intent["repository_root"], intent["issue_id"], intent["kind"]
    before = issue(root, issue_id)
    marker = "beadwork-operation:" + evidence.digest(path)
    write_result = None
    already = False
    if kind == "claim":
        expected = intent.get("expected_assignee")
        already = before.get("status") == "in_progress" and bool(before.get("assignee"))
        if already:
            require(expected and before.get("assignee") == expected,
                    "issue 已被领取但无法证明属于本 intent")
        else:
            write_result = command(root, "update", issue_id, "--claim")
    elif kind == "comment":
        already = any(marker in comment_text(row) for row in comments(root, issue_id))
        if not already:
            body_path = path.with_name(path.stem + "-body.txt")
            body = intent["body"].rstrip() + "\n\n<!-- " + marker + " -->\n"
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
    after = issue(root, issue_id)
    if kind == "claim":
        require(after.get("status") == "in_progress" and after.get("assignee"), "claim 未读回")
        if intent.get("expected_assignee"):
            require(after.get("assignee") == intent["expected_assignee"], "claim assignee 不符")
    elif kind == "comment":
        require(any(marker in comment_text(row) for row in comments(root, issue_id)), "comment 写入结果未知")
    else:
        require(after.get("status") == "closed", "close 未读回")
    result = {"intent_sha256": evidence.digest(path), "kind": kind, "issue_id": issue_id,
              "already_applied": already, "before": before, "after": after,
              "write_exit_code": None if write_result is None else write_result["exit_code"]}
    evidence.write(result_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--input", required=True); p.add_argument("--output", required=True)
    p = sub.add_parser("execute"); p.add_argument("--intent", required=True)
    args = parser.parse_args()
    result = prepare(args.input, args.output) if args.command == "prepare" else execute(args.intent)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

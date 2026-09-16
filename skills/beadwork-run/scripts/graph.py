#!/usr/bin/env python3
"""beadwork-run 内置只读 Beads 查询脚本。

用法:
  python3 graph.py check-flat <parent-id>
  python3 graph.py next <parent-id> <expected-child-id>...

stdout 成功时只输出一行紧凑 JSON；业务不满足时输出带 reason 的结果并 exit 0。
运行/输入/schema 错误时向 stderr 输出 {"error":...} 并 exit 1。
所有 bd 调用均为只读（--readonly --json），无任何 Git/Beads 写操作。

运行要求：Python >= 3.9，仅标准库。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

ID_RE = re.compile(r"[^\s-]+-\S+")


def _use_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def fail(message: str) -> None:
    sys.stderr.write(json.dumps({"error": message}, ensure_ascii=False) + "\n")
    raise SystemExit(1)


def emit(payload: Dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def run_bd(args: List[str], cwd: str) -> str:
    try:
        proc = subprocess.run(["bd", *args], cwd=cwd, capture_output=True)
    except OSError as exc:
        fail("bd {} 失败 (exit null): {}".format(args[0], exc))
    stderr = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        fail(
            "bd {} 失败 (exit {}){}".format(
                args[0], proc.returncode, ": " + stderr if stderr else ""
            )
        )
    return proc.stdout.decode("utf-8", "replace")


def parse_bd_json(stdout: str, what: str) -> Any:
    try:
        parsed = json.loads(stdout)
    except ValueError:
        fail("{} 返回的不是合法 JSON".format(what))
    if isinstance(parsed, dict) and "error" in parsed:
        fail("{} 失败: {}".format(what, parsed["error"]))
    return parsed


def validate_id(id_: Optional[str]) -> None:
    if not id_ or not ID_RE.fullmatch(id_):
        fail("参数必须是非空、包含连字符且不以 - 开头的完整 Bead ID")


def validate_issue(raw: Any, what: str) -> Dict[str, Any]:
    if raw is None or not isinstance(raw, (dict, list)):
        fail("{} 记录不是对象".format(what))
    rec: Dict[str, Any] = raw if isinstance(raw, dict) else {}
    if not isinstance(rec.get("id"), str) or len(rec["id"]) == 0:
        fail("{} 缺少有效的 id 字段".format(what))
    if not isinstance(rec.get("status"), str) or len(rec["status"]) == 0:
        fail("{} ({}) 缺少有效的 status 字段".format(what, rec["id"]))
    labels: List[str] = []
    if rec.get("labels") is not None:
        raw_labels = rec["labels"]
        if not isinstance(raw_labels, list) or not all(
            isinstance(label, str) for label in raw_labels
        ):
            fail("{} ({}) 的 labels 字段格式无效".format(what, rec["id"]))
        labels = list(raw_labels)
    assignee: Optional[str] = None
    if rec.get("assignee") is not None and rec.get("assignee") != "":
        if not isinstance(rec["assignee"], str):
            fail("{} ({}) 的 assignee 字段格式无效".format(what, rec["id"]))
        assignee = rec["assignee"]
    return {
        "id": rec["id"],
        "status": rec["status"],
        "labels": labels,
        "assignee": assignee,
    }


def flat_result(children: List[Dict[str, Any]], dependents: List[Any]) -> Dict[str, Any]:
    if len(children) == 0:
        return {"flat": False, "reason": "no_children"}
    if not isinstance(dependents, list):
        raise ValueError("bd dep list 返回的不是数组")
    grandchildren = set()
    for item in dependents:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
            raise ValueError("bd dep list 包含缺少有效 id 的记录")
        grandchildren.add(item["id"])
    return ({"flat": False, "grandchildren": sorted(grandchildren)}
            if grandchildren else {"flat": True})


def check_flat(children: List[Dict[str, Any]], cwd: str) -> None:
    if not children:
        emit(flat_result(children, []))
        return
    dep_out = run_bd(
        [
            "dep",
            "list",
            *(child["id"] for child in children),
            "--direction=up",
            "--type=parent-child",
            "--readonly",
            "--json",
        ],
        cwd,
    )
    dependents = parse_bd_json(dep_out, "bd dep list")
    try:
        emit(flat_result(children, dependents))
    except ValueError as error:
        fail(str(error))


def frontier_result(children: List[Dict[str, Any]], expected_args: List[str], ready_raw=None):
    actual_ids = {child["id"] for child in children}
    expected_ids = set(expected_args)
    added = [child["id"] for child in children if child["id"] not in expected_ids]
    removed = [id_ for id_ in expected_args if id_ not in actual_ids]
    if added or removed:
        return {"next": "blocked", "reason": "children_changed", "added": added, "removed": removed}
    if not children:
        return {"next": "blocked", "reason": "no_children"}
    missing_ready = [child["id"] for child in children
                     if child["status"] != "closed" and "ready-for-agent" not in child["labels"]]
    if missing_ready:
        return {"next": "blocked", "reason": "missing_ready_label", "ids": missing_ready}
    in_progress = [child["id"] for child in children if child["status"] == "in_progress"]
    if len(in_progress) > 1:
        return {"next": "blocked", "reason": "multiple_in_progress", "ids": in_progress}
    if len(in_progress) == 1:
        return {"next": "resume", "ticket_id": in_progress[0]}
    if all(child["status"] == "closed" for child in children):
        return {"next": "done"}
    if ready_raw is None:
        return None
    if not isinstance(ready_raw, list):
        raise ValueError("bd ready 返回的不是数组")
    if not ready_raw:
        unfinished = [{"id": child["id"], "status": child["status"], "assignee": child["assignee"]}
                      for child in children if child["status"] != "closed"]
        return {"next": "blocked", "reason": "no_ready", "unfinished": unfinished}
    candidate = normalize_issue(ready_raw[0], "ready 候选")
    known = next((child for child in children if child["id"] == candidate["id"]), None)
    valid = (known is not None and known["status"] == candidate["status"] == "open"
             and "ready-for-agent" in candidate["labels"] and candidate["assignee"] is None
             and "ready-for-agent" in known["labels"] and known["assignee"] is None)
    return ({"next": "claim", "ticket_id": candidate["id"]} if valid else
            {"next": "blocked", "reason": "invalid_ready_candidate", "candidate": candidate["id"]})


def normalize_issue(raw: Any, what: str) -> Dict[str, Any]:
    """供纯判定函数使用；错误通过 ValueError 返回给 CLI/采集器适配。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
        raise ValueError(f"{what} 缺少有效的 id 字段")
    if not isinstance(raw.get("status"), str) or not raw["status"]:
        raise ValueError(f"{what} ({raw['id']}) 缺少有效的 status 字段")
    labels = raw.get("labels", [])
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        raise ValueError(f"{what} ({raw['id']}) 的 labels 字段格式无效")
    assignee = raw.get("assignee") or None
    if assignee is not None and not isinstance(assignee, str):
        raise ValueError(f"{what} ({raw['id']}) 的 assignee 字段格式无效")
    return {"id": raw["id"], "status": raw["status"], "labels": list(labels), "assignee": assignee}


def next_(parent_id: str, children: List[Dict[str, Any]], expected_args: List[str], cwd: str) -> None:
    decided = frontier_result(children, expected_args)
    if decided is not None:
        emit(decided); return

    # 查询 ready 候选；有效候选必须是当前 children 中 open、有 ready label、未分配
    ready_out = run_bd(
        [
            "ready",
            "--parent",
            parent_id,
            "--unassigned",
            "--limit",
            "1",
            "--readonly",
            "--json",
        ],
        cwd,
    )
    ready_raw = parse_bd_json(ready_out, "bd ready")
    try:
        emit(frontier_result(children, expected_args, ready_raw))
    except ValueError as error:
        fail(str(error))


def main() -> None:
    _use_utf8()
    argv = sys.argv[1:]
    if len(argv) < 2:
        fail(
            "用法: python3 graph.py check-flat <parent-id> | python3 graph.py next <parent-id> <expected-child-id>..."
        )
    subcommand, parent_id, rest = argv[0], argv[1], argv[2:]
    if subcommand not in ("check-flat", "next"):
        fail("未知子命令: {}".format(subcommand))
    validate_id(parent_id)
    if subcommand == "check-flat" and len(rest) != 0:
        fail("check-flat 只接受一个 parent-id")
    if subcommand == "next":
        if len(rest) == 0:
            fail("next 需要至少一个 expected-child-id")
        for id_ in rest:
            validate_id(id_)
    cwd = os.getcwd()

    # 验证 parent 存在（bd show --json 返回数组）
    show_out = run_bd(["show", parent_id, "--readonly", "--json"], cwd)
    shown = parse_bd_json(show_out, "bd show {}".format(parent_id))
    if not isinstance(shown, list) or not any(
        isinstance(it, dict) and it.get("id") == parent_id for it in shown
    ):
        fail("parent {} 不存在".format(parent_id))

    # 查询 direct children
    list_out = run_bd(
        [
            "list",
            "--parent",
            parent_id,
            "--all",
            "--limit",
            "0",
            "--readonly",
            "--json",
        ],
        cwd,
    )
    child_raw = parse_bd_json(list_out, "bd list --parent {}".format(parent_id))
    if not isinstance(child_raw, list):
        fail("bd list --parent {} 返回的不是数组".format(parent_id))
    children = [validate_issue(it, "child") for it in child_raw]
    if len({child["id"] for child in children}) != len(children):
        fail("children ID 重复")

    if subcommand == "check-flat":
        check_flat(children, cwd)
    else:
        next_(parent_id, children, rest, cwd)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - 对齐 TS 版顶层 catch 行为
        _use_utf8()
        fail(str(error))

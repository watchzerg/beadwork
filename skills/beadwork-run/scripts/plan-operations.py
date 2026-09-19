#!/usr/bin/env python3
"""发布 parent 执行计划或显式接纳剩余票改序；只操作指定 parent 和批次证据。"""

import argparse
import json
import sys

import evidence
import execution_plan as plans
import repository


def prepare(source, output):
    data = evidence.read(source)
    plans.require(set(data) == {"repository_root", "parent_id", "ticket_order"}, "发布输入字段无效")
    root = repository.primary(data["repository_root"])
    value = plans.plan({"ticket_order": data["ticket_order"]})
    parent, _, _, _ = plans.live(root, data["parent_id"], value)
    body = parent.get("description", "")
    after = plans.replace(body, value)
    record = dict(
        repository_root=root,
        parent_id=data["parent_id"],
        plan=value,
        before=body,
        after=after,
        parent_status=parent["status"],
    )
    evidence.write(evidence.absolute(output), record)
    return evidence.binding(output)


def publish(intent_path):
    path = evidence.absolute(intent_path)
    data = evidence.read(path)
    root, parent_id = data["repository_root"], data["parent_id"]
    plans.require(
        data["after"] == plans.replace(data["before"], data["plan"]), "发布 intent 正文不匹配"
    )
    parent, _, _, _ = plans.live(root, parent_id, data["plan"])
    plans.require(
        parent.get("description", "") in (data["before"], data["after"]),
        "parent 正文已变化，请重新 prepare",
    )
    plans.require(parent["status"] == data["parent_status"], "parent 状态已变化")
    if parent.get("description", "") != data["after"]:
        body = path.with_name(path.stem + "-body.md")
        if body.exists():
            plans.require(body.read_text() == data["after"], "发布正文证据已变化")
        else:
            evidence.write(body, data["after"])
        # argv 传文件路径；正文不进入 shell，不改 status、labels 或依赖。
        repository.run(["bd", "update", parent_id, "--body-file", str(body), "--json"], root)
    parent, _, _, value = plans.live(root, parent_id)
    plans.require(
        parent.get("description") == data["after"]
        and parent["status"] == data["parent_status"]
        and value == data["plan"],
        "发布读回不一致，保留现场",
    )
    result = path.with_name(path.stem + "-result.json")
    record = dict(intent=evidence.binding(path), parent_id=parent_id, plan=value)
    if result.exists():
        plans.require(evidence.read(result) == record, "发布结果来源已变化")
    else:
        evidence.write(result, record)
    return evidence.binding(result)


def adopt(source):
    data = evidence.read(source)
    plans.require(
        set(data) == {"repository_root", "parent_id", "ticket_order", "previous", "reason"},
        "接纳输入字段无效",
    )
    root = repository.primary(data["repository_root"])
    plans.require(data["previous"] is not None, "调整必须提供已采用计划的 previous 绑定")
    evidence.bound(data["previous"])
    plans.selected(root, data["parent_id"])
    _, children, _, value = plans.live(root, data["parent_id"])
    plans.require(
        value == plans.plan({"ticket_order": data["ticket_order"]}), "parent 与批准顺序不同"
    )
    return plans.adopt(
        root,
        data["parent_id"],
        value,
        children,
        [evidence.binding(source)],
        data["reason"],
        data["previous"],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("prepare")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p = subs.add_parser("publish")
    p.add_argument("--intent", required=True)
    p = subs.add_parser("adopt")
    p.add_argument("--input", required=True)
    p = subs.add_parser("inspect")
    p.add_argument("--repository-root", required=True)
    p.add_argument("--parent", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.input, args.output)
    elif args.command == "publish":
        result = publish(args.intent)
    elif args.command == "adopt":
        result = adopt(args.input)
    else:
        _, children, _, value = plans.live(args.repository_root, args.parent)
        result = {
            "plan": value,
            "selected": plans.selected(args.repository_root, args.parent, False),
            "unfinished": [x["id"] for x in children if x["status"] != "closed"],
        }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

"""串行计划的解析、实时依赖校验和 append-only 批次选择；不写 Beads。"""

import hashlib
import json
import re
from pathlib import Path
from typing import TypedDict

import evidence
import repository

START = "<!-- beadwork:execution-plan:start -->"
END = "<!-- beadwork:execution-plan:end -->"
require = repository.require


class ExecutionPlan(TypedDict):
    ticket_order: list[str]


def plan(value: object) -> ExecutionPlan:
    if not isinstance(value, dict) or set(value) != {"ticket_order"}:
        raise ValueError("执行计划只能包含 ticket_order")
    raw_order = value["ticket_order"]
    require(isinstance(raw_order, list) and bool(raw_order), "ticket_order 必须为非空数组")
    order: list[str] = []
    for item in raw_order:
        require(
            isinstance(item, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", item)
            and item not in (".", ".."),
            "ticket_order 需要完整有效的 Bead ID",
        )
        if not isinstance(item, str):
            raise TypeError("ticket_order 项必须是字符串")
        order.append(item)
    require(len(order) == len(set(order)), "ticket_order 包含重复 ID")
    return {"ticket_order": list(order)}


def parse(body: object) -> ExecutionPlan:
    if not isinstance(body, str) or body.count(START) != 1 or body.count(END) != 1:
        raise ValueError("parent 必须包含唯一 execution-plan 区块")
    a, b = body.index(START) + len(START), body.index(END)
    require(a < b, "execution-plan marker 顺序错误")
    match = re.fullmatch(r"\s*```json\s*\n(.*?)\n```\s*", body[a:b], re.S)
    if match is None:
        raise ValueError("execution-plan 区块需要唯一 JSON code fence")
    return plan(evidence.loads(match[1]))


def replace(body: str, value: object) -> str:
    require(isinstance(body, str), "parent description 必须为字符串")
    block = (
        START
        + "\n```json\n"
        + json.dumps(plan(value), ensure_ascii=False, indent=2)
        + "\n```\n"
        + END
    )
    if START not in body and END not in body:
        return body + ("\n\n" if body else "") + "## 执行计划\n\n" + block + "\n"
    parse(body)  # 损坏或重复区块不自动修补。
    return body[: body.index(START)] + block + body[body.index(END) + len(END) :]


def validate(value, children, dependencies):
    order = plan(value)["ticket_order"]
    require(
        isinstance(children, list)
        and all(
            isinstance(x, dict)
            and isinstance(x.get("id"), str)
            and isinstance(x.get("status"), str)
            for x in children
        ),
        "children 数据无效",
    )
    ids = [x["id"] for x in children]
    require(len(ids) == len(set(ids)) and set(order) == set(ids), "执行计划与 children 范围不一致")
    require(set(dependencies) == set(ids), "依赖采集未覆盖全部 children")
    positions = {x: i for i, x in enumerate(order)}
    for child, blockers in dependencies.items():
        require(
            isinstance(blockers, list) and all(isinstance(x, str) and x for x in blockers),
            "blocking 依赖格式错误",
        )
        for blocker in blockers:
            if blocker in positions:
                require(
                    positions[blocker] < positions[child],
                    f"执行顺序违反依赖：{child} 依赖 {blocker}",
                )
    active = [x["id"] for x in children if x["status"] == "in_progress"]
    require(len(active) <= 1, "multiple_in_progress")
    pending = [x for x in order if next(c for c in children if c["id"] == x)["status"] != "closed"]
    require(not active or active == pending[:1], "活动票不是计划中第一张未完成票")
    return order


def bd(root, *args):
    value = evidence.loads(repository.run(["bd", *args, "--readonly", "--json"], root))
    require(isinstance(value, list), "bd 查询未返回数组")
    return value


def parent(root, parent_id):
    rows = bd(root, "show", parent_id)
    matches = [x for x in rows if isinstance(x, dict) and x.get("id") == parent_id]
    require(len(matches) == 1, "无法唯一读取 parent")
    return matches[0]


def dependencies(children, query):
    result = {}
    # 单票返回关联 issue，源 ID 由查询绑定；不混用批量 raw edge 的 JSON 形状。
    for child in children:
        rows = query(child["id"])
        require(
            isinstance(rows, list)
            and all(isinstance(x, dict) and isinstance(x.get("id"), str) and x["id"] for x in rows),
            "bd dep list 返回无效依赖",
        )
        result[child["id"]] = [x["id"] for x in rows]
    return result


def live(root, parent_id, value=None):
    p = parent(root, parent_id)
    children = bd(root, "list", "--parent", parent_id, "--all", "--limit", "0")
    require(bool(children), "children 不能为空")
    grandchildren = bd(
        root, "dep", "list", *(x["id"] for x in children), "--direction=up", "--type=parent-child"
    )
    require(not grandchildren, "图未平铺")
    deps = dependencies(
        children, lambda child: bd(root, "dep", "list", child, "--direction=down", "--type=blocks")
    )
    value = parse(p.get("description")) if value is None else plan(value)
    validate(value, children, deps)
    return p, children, deps, value


def folder(root, parent_id):
    require(
        isinstance(parent_id, str)
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parent_id)
        and parent_id not in (".", ".."),
        "parent ID 无效",
    )
    return (
        Path(repository.primary(root)) / ".worktrees" / ".evidence" / parent_id / "execution-plan"
    )


def selected(root, parent_id, required=True):
    directory = folder(root, parent_id)
    path = directory / "initial.json"
    if not path.exists():
        require(not required, "批次尚未接纳执行计划；先完成 READY preflight")
        return None
    previous = None
    seen = set()
    while True:
        binding = evidence.binding(path)
        require(binding["sha256"] not in seen, "计划选择链存在环")
        seen.add(binding["sha256"])
        record = evidence.read(path)
        require(
            record["parent_id"] == parent_id
            and record["repository_root"] == str(directory.parents[3]),
            "计划归属错误",
        )
        plan(record["plan"])
        require(record["previous"] == previous, "计划选择来源链断裂")
        sources = [evidence.read(evidence.bound(source)) for source in record["sources"]]
        require(
            any(
                isinstance(source, dict)
                and (
                    source.get("execution_plan") == record["plan"]
                    or source.get("ticket_order") == record["plan"]["ticket_order"]
                )
                for source in sources
            ),
            "计划与批准来源不符",
        )
        successor = directory / ("after-" + binding["sha256"] + ".json")
        if not successor.exists():
            return binding
        previous, path = binding, successor


def check_selected(root, parent_id, value, children, expected=None, required=True):
    binding = selected(root, parent_id, required)
    if binding is None:
        require(
            all(x["status"] == "open" and not x.get("assignee") for x in children),
            "首次接纳只接受未开工批次；不导入已有执行现场",
        )
        return None
    if expected is not None:
        require(binding == expected, "执行计划选择已变化，旧 intent/dispatch 不可继续开新票")
    record = evidence.read(evidence.bound(binding))
    require(record["plan"] == plan(value), "parent 执行计划已变化；需显式接纳调整")
    states = {x["id"]: x["status"] for x in children}
    require(all(states.get(x) == "closed" for x in record["closed"]), "已关闭票被重新打开或移除")
    for ticket in value["ticket_order"]:
        path = Path(binding["path"]).parent / progress_name(ticket, "closed")
        if path.exists():
            record = evidence.read(path)
            require(record["ticket_id"] == ticket, "完成来源身份不符")
            evidence.bound(record["source"])
            require(states.get(ticket) == "closed", "已完成票被重新打开：" + ticket)
    return binding


def adopt(root, parent_id, value, children, sources, reason, previous=None):
    require(isinstance(reason, str) and reason.strip(), "接纳计划需要明确原因")
    current = selected(root, parent_id, False)
    directory = folder(root, parent_id)
    if current is not None:
        old = evidence.read(evidence.bound(current))
        if old["plan"] == plan(value):
            if previous is not None and previous != current:
                require(
                    old["previous"] == previous
                    and old["sources"] == sources
                    and old["reason"] == reason,
                    "重复接纳来源不符",
                )
            check_selected(root, parent_id, value, children)
            return current
        require(previous == current, "调整需要绑定当前选定计划")
        sync_dir = directory.parent / "main-sync"
        require(
            not any(
                not (path.parent / "ready.json").exists() for path in sync_dir.glob("*/intent.json")
            ),
            "存在未完成 main-sync；先恢复原计划并完成同步，再接纳改序",
        )
        old_order, new_order = old["plan"]["ticket_order"], value["ticket_order"]
        check_selected(root, parent_id, old["plan"], children, expected=current)
        require(set(old_order) == set(new_order), "调整不得改变 children 范围")
        states = {x["id"]: x["status"] for x in children}
        require(all(states.get(x) == "closed" for x in old["closed"]), "已关闭票状态变化")
        protected = {
            x
            for x in old_order
            if states[x] in ("closed", "in_progress")
            or (directory / progress_name(x, "started")).exists()
        }
        require(
            all(old_order.index(x) == new_order.index(x) for x in protected),
            "不得移动已关闭或活动票",
        )
        # 当前 writer 未结束时不接纳重排；恢复原票无需重排。
        require(
            not any(x["status"] == "in_progress" for x in children), "活动票尚未结束，不能接纳重排"
        )
    else:
        require(previous is None, "首次接纳不能指定 previous")
        require(
            all(x["status"] == "open" and not x.get("assignee") for x in children),
            "首次接纳只接受未开工批次；不导入已有执行现场",
        )
    for source in sources:
        evidence.bound(source)
    require(bool(sources), "计划接纳需要来源证据")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / (
        "initial.json" if current is None else "after-" + current["sha256"] + ".json"
    )
    record = dict(
        repository_root=str(directory.parents[3]),
        parent_id=parent_id,
        plan=plan(value),
        closed=[x["id"] for x in children if x["status"] == "closed"],
        previous=current,
        sources=sources,
        reason=reason,
    )
    evidence.write(target, record)
    return evidence.binding(target)


def progress_name(ticket_id, kind):
    require(kind in ("started", "closed"), "进度记录类型无效")
    return kind + "-" + hashlib.sha256(ticket_id.encode()).hexdigest() + ".json"


def progress_path(root, parent_id, ticket_id, kind):
    return folder(root, parent_id) / progress_name(ticket_id, kind)


def record_progress(root, parent_id, ticket_id, kind, source):
    selected(root, parent_id)
    evidence.bound(source)
    path = progress_path(root, parent_id, ticket_id, kind)
    record = {"ticket_id": ticket_id, "source": source}
    if path.exists():
        require(evidence.read(path) == record, "ticket 已有不同执行来源：" + ticket_id)
    else:
        evidence.write(path, record)

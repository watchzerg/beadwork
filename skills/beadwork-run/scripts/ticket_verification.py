"""单票验证来源只扫描一次；固定快照同时用于报告与 gate 覆盖。"""

import shlex

import dispatch_contract
import evidence
import gate_plan
import repository
import verification_records


def attempted_boundaries(starts):
    """从交付尝试累计实测边界，包括失败和未完成记录。"""
    return list(
        dict.fromkeys(
            start["argv"][3]
            for start in starts
            if start.get("delivery_attempt") is not None
            and start["argv"][3] not in ("gate-core", "gate-full")
        )
    )


def delivery_coverage(rows, head, boundaries):
    """按全部 started 记录承担义务；未知结果不能解除义务或覆盖较新的尝试。"""
    deliveries = [row for row in rows if row[0].get("delivery_attempt") is not None]
    repository.require(
        all(start["argv"][3] != "gate-full" for start, _ in deliveries),
        "单票不接受 gate-full 交付记录；最终全量由 finalizer 执行",
    )
    latest = {
        start["argv"][3]: (start, end)
        for start, end in sorted(deliveries, key=lambda row: row[0]["started_ns"])
        if start["before"]["head"] == head
    }
    repository.require("gate-core" in latest, "交付 HEAD 缺少 gate-core 计划来源")
    plan = latest["gate-core"][0].get("gate_plan")
    repository.require(plan is not None, "gate-core 缺少当次 gate-plan 定义")
    attempted = set(attempted_boundaries(start for start, _ in deliveries))
    gate_plan.require_boundaries(plan, sorted(attempted))
    required = set(gate_plan.required_for_ticket(plan, boundaries)) | attempted
    passed = {
        recipe
        for recipe, (start, end) in latest.items()
        if end is not None
        and start["before"] == end["after"] == {"head": head, "status": ""}
        and end["outcome"] == "exited"
        and end["exit_code"] == 0
        and end["process_group_gone"] is True
    }
    return plan, [gate for gate in plan["full"] if gate in required], passed, latest


def origins(d):
    paths = [d["dispatch_path"], *d.get("verification_dispatches", [])]
    repository.require(len(set(paths)) == len(paths), "verification dispatch 不得重复")
    result = {}
    keys = (
        "role",
        "repository_root",
        "worktree",
        "branch",
        "parent_id",
        "ticket_id",
        "base_commit",
        "attempt_id",
    )
    for path in paths:
        origin = dispatch_contract.verification_dispatch(path)
        repository.require(
            all(d.get(k) == origin.get(k) for k in keys), "验证记录属于其他 ticket 或 BASE"
        )
        source = evidence.absolute(path)
        repository.require(source.parent not in result, "验证来源目录重复")
        result[source.parent] = evidence.binding(source)
    return result


def verification_snapshot(d):
    return [
        item
        for source in origins(d).values()
        for item in verification_records.snapshot(source["path"])
    ]


def inspect(d, snapshot, notes, status):
    """逐条读取，不因单条损坏丢弃其余证据；来源归属错误不可降为部分交付。"""
    repository.require(isinstance(snapshot, list), "验证快照必须为列表")
    repository.require(
        isinstance(notes, dict)
        and all(isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in notes.items()),
        "verification_notes 必须为路径到说明的映射",
    )
    allowed = origins(d)
    rows, issues, seen = [], [], set()
    for item in snapshot:
        folder = verification_records.directory(item)
        repository.require(folder.parent in allowed, "验证快照不属于当前来源")
        run_path = str(folder)
        repository.require(run_path not in seen, "验证快照重复")
        seen.add(run_path)
        source = allowed[folder.parent]
        try:
            path, start, end_path, end, _ = verification_records.read(item)
            repository.require(
                start["dispatch_path"] == source["path"]
                and start["dispatch_sha256"] == source["sha256"],
                "验证 dispatch 身份或内容已变化",
            )
            repository.require(start["cwd"] == d["worktree"], "验证 cwd 不符")
            text = "未完成记录；退出结果未知，需确认旧任务已结束"
            if end is not None:
                text = (
                    f"outcome={end['outcome']}；exit_code={end['exit_code']}；"
                    f"耗时={end['duration_seconds']}s；result_sha256={item['result']['sha256']}"
                )
            elif status == "DONE":
                repository.require(
                    run_path in notes, "未完成验证需在 verification_notes 说明收尾确认及后续验证"
                )
            text += (
                f"；运行 HEAD={start['before']['head']}；"
                f"有未提交修改={bool(start['before']['status'])}；证据={folder}"
            )
            if run_path in notes:
                text += "；执行者说明：" + notes[run_path]
            row = {"command": shlex.join(start["argv"]), "result": text}
            rows.append((start, end, end_path, row, run_path))
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append({"source": item, "reason": str(error)})
    repository.require(set(notes) <= seen, "verification_notes 引用了未收集的运行目录")
    return sorted(rows, key=lambda row: (row[0]["started_ns"], row[4])), issues


def collect_verification(d, snapshot, notes, status):
    rows, issues = inspect(d, snapshot, notes, status)
    return [row[3] for row in rows], issues


def collect(current_path, prior_paths, notes, report_status, snapshots=None):
    d = dict(
        dispatch_contract.verification_dispatch(current_path), verification_dispatches=prior_paths
    )
    selected = verification_snapshot(d) if snapshots is None else snapshots
    rows, issues = collect_verification(d, selected, notes, report_status)
    repository.require(not issues, "验证来源损坏：" + "; ".join(item["reason"] for item in issues))
    return rows

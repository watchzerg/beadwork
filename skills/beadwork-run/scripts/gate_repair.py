"""每个逻辑阶段最多三次交付 gate 修正；仅记录事实，不判断代码根因。"""

import json
from pathlib import Path

import evidence
import final_state
import repository
import ticket_state
import verification_records
import workflow_policy

MAX_REPAIRS = workflow_policy.MAX_GATE_REPAIRS


def inherit(d, previous=None):
    # 准备入口覆盖调用者字段；同阶段恢复共用原证据目录。
    d["gate_repair_root"] = (
        previous.get("gate_repair_root", str(Path(previous["dispatch_path"]).parent))
        if previous and previous.get("stage") == d["stage"]
        else str(Path(d["dispatch_path"]).parent)
    )


def root(d):
    p = Path(d.get("gate_repair_root", str(Path(d["dispatch_path"]).parent)))
    repository.require(p.is_absolute() and p.resolve() == p and p.is_dir(), "gate 修正证据目录无效")
    return p


def record(path, value):
    try:
        with path.open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError:
        repository.require(evidence.read(path) == value, "本阶段已有不同的 gate 修正记录")


def repair_path(p, number):
    suffix = "" if number == 1 else f"-{number}"
    return p / f"gate-repair{suffix}.json"


def used_repairs(p):
    present = [repair_path(p, n).exists() for n in range(1, MAX_REPAIRS + 1)]
    used = sum(present)
    repository.require(
        present == [True] * used + [False] * (MAX_REPAIRS - used), "gate 修正记录不连续"
    )
    return used


def freeze(d):
    # review 准入已核验当前 HEAD 的交付来源；这里只冻结阶段。
    record(root(d) / "gate-review-started.json", {"stage": d["stage"]})


def latest_delivery(d):
    """候选事实来自原始验证；同阶段计划适配沿用全部 writer 来源。"""
    if d.get("ticket_scope") == "stage":
        d = evidence.read(evidence.bound(d["implementer_dispatch"]))
    runs = []
    for source in [d["dispatch_path"], *d.get("verification_dispatches", [])]:
        origin = evidence.read(source)
        repository.require(
            all(
                origin.get(key) == d.get(key)
                for key in (
                    "role",
                    "repository_root",
                    "worktree",
                    "branch",
                    "parent_id",
                    "ticket_id",
                    "base_commit",
                    "attempt_id",
                    "stage",
                )
            )
            and root(origin) == root(d),
            "交付验证不属于当前逻辑阶段",
        )
        for item in verification_records.snapshot(source):
            path, start, result_path, end, _ = verification_records.read(item)
            repository.require(
                start["dispatch_path"] == source
                and start["dispatch_sha256"] == evidence.digest(source)
                and start["cwd"] == d["worktree"],
                "交付验证身份或内容已变化",
            )
            if start.get("delivery") is True:
                recipe = "gate-full" if d["role"] == "fixer" else "gate-core"
                repository.require(
                    start["argv"] == ["just", "--one", "--", recipe]
                    and type(start.get("delivery_attempt")) is int
                    and 0 <= start["delivery_attempt"] <= MAX_REPAIRS
                    and not start["before"]["status"],
                    "交付验证候选无效",
                )
                runs.append((path, start, result_path, end))
    return max(runs, key=lambda row: (row[1]["started_ns"], str(row[0]))) if runs else None


def passed(start, end):
    return bool(
        end
        and end["outcome"] == "exited"
        and type(end["exit_code"]) is int
        and end["exit_code"] == 0
        and end["process_group_gone"] is True
        and start["before"] == end["after"]
        and not start["before"]["status"]
    )


def delivery(d, before):
    repository.require(
        d["role"] in ("executor", "implementer", "fixer"), "交付验证需要 writer dispatch"
    )
    repository.require(
        not d.get("ticket_scope") or d["role"] == "implementer", "单票交付验证仅由 implementer 执行"
    )
    if d.get("ticket_scope"):
        ticket_state.require_writer(d)
    repository.require(not before["status"], "交付验证需要干净 HEAD")
    p = root(d)
    repository.require(
        not (p / "gate-review-started.json").exists(), "review 已开始，源码与验证候选保持冻结"
    )
    used = used_repairs(p)
    latest = latest_delivery(d)
    if latest:
        _, start, result_path, end = latest
        attempt = start["delivery_attempt"]
        repository.require(attempt <= used, "交付验证修复次数超出授权")
        if attempt < used:
            repository.require(
                attempt + 1 == used
                and result_path is not None
                and evidence.read(repair_path(p, used))["failure"] == evidence.binding(result_path),
                "修复授权不属于最近交付失败",
            )
        elif before["head"] != start["before"]["head"]:
            repository.require(
                passed(start, end),
                "最近交付未通过；失败须先申请 gate 修复，中断须在原候选重跑",
            )
        repository.git(
            d["worktree"], "merge-base", "--is-ancestor", start["before"]["head"], before["head"]
        )
    else:
        repository.require(not used, "修复授权缺少交付验证来源")
    return used


def failure_source(d, failure):
    """校验并返回属于当前逻辑阶段的原始 delivery gate 失败。"""
    p = root(d)
    result_path = Path(failure).resolve()
    repository.require(result_path.name == "result.json", "需要原始 result.json")
    result = evidence.read(result_path)
    start_path = result_path.parent / "started.json"
    start = evidence.read(start_path)
    origin_path = Path(start["dispatch_path"])
    origin = evidence.read(origin_path)
    same_role = d.get("role") == origin.get("role")
    ticket_recovery = (
        d.get("ticket_scope") == "stage"
        and d.get("role") == "executor"
        and origin.get("role") == "implementer"
    )
    repository.require(same_role or ticket_recovery, "失败 writer 与当前逻辑阶段不符")
    keys = (
        "repository_root",
        "worktree",
        "branch",
        "parent_id",
        "ticket_id",
        "base_commit",
        "stage",
        "attempt_id",
    )
    repository.require(
        all(d.get(k) == origin.get(k) for k in keys) and root(origin) == p, "失败不属于当前逻辑阶段"
    )
    repository.require(
        result_path.parent.parent == origin_path.parent
        and result_path.parent.name.startswith("verification-"),
        "失败证据目录不符",
    )
    log = result_path.parent / "output.log"
    repository.require(
        start["dispatch_sha256"] == evidence.digest(origin_path)
        and result["started_sha256"] == evidence.digest(start_path)
        and result["log_sha256"] == evidence.digest(log)
        and result["log_bytes"] == log.stat().st_size,
        "失败来源或日志已变化",
    )
    attempt = start.get("delivery_attempt")
    repository.require(
        type(attempt) is int
        and 0 <= attempt <= MAX_REPAIRS
        and result["outcome"] == "exited"
        and type(result["exit_code"]) is int
        and result["exit_code"] > 0
        and result["process_group_gone"] is True
        and start["before"] == result["after"]
        and not start["before"]["status"],
        "仅交付候选的正常代码失败可申请修正；不接受开发 red 或中断",
    )
    repository.git(d["worktree"], "merge-base", "--is-ancestor", start["before"]["head"], "HEAD")
    return p, result_path, start, attempt


def begin(args):
    source = Path(args.dispatch).resolve()
    d = evidence.read(source)
    repository.require(
        d.get("dispatch_path") == str(source) and d["role"] in ("executor", "implementer", "fixer"),
        "需要 writer dispatch",
    )
    repository.require(d["role"] != "fixer" or d.get("stage", 0) > 0, "最终 stage 0 没有 fixer")
    repository.require(
        not d.get("ticket_scope") or d["role"] == "implementer",
        "单票 gate-fix 仅由 implementer 执行",
    )
    if d.get("ticket_scope"):
        ticket_state.require_writer(d)
    if final_state.strict(d) and d["role"] == "fixer":
        final_state.require_writer(d)
    repository.topology(d)
    p = root(d)
    repository.require(
        not (p / "gate-review-started.json").exists()
        and not any(x.is_dir() for x in p.glob("review-*")),
        "review 已开始，不能就地修正",
    )
    _, result_path, start, attempt = failure_source(d, args.failure)
    entry = {
        "failure": {"path": str(result_path), "sha256": evidence.digest(result_path)},
        "stage": d["stage"],
    }
    repository.require(attempt < MAX_REPAIRS, "本阶段三次 gate 修正已用尽")
    used = used_repairs(p)
    target = repair_path(p, attempt + 1)
    if not target.exists():
        repository.require(attempt == used, "失败不属于当前交付候选")
        latest = latest_delivery(d)
        repository.require(
            latest is not None and latest[2] == result_path,
            "只能使用最近交付失败申请修复",
        )
        repository.require(
            repository.sha(d["worktree"], "HEAD") == start["before"]["head"]
            and not repository.status(d["worktree"]),
            "申请修正前须保留失败候选的干净 HEAD",
        )
    record(target, entry)
    return {
        "allowed": True,
        "gate_repair_path": str(target),
        "failure_head": start["before"]["head"],
        "repair_number": attempt + 1,
        "remaining_repairs": MAX_REPAIRS - attempt - 1,
    }

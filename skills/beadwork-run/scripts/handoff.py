"""持久化必要上下文及直接派发者观察，不替代宿主任务结束确认。"""

import json
import uuid
from pathlib import Path

import dispatch_contract
import evidence
import phase_validation
import repository


def preflight_input(d):
    source = d.get("preflight_acceptance")
    repository.require(source, "新 ticket 必须提供 preflight_acceptance 来源")
    accepted = evidence.read(evidence.bound(source))
    repository.require(
        accepted.get("kind") == "mechanical_acceptance"
        and accepted.get("role") == "preflight"
        and accepted.get("status") == "READY",
        "需要已验收 READY preflight",
    )
    for key in ("dispatch", "report", "receipt"):
        repository.require(
            evidence.digest(accepted[key + "_path"]) == accepted[key + "_sha256"],
            "preflight 来源已变化",
        )
    pd = evidence.read(accepted["dispatch_path"])
    repository.require(pd["role"] == "preflight", "需要 preflight dispatch")
    directory = Path(accepted["dispatch_path"]).resolve().parent
    for path in (accepted["report_path"], accepted["receipt_path"]):
        repository.require(
            Path(path).resolve().parent == directory, "报告和回执必须位于 dispatch 证据目录"
        )
    result = phase_validation.check(
        "preflight",
        accepted["report_path"],
        accepted["dispatch_path"],
        accepted["receipt_path"],
    )
    repository.require(
        result.get("ok") is True,
        "preflight 报告校验失败：" + json.dumps(result, ensure_ascii=False),
    )
    report = evidence.read(accepted["report_path"])
    repository.require(
        evidence.digest(accepted["report_path"]) == result["report_sha256"],
        "验收期间报告发生变化",
    )
    repository.require(
        pd["parent_id"] == d["parent_id"] and pd["repository_root"] == d["repository_root"],
        "preflight 批次身份不符",
    )
    plan = next((t["test_plan"] for t in report["tickets"] if t["id"] == d["ticket_id"]), None)
    if not plan or plan["mode"] != d["test_mode"] or plan["approved_seams"] != d["approved_seams"]:
        raise ValueError("ticket 计划与 preflight 不符")
    repository.require(report["linked_spec"] == d["linked_spec"], "linked spec 与 preflight 不符")
    d["plan_source"] = {
        "report": evidence.binding(accepted["report_path"]),
        "ticket_id": d["ticket_id"],
    }
    d["environment_evidence"] = list(d.get("environment_evidence", [])) + [
        evidence.binding(d["sync_result"])
    ]
    for item in d["environment_evidence"]:
        evidence.bound(item)


def context_root(d):
    if d.get("ticket_root"):
        return Path(evidence.bound(d["ticket_root"])).parent
    return Path(d.get("attempt_path", Path(d["dispatch_path"]).parent))


def contexts(d):
    root = context_root(d)
    previous = None
    sources = []
    for number, path in enumerate(sorted(root.glob("context-add-" + "[0-9]" * 6 + ".json")), 1):
        value = evidence.read(path)
        repository.require(
            path.name == f"context-add-{number:06d}.json" and value["previous"] == previous,
            "上下文补充链不连续",
        )
        for item in value["sources"]:
            evidence.bound(item)
        sources.append(evidence.binding(str(path)))
        previous = sources[-1]
    return sources


def add_context(dispatch_path, facts):
    d = dispatch_contract.dispatch(dispatch_path)
    repository.require(
        set(facts) == {"sources", "reason"}
        and isinstance(facts["reason"], str)
        and facts["reason"].strip(),
        "上下文补充只接收来源与原因，不修改需求或派发身份",
    )
    repository.require(isinstance(facts["sources"], list) and facts["sources"], "缺少补充事实来源")
    for item in facts["sources"]:
        evidence.bound(item)
    previous = contexts(d)
    path = context_root(d) / f"context-add-{len(previous) + 1:06d}.json"
    evidence.write(path, dict(facts, previous=previous[-1] if previous else None))
    return {"context_source": evidence.binding(str(path)), "dispatch_path": dispatch_path}


def close(dispatch_path, report_path, facts):
    evidence.read(dispatch_path)
    repository.require(Path(report_path).parent == Path(dispatch_path).parent, "收尾报告目录不符")
    required = {"task_id", "stopped", "observed_at", "evidence", "unresolved"}
    repository.require(
        set(facts) == required
        and type(facts["stopped"]) is bool
        and isinstance(facts["unresolved"], list),
        "收尾记录字段无效",
    )
    repository.require(
        all(
            isinstance(facts[k], str) and facts[k].strip()
            for k in ("task_id", "observed_at", "evidence")
        ),
        "收尾观察缺少具体来源",
    )
    repository.require(
        not facts["stopped"] or not facts["unresolved"], "仍有未结束事项，不能确认 stopped"
    )
    report = evidence.read(report_path)
    self_stopped = report.get("stopped_tasks", report.get("execution", {}).get("stopped_tasks"))
    repository.require(
        self_stopped is not False or not facts["stopped"],
        "子 agent 与派发者停止事实矛盾，需先更正来源",
    )
    path = Path(dispatch_path).parent / ("closure-" + uuid.uuid4().hex + ".json")
    evidence.write(
        path,
        dict(facts, dispatch=evidence.binding(dispatch_path), report=evidence.binding(report_path)),
    )
    return {"closure_source": evidence.binding(str(path))}


def closure_binding(source):
    """CLI 可直接接收 handoff-close stdout；内部始终使用裸 binding。"""
    if isinstance(source, dict) and set(source) == {"closure_source"}:
        source = source["closure_source"]
        evidence.bound(source)
    return source


def acceptance_closure(args):
    """验收时保存观察；来源仍由正常验收入口重新核对。"""
    observation = getattr(args, "observation", None)
    closure = getattr(args, "closure", None)
    repository.require(not (observation and closure), "observation 与 closure 选择其一")
    if observation:
        child = Path(args.report).parent / "dispatch.json"
        return close(str(child), args.report, evidence.read(observation))["closure_source"]
    return closure_binding(evidence.read(closure)) if closure else None


def check_close(dispatch_path, report_path, source, required=True):
    source = closure_binding(source)
    repository.require(source or not required, "缺少直接派发者的收尾确认来源")
    if not source:
        return None
    record = evidence.read(evidence.bound(source))
    repository.require(
        type(record.get("stopped")) is bool
        and isinstance(record.get("unresolved"), list)
        and all(
            isinstance(record.get(k), str) and record[k].strip()
            for k in ("task_id", "observed_at", "evidence")
        ),
        "收尾观察字段无效",
    )
    repository.require(
        record["dispatch"] == evidence.binding(dispatch_path)
        and record["report"] == evidence.binding(report_path),
        "收尾来源与交付不符",
    )
    report = evidence.read(report_path)
    advance = (
        report.get("status", "COMPLETED") in ("DONE", "READY", "READY_TO_MERGE", "COMPLETED")
        or report.get("outcome") == "code_failure"
    )
    if advance:
        repository.require(
            record["stopped"] and not record["unresolved"], "未确认任务停止，不能推进"
        )
    return record

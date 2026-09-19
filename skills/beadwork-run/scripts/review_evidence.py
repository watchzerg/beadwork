"""双轴报告与 collection 的只读来源重验，不更新工作流选择。"""


import dispatch_contract
import evidence
import handoff
import report_io
import repository

AXES = ("standards", "spec")

def require_axis_sources(sources):
    if not isinstance(sources, dict) or set(sources) != set(AXES):
        raise ValueError("必须明确提供两个轴的报告与回执")
    for axis in AXES:
        if set(sources[axis]) not in ({"report", "receipt"}, {"report", "receipt", "closure"}):
            raise ValueError("每轴需要 report/receipt 及可选 closure")


def pair_from_sources(round_path, sources, *, verified=None):
    record = evidence.read(round_path)
    d = dispatch_contract.dispatch(evidence.bound(record["dispatch"]))
    base = d["base_commit"] if d["role"] == "executor" else d["reviewed_main"]
    repository.require(record["reviewed_base"] == base, "round BASE 与派发不符")
    if base == record["reviewed_head"]:
        repository.require(record.get("review_kind") == "existing_behavior", "空 diff 缺少已有行为审查身份")
        evidence.bound(record["acceptance_evidence"])
    require_axis_sources(sources)
    pair = {}
    for axis in AXES:
        identity_path = evidence.bound(record["axes"][axis])
        repository.require(identity_path.parent == round_path.parent / axis, "轴目录不符")
        identity = evidence.read(identity_path)
        repository.require(identity["axis"] == axis and identity["reviewed_base"] == base
                  and identity["reviewed_head"] == record["reviewed_head"], "轴身份与 round 不符")
        repository.require(identity.get("review_kind") == record.get("review_kind") and
                  identity.get("acceptance_evidence") == record.get("acceptance_evidence"), "轴审查范围与 round 不符")
        report = evidence.absolute(sources[axis]["report"])
        receipt = evidence.absolute(sources[axis]["receipt"])
        repository.require(report.parent == identity_path.parent and receipt.parent == identity_path.parent,
                  "报告和回执必须位于该轴证据目录")
        handoff.check_close(str(identity_path), str(report), evidence.binding(sources[axis]['closure']) if sources[axis].get('closure') else None,
                            required=identity.get('handoff_required', False))
        # 每次仍检查内容与 closure；只复用相同内容已通过的 reviewer 校验。
        key = tuple((str(path), evidence.digest(path)) for path in (identity_path, report, receipt))
        if verified is None or key not in verified:
            checked = report_io.reviewer("--check-report", report, receipt, "--expected", identity_path)
            repository.require(checked["status"] == "COMPLETED", "reviewer 未完成，保留失败证据并返回 BLOCKED")
            repository.require(evidence.digest(report) == checked["report_sha256"], "验收期间报告发生变化")
            if verified is not None:
                verified.add(key)
        pair[axis] = evidence.read(report)
    gate = "BLOCKED" if any(f["blocking"] for r in pair.values() for f in r["findings"]) else "PASS"
    return record, d, pair, gate


def collection(path, dispatch_path, *, verified=None):
    item = evidence.read(evidence.absolute(path))
    round_path = evidence.bound(item["round"])
    sources = {axis: {key: str(evidence.bound(value)) for key, value in entries.items()}
               for axis, entries in item["sources"].items()}
    record, previous, pair, gate = pair_from_sources(round_path, sources, verified=verified)
    current = dispatch_contract.dispatch(dispatch_path)
    # 接替显式选择旧证据时，保留同票、同 BASE 的已完成轮次。
    keys = ("role", "repository_root", "worktree", "branch", "parent_id", "ticket_id", "base_commit")
    if current.get("ticket_scope"):
        keys += ("ticket_root",)
    if current["role"] == "finalizer":
        keys += ("reviewed_main",)
        if "attempt_id" in previous and "attempt_id" in current:
            keys += ("attempt_id",)
    repository.require(all(previous.get(key) == current.get(key) for key in keys), "review 属于其他 ticket 或 BASE")
    repository.require(item["pair"] == pair and item["gate"] == gate, "聚合结果与原始报告不符")
    return pair, gate

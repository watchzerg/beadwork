#!/usr/bin/env python3
"""preflight/finalizer 阶段报告的只读机械验收。

用法：
  python3 verify-phase.py --schema <preflight|finalizer>
  python3 verify-phase.py --receipt-schema <preflight|finalizer>
  python3 verify-phase.py --check-report <preflight|finalizer> <report.json> [receipt.json] [--expected dispatch.json]

报告和 receipt 都是 append-only 证据；本脚本不会写入 Git、Beads 或报告文件。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.dont_write_bytecode = True

_ticket_spec = importlib.util.spec_from_file_location("verify_ticket", Path(__file__).with_name("verify-ticket.py"))
if _ticket_spec is None or _ticket_spec.loader is None:
    raise RuntimeError("无法加载 verify-ticket.py")
_ticket = importlib.util.module_from_spec(_ticket_spec)
_ticket_spec.loader.exec_module(_ticket)

SHA = _ticket.SHA
TEXT = _ticket.TEXT
TEXTS = _ticket.TEXTS
object_schema = _ticket.object_schema
schema_errors = _ticket.schema_errors
check_schema = _ticket.check_schema
read_json = _ticket.read_json
FULL_SHA = _ticket.FULL_SHA

PHASES = ("preflight", "finalizer")
PREFLIGHT_CHECKS = (
    "parent_state", "children_nonempty", "ready_labels", "flat_graph",
    "spec_and_test_plans", "beads_config", "primary_worktree", "worktree_ignored",
    "branch_name", "beads_clean", "toolchain", "just_recipes", "review_schema", "recovery",
)


def nullable(item: Dict[str, Any]) -> Dict[str, Any]:
    return {"anyOf": [item, {"type": "null"}]}


def receipt_schema(phase: str) -> Dict[str, Any]:
    return object_schema({
        "status": {"enum": ["READY", "BLOCKED"] if phase == "preflight" else ["READY_TO_MERGE", "BLOCKED"]},
        "report_path": TEXT,
        "report_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
    })


def plan_schema() -> Dict[str, Any]:
    return object_schema({
        "mode": {"enum": ["TDD", "direct_verification"]},
        "approved_seams": {"type": "array", "items": TEXT, "uniqueItems": True},
        "boundary_gates": {"type": "array", "items": TEXT, "uniqueItems": True},
        "observable_behavior": nullable(TEXT),
        "expected_red": nullable(TEXT),
        "reason": nullable(TEXT),
        "verification": nullable(TEXT),
    })


def preflight_schema() -> Dict[str, Any]:
    ticket = object_schema({"id": TEXT, "status": TEXT, "test_plan": nullable(plan_schema())})
    schema = object_schema({
        "status": {"enum": ["READY", "BLOCKED"]},
        "parent": object_schema({"id": nullable(TEXT), "status": nullable(TEXT)}),
        "expected_children": {"type": "array", "items": TEXT, "uniqueItems": True},
        "tickets": {"type": "array", "items": ticket},
        "linked_spec": nullable(TEXT),
        "boundary_gates": {"type": "array", "items": TEXT, "uniqueItems": True},
        "workspace": object_schema({"primary_worktree": nullable(TEXT), "implementation_worktree": nullable(TEXT), "branch": nullable(TEXT), "observed_head": nullable(SHA), "clean": nullable({"type": "boolean"})}),
        "resume_evidence": TEXTS,
        "sources": TEXTS,
        "suggested_route": nullable(TEXT),
        "checks": {"type": "array", "items": object_schema({"name": TEXT, "passed": {"type": "boolean"}, "evidence": TEXT})},
        "blockers": TEXTS,
        "remaining_work": TEXTS,
    })
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    return schema


def finalizer_schema(axis: Dict[str, Any]) -> Dict[str, Any]:
    pair = object_schema({"standards": axis, "spec": axis})
    source = object_schema({"path": TEXT, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}})
    schema = object_schema({
        "stage": {"type": "integer", "enum": [0, 1, 2, 3]},
        "attempt_id": TEXT,
        "outcome": {"enum": ["passed", "code_failure", "interrupted", "blocked"]},
        "stage_sources": {"type": "array", "items": source, "minItems": 1},
        "review_sources": {"type": "array", "items": source, "maxItems": 4},
        "fix_sources": {"type": "array", "items": object_schema({key: source for key in ("dispatch", "report", "receipt")})},
        "status": {"enum": ["READY_TO_MERGE", "BLOCKED"]},
        "parent_id": nullable(TEXT),
        "expected_children": {"type": "array", "items": TEXT, "uniqueItems": True},
        "reviewed_main": nullable(SHA), "start_head": nullable(SHA), "head_commit": nullable(SHA),
        "required_gates": {"type": "array", "items": TEXT, "uniqueItems": True},
        "boundary_gates": {"type": "array", "items": TEXT, "uniqueItems": True},
        "gate_sources": {"type": "array", "items": object_schema({"gate": TEXT, "source": TEXT})},
        "verification": {"type": "array", "items": object_schema({"gate": TEXT, "command": TEXT, "result": TEXT, "log_path": TEXT, "head_commit": nullable(SHA), "passed": {"type": "boolean"}})},
        "fix": object_schema({"used": {"type": "boolean"}, "commits": {"type": "array", "items": SHA, "uniqueItems": True}, "dispositions": TEXTS}),
        "review_rounds": {"type": "array", "items": pair, "maxItems": 4},
        "workspace": object_schema({"branch": nullable(TEXT), "observed_head": nullable(SHA), "clean": {"type": "boolean"}}),
        "sources": TEXTS, "stopped_tasks": {"type": "boolean"}, "blockers": TEXTS, "remaining_work": TEXTS,
    }, optional=("stage", "attempt_id", "outcome", "stage_sources", "review_sources", "fix_sources"))
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    return schema


def schema_for(phase: str, axis: Dict[str, Any]) -> Dict[str, Any]:
    return preflight_schema() if phase == "preflight" else finalizer_schema(axis)


def fail(check: str, **extra: Any) -> Dict[str, Any]:
    return {"check": check, **extra}


def unique_ids(items: List[Dict[str, Any]]) -> bool:
    ids = [item["id"] for item in items]
    return len(ids) == len(set(ids))


def dispatch_failures(phase: str, expected: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if expected is None:
        return []
    required = (
        ("repository_root", "parent_id", "expected_branch", "expected_worktree", "rules_paths", "skill_dir", "report_path", "dispatch_path")
        if phase == "preflight" else
        ("repository_root", "worktree", "branch", "parent_id", "expected_children", "linked_spec", "rules_paths", "skill_dir", "reviewed_main", "start_head", "ticket_evidence", "required_boundary_gates", "prior_finalization", "report_path", "dispatch_path")
    )
    if not isinstance(expected, dict) or any(key not in expected for key in required):
        return [fail("dispatch_schema")]
    if not isinstance(expected["parent_id"], str) or not expected["parent_id"]:
        return [fail("dispatch_schema")]
    if phase == "finalizer":
        if not isinstance(expected["expected_children"], list) or not isinstance(expected["required_boundary_gates"], list):
            return [fail("dispatch_schema")]
        prior = expected["prior_finalization"]
        if prior is not None and not (isinstance(prior, dict) and isinstance(prior.get("stage_path"), str) and prior["stage_path"]) and (
            not isinstance(prior, dict)
            or type(prior.get("fix_used")) is not bool
            or type(prior.get("review_rounds_used")) is not int
            or prior["review_rounds_used"] not in (0, 1, 2)
            or not isinstance(prior.get("report_path"), str)
            or not prior["report_path"].strip()
        ):
            return [fail("dispatch_schema")]
    return []


def preflight_failures(report: Dict[str, Any], expected: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    failures = dispatch_failures("preflight", expected)
    if failures:
        return failures
    if expected and report["status"] == "READY":
        if report["parent"]["id"] != expected.get("parent_id"):
            failures.append(fail("parent_matches_dispatch"))
        if report["workspace"]["primary_worktree"] != expected.get("repository_root") or report["workspace"]["branch"] != expected.get("expected_branch") or report["workspace"]["implementation_worktree"] != expected.get("expected_worktree"):
            failures.append(fail("workspace_matches_dispatch"))
        if "expected_children" in expected and set(report["expected_children"]) != set(expected["expected_children"]):
            failures.append(fail("children_match_dispatch"))
    if report["status"] != "READY":
        return failures
    if not report["expected_children"] or not unique_ids(report["tickets"]) or set(item["id"] for item in report["tickets"]) != set(report["expected_children"]):
        failures.append(fail("tickets_match_unique_children"))
    if report["blockers"] or report["remaining_work"]:
        failures.append(fail("ready_has_no_blockers"))
    if report["parent"]["id"] is None or report["parent"]["status"] is None or report["suggested_route"] not in ("new_batch", "resume_tickets", "finalize", "post_merge"):
        failures.append(fail("ready_parent_and_route"))
    check_names = [item["name"] for item in report["checks"]]
    if set(check_names) != set(PREFLIGHT_CHECKS) or len(check_names) != len(set(check_names)) or any(not item["passed"] for item in report["checks"]):
        failures.append(fail("all_preflight_checks_passed"))
    gates = set()
    for item in report["tickets"]:
        plan = item["test_plan"]
        if item["status"] == "closed":
            continue
        if plan is None:
            failures.append(fail("ready_ticket_has_plan", ticket=item["id"]))
            continue
        gates.update(plan["boundary_gates"])
        if plan["mode"] == "TDD" and (not plan["approved_seams"] or plan["observable_behavior"] is None or plan["expected_red"] is None):
            failures.append(fail("tdd_plan_complete", ticket=item["id"]))
        if plan["mode"] == "direct_verification" and (plan["approved_seams"] or plan["reason"] is None or plan["verification"] is None):
            failures.append(fail("direct_plan_complete", ticket=item["id"]))
    if gates != set(report["boundary_gates"]):
        failures.append(fail("boundary_gates_are_ticket_union"))
    if any(not gate.startswith("gate-") for gate in gates):
        failures.append(fail("boundary_gate_names"))
    return failures


def pair_failures(pair: Dict[str, Any], base: str, head: str | None, axis_schema: Dict[str, Any], round_: int) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    for name in ("standards", "spec"):
        result = pair[name]
        if schema_errors(result, axis_schema):
            failures.append(fail("review_report_schema", round=round_, axis=name))
            continue
        if result.get("axis") != name or result.get("reviewed_base") != base or (head is not None and result.get("reviewed_head") != head):
            failures.append(fail("review_sha_binding", round=round_, axis=name))
    if pair["standards"].get("reviewed_head") != pair["spec"].get("reviewed_head"):
        failures.append(fail("review_heads_agree", round=round_))
    return failures


def finalizer_failures(report: Dict[str, Any], expected: Dict[str, Any] | None, axis: Dict[str, Any]) -> List[Dict[str, Any]]:
    failures = dispatch_failures("finalizer", expected)
    if failures:
        return failures
    modern = "stage" in report or (expected is not None and expected.get("finalization_version") == 1)
    if modern:
        fields = ("stage", "attempt_id", "outcome", "stage_sources", "review_sources", "fix_sources")
        if any(key not in report for key in fields):
            return [fail("final_stage_fields")]
        if expected:
            if report["attempt_id"] != expected.get("attempt_id") or ("stage" in expected and report["stage"] != expected["stage"]):
                failures.append(fail("final_stage_identity"))
        if (report["outcome"] == "passed") != (report["status"] == "READY_TO_MERGE"):
            failures.append(fail("final_outcome_status"))
        if report["fix"]["used"] != (report["stage"] > 0):
            failures.append(fail("repair_stage"))
        if len(report["review_rounds"]) != len(report["review_sources"]) or len(report["review_rounds"]) > report["stage"] + 1:
            failures.append(fail("review_round_limit"))
        for index, pair in enumerate(report["review_rounds"], 1):
            failures.extend(pair_failures(pair, report["reviewed_main"], None, axis, index))
    if expected and (modern or report["status"] == "READY_TO_MERGE"):
        for key in ("parent_id", "reviewed_main", "start_head"):
            if report.get(key) != expected.get(key):
                failures.append(fail(key + "_matches_dispatch"))
        if set(report["expected_children"]) != set(expected.get("expected_children", [])):
            failures.append(fail("children_match_dispatch"))
        if set(report["required_gates"]) != set(expected.get("required_boundary_gates", [])):
            failures.append(fail("required_gates_match_dispatch"))
        workspace = report["workspace"]
        if workspace["branch"] != expected.get("branch") or workspace["observed_head"] != report["head_commit"] or (
            report["status"] == "READY_TO_MERGE" and not workspace["clean"]
        ):
            failures.append(fail("workspace_ready"))
    if report["status"] != "READY_TO_MERGE":
        return failures
    if report["blockers"] or report["remaining_work"]:
        failures.append(fail("ready_has_no_blockers"))
    if not report["stopped_tasks"]:
        failures.append(fail("writers_and_reviewers_stopped"))
    if not modern and len(report["fix"]["commits"]) != int(report["fix"]["used"]):
        failures.append(fail("repair_limit"))
    if not report["review_rounds"] or (not modern and (len(report["review_rounds"]) > 2 or (len(report["review_rounds"]) == 2 and not report["fix"]["used"]))):
        failures.append(fail("review_round_limit"))
    prior = expected.get("prior_finalization") if expected else None
    if isinstance(prior, dict):
        if prior.get("fix_used") is True and (not report["fix"]["used"] or not report["fix"]["commits"]):
            failures.append(fail("repair_limit"))
        if isinstance(prior.get("review_rounds_used"), int) and len(report["review_rounds"]) < prior["review_rounds_used"]:
            failures.append(fail("review_round_limit"))
    head, base = report["head_commit"], report["reviewed_main"]
    if head is None or base is None:
        failures.append(fail("ready_commit_identity"))
    else:
        for index, pair in enumerate(report["review_rounds"], 1):
            failures.extend(pair_failures(pair, base, head if index == len(report["review_rounds"]) else None, axis, index))
        final_pair = report["review_rounds"][-1] if report["review_rounds"] else None
        if final_pair and any(f.get("blocking") for item in final_pair.values() for f in item.get("findings", [])):
            failures.append(fail("final_review_gate_pass"))
    if not set(report["required_gates"]).issubset(report["boundary_gates"]) or any(
        not gate.startswith("gate-") or gate == "gate-full" for gate in report["boundary_gates"]
    ):
        failures.append(fail("boundary_gate_names"))
    required = set(report["required_gates"]) | set(report["boundary_gates"]) | {"final"}
    sourced = {item["gate"] for item in report["gate_sources"]}
    if not set(report["boundary_gates"]).issubset(sourced):
        failures.append(fail("boundary_gate_sources"))
    # verification 按时间顺序追加；同一 gate 以交付 HEAD 的最后一次结果为准。
    latest: Dict[str, Dict[str, Any]] = {}
    for item in report["verification"]:
        if item["head_commit"] == report["head_commit"]:
            latest[item["gate"]] = item
    passed = {gate for gate, item in latest.items() if item["passed"]}
    if not required.issubset(passed):
        failures.append(fail("required_gates_covered", missing=sorted(required - passed)))
    return failures


def validate(phase: str, report: Any, axis: Dict[str, Any], expected: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    schema = schema_for(phase, axis)
    if phase == "finalizer" and expected and expected.get("report_schema_path"):
        schema = read_json(expected["report_schema_path"])[0]
    problems = schema_errors(report, schema)
    if problems:
        return [fail("report_schema", observed=problems)]
    return preflight_failures(report, expected) if phase == "preflight" else finalizer_failures(report, expected, axis)


def main(argv: List[str]) -> None:
    emit_receipt = "--emit-receipt" in argv
    if emit_receipt:
        argv = list(argv)
        argv.remove("--emit-receipt")
        if not argv or argv[0] != "--check-report":
            raise ValueError("--emit-receipt 仅用于报告自检")
    if len(argv) == 2 and argv[0] == "--schema" and argv[1] in PHASES:
        axis = _ticket.axis_report_schema(); schema = schema_for(argv[1], axis); check_schema(schema)
        print(json.dumps(schema, ensure_ascii=False, separators=(",", ":"))); return
    if len(argv) == 2 and argv[0] == "--receipt-schema" and argv[1] in PHASES:
        print(json.dumps(receipt_schema(argv[1]), ensure_ascii=False, separators=(",", ":"))); return
    if len(argv) < 3 or argv[0] != "--check-report" or argv[1] not in PHASES:
        raise ValueError("用法：--check-report <preflight|finalizer> <report> [receipt] [--expected dispatch]")
    phase, report_path = argv[1:3]
    tail = argv[3:]
    expected_path = None
    if "--expected" in tail:
        position = tail.index("--expected")
        if position + 1 >= len(tail) or position + 2 != len(tail): raise ValueError("--expected 必须位于末尾")
        expected_path = tail[position + 1]; tail = tail[:position]
    if len(tail) > 1: raise ValueError("receipt 参数过多")
    axis = _ticket.axis_report_schema(); report, digest = read_json(report_path)
    expected = read_json(expected_path)[0] if expected_path else None
    failures = validate(phase, report, axis, expected)
    if tail:
        receipt, _ = read_json(tail[0]); problems = schema_errors(receipt, receipt_schema(phase))
        if problems: failures.append(fail("receipt_schema", observed=problems))
        else:
            wanted = {"status": report.get("status") if isinstance(report, dict) else None, "report_path": os.path.abspath(report_path), "report_sha256": digest}
            for key, value in wanted.items():
                if receipt[key] != value: failures.append(fail("receipt_" + key + "_matches"))
    if emit_receipt:
        if tail or failures:
            raise ValueError(json.dumps(failures or ["receipt 自检不接受已有 receipt"], ensure_ascii=False))
        print(json.dumps({"status": report["status"], "report_path": os.path.abspath(report_path), "report_sha256": digest}))
        return
    print(json.dumps({"ok": not failures, "report_sha256": digest, **({"failures": failures} if failures else {})}, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    try: main(sys.argv[1:])
    except Exception as error:
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n"); sys.exit(1)

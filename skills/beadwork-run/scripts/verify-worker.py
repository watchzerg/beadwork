#!/usr/bin/env python3
"""implementer/fixer/reviewer 的文件报告、短回执及派发身份校验；仅标准库。

用法：
  --schema <implementer|fixer|reviewer>
  --receipt-schema <implementer|fixer|reviewer>
  --check-report <implementer|fixer|reviewer> <report.json> [receipt.json] --expected <dispatch.json>

输出紧凑 JSON；ok:false 表示验收失败，非零退出表示输入或命令失败。
不写入源码、Git、Beads 或报告；Git 现场由直接派发者验收。
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import schema_validation
import review_schema

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("ticket_validator", Path(__file__).with_name("verify-ticket.py"))
assert spec and spec.loader
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
TEXT, SHA, TEXTS, obj = (schema_validation.TEXT, schema_validation.SHA,
                         schema_validation.TEXTS, schema_validation.object_schema)
ROLES = ("fixer", "reviewer", "implementer")


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def receipt_schema(role):
    return obj({"status": {"enum": ["DONE", "NEEDS_CONTEXT", "BLOCKED"] if role == "implementer" else ["DONE", "BLOCKED"] if role == "fixer" else ["COMPLETED", "BLOCKED"]},
                "report_path": TEXT, "report_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"}})


def report_schema(role, axis_schema):
    if role == "implementer":
        import ticket_execution
        return ticket_execution.implementer_schema(v)
    if role == "reviewer":
        # 成功报告保留本流程 AxisReport；无法完成审查时使用本地失败报告，不伪造 findings。
        return {"oneOf": [axis_schema, obj({
            "status": {"const": "BLOCKED"}, "axis": {"enum": ["standards", "spec"]},
            "reviewed_base": SHA, "reviewed_head": SHA,
            "blockers": {**TEXTS, "minItems": 1},
        })]}
    return obj({
        "stage": {"type": "integer", "enum": [1, 2, 3]}, "attempt_id": TEXT,
        "outcome": {"enum": ["passed", "code_failure", "interrupted", "blocked"]},
        "fix_commits": {"type": "array", "items": SHA, "uniqueItems": True},
        "status": {"enum": ["DONE", "BLOCKED"]}, "parent_id": TEXT, "branch": TEXT,
        "base_commit": SHA, "head_commit": nullable(SHA), "fix_commit": nullable(SHA),
        "dispositions": {"type": "array", "items": obj({"source": TEXT, "action": TEXT})},
        "boundary_gates": {**TEXTS, "uniqueItems": True},
        "gate_sources": {"type": "array", "items": obj({"gate": TEXT, "source": TEXT})},
        "verification": {"type": "array", "items": obj({
            "gate": TEXT, "command": TEXT, "head_commit": nullable(SHA),
            "passed": {"type": "boolean"}, "result": TEXT, "log_path": TEXT,
        })},
        "verification_sources": {"type": "array", "items": {"type": "object"}},
        "verification_notes": {"type": "object"},
        "verification_issues": {"type": "array", "items": {"type": "object"}},
        "worktree_clean": {"type": "boolean"}, "stopped_tasks": {"type": "boolean"},
        "uncommitted_files": TEXTS, "blockers": TEXTS, "remaining_work": TEXTS,
    }, optional=("stage", "attempt_id", "outcome", "fix_commits", "fix_commit", "verification_sources", "verification_notes", "verification_issues"))


def dispatch_schema(role):
    # 其余任务上下文由 prompt 交接；这里只校验验收需要的身份与 gate 下限。
    fields = ({"axis": {"enum": ["standards", "spec"]}, "reviewed_base": SHA, "reviewed_head": SHA}
              if role == "reviewer" else
              {"parent_id": TEXT, "branch": TEXT, "base_commit": SHA,
               "required_boundary_gates": {**TEXTS, "uniqueItems": True}})
    schema = obj(fields)
    schema["additionalProperties"] = True
    return schema


def validate(role, report, axis_schema, expected):
    if role == "implementer":
        import ticket_execution
        return ticket_execution.implementer_errors(report, expected, v)
    problems = v.schema_errors(expected, dispatch_schema(role))
    if problems:
        return ["dispatch_schema: " + problem for problem in problems]
    problems = v.schema_errors(report, report_schema(role, axis_schema))
    if problems:
        return ["report_schema: " + problem for problem in problems]
    keys = ("axis", "reviewed_base", "reviewed_head") if role == "reviewer" else ("parent_id", "branch", "base_commit")
    failures = [key + "_matches_dispatch" for key in keys if report[key] != expected[key]]
    if role == "reviewer":
        if report.get("status") != "BLOCKED" and any(finding["axis"] != expected["axis"] for finding in report["findings"]):
            failures.append("finding_axis_matches_dispatch")
        return failures
    if "stage" in expected or "stage" in report:
        if any(key not in report for key in ("stage", "attempt_id", "outcome", "fix_commits")):
            return failures + ["fixer_stage_fields"]
        if report["stage"] != expected.get("stage") or report["attempt_id"] != expected.get("attempt_id"):
            failures.append("fixer_stage_identity")
        if (report["outcome"] == "passed") != (report["status"] == "DONE"):
            failures.append("fixer_outcome_status")
        if report["fix_commits"] and report["fix_commits"][-1] != report["head_commit"]:
            failures.append("fixer_commit_head")
    if expected.get('finalization_version') == 2:
        import final_verification
        try:
            final_verification.check(expected, report)
        except Exception as error:
            failures.append('fixer_verification: ' + str(error))
    if report["status"] == "BLOCKED":
        if not report["blockers"]:
            failures.append("blocked_has_reason")
        return failures
    if report["blockers"] or report["remaining_work"] or report["uncommitted_files"]:
        failures.append("done_has_no_unfinished_work")
    if not report["worktree_clean"] or not report["stopped_tasks"]:
        failures.append("done_clean_and_stopped")
    commits = report.get("fix_commits", [report["fix_commit"]] if report.get("fix_commit") else [])
    if not commits or commits[-1] != report["head_commit"] or report["head_commit"] == report["base_commit"]:
        failures.append("fix_commit_is_new_delivery_head")
    if not report["dispositions"]:
        failures.append("fix_has_dispositions")
    gates = set(report["boundary_gates"])
    if not set(expected["required_boundary_gates"]).issubset(gates):
        failures.append("required_gates_retained")
    if any(not gate.startswith("gate-") or gate == "gate-full" for gate in gates):
        failures.append("boundary_gate_names")
    if not gates.issubset({item["gate"] for item in report["gate_sources"]}):
        failures.append("boundary_gate_sources")
    latest = {item["gate"]: item for item in report["verification"] if item["head_commit"] == report["head_commit"]}
    if not (gates | {"final"}).issubset({gate for gate, item in latest.items() if item["passed"]}):
        failures.append("final_validation_on_delivery_head")
    return failures


def main(argv):
    emit_receipt = "--emit-receipt" in argv
    if emit_receipt:
        argv = list(argv)
        argv.remove("--emit-receipt")
        if not argv or argv[0] != "--check-report":
            raise ValueError("--emit-receipt 仅用于报告自检")
    if len(argv) == 2 and argv[0] == "--receipt-schema" and argv[1] in ROLES:
        print(json.dumps(receipt_schema(argv[1]), ensure_ascii=False)); return
    if len(argv) == 2 and argv[0] == "--schema" and argv[1] in ROLES:
        axis = review_schema.axis_report_schema(); schema_validation.check_schema(axis)
        schema = report_schema(argv[1], axis); schema_validation.check_schema(schema)
        print(json.dumps(schema, ensure_ascii=False)); return
    if len(argv) not in (5, 6) or argv[0] != "--check-report" or argv[1] not in ROLES or argv[-2] != "--expected":
        raise ValueError("用法：--check-report <role> <report> [receipt] --expected <dispatch>")
    role, path = argv[1:3]
    axis = review_schema.axis_report_schema(); schema_validation.check_schema(axis)
    report, digest = v.read_json(path)
    expected, _ = v.read_json(argv[-1])
    failures = validate(role, report, axis, expected)
    status = report.get("status", "COMPLETED") if isinstance(report, dict) else None
    if len(argv) == 6:
        receipt, _ = v.read_json(argv[3])
        failures.extend("receipt_schema: " + problem for problem in v.schema_errors(receipt, receipt_schema(role)))
        if not v.schema_errors(receipt, receipt_schema(role)):
            for key, value in {"status": status, "report_path": os.path.abspath(path), "report_sha256": digest}.items():
                if receipt[key] != value:
                    failures.append("receipt_" + key + "_matches")
    if emit_receipt:
        if len(argv) != 5 or failures:
            raise ValueError(json.dumps(failures or ["receipt 自检不接受已有 receipt"], ensure_ascii=False))
        print(json.dumps({"status": status, "report_path": os.path.abspath(path), "report_sha256": digest}))
        return
    result = {"ok": not failures, "status": status, "report_sha256": digest}
    if failures:
        result["failures"] = failures
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except Exception as error:
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        sys.exit(1)

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

import json
import os
import sys

sys.dont_write_bytecode = True

import final_verification
import implementer_reports
import review_context
import review_schema
import schema_validation
import verify_ticket as v
import workflow_contract
import workflow_policy

TEXT, SHA, TEXTS, obj = (
    schema_validation.TEXT,
    schema_validation.SHA,
    schema_validation.TEXTS,
    schema_validation.object_schema,
)
ROLES = ("fixer", "reviewer", "implementer")


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def receipt_schema(role):
    return obj(
        {
            "status": {
                "enum": ["DONE", "NEEDS_CONTEXT", "BLOCKED"]
                if role == "implementer"
                else ["DONE", "BLOCKED"]
                if role == "fixer"
                else ["COMPLETED", "BLOCKED"]
            },
            "report_path": TEXT,
            "report_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        }
    )


def report_schema(role, axis_schema):
    if role == "implementer":
        return implementer_reports.implementer_schema()
    if role == "reviewer":
        # 成功报告保留本流程 AxisReport；无法完成审查时使用本地失败报告，不伪造 findings。
        return {
            "oneOf": [
                axis_schema,
                obj(
                    {
                        "status": {"const": "BLOCKED"},
                        "axis": {"enum": ["standards", "spec"]},
                        "reviewed_base": SHA,
                        "reviewed_head": SHA,
                        "blockers": {**TEXTS, "minItems": 1},
                    }
                ),
            ]
        }
    return obj(
        {
            "stage": {
                "type": "integer",
                "enum": list(range(1, len(workflow_policy.FINAL_STAGE_MODELS))),
            },
            "attempt_id": TEXT,
            "outcome": {"enum": ["passed", "code_failure", "interrupted", "blocked"]},
            "fix_commits": {"type": "array", "items": SHA, "uniqueItems": True},
            "status": {"enum": ["DONE", "BLOCKED"]},
            "parent_id": TEXT,
            "branch": TEXT,
            "base_commit": SHA,
            "head_commit": nullable(SHA),
            "fix_commit": nullable(SHA),
            "dispositions": {"type": "array", "items": obj({"source": TEXT, "action": TEXT})},
            "verification": {
                "type": "array",
                "items": obj(
                    {
                        "gate": TEXT,
                        "command": TEXT,
                        "head_commit": nullable(SHA),
                        "passed": {"type": "boolean"},
                        "result": TEXT,
                        "log_path": TEXT,
                    }
                ),
            },
            "verification_sources": {"type": "array", "items": {"type": "object"}},
            "verification_notes": {"type": "object"},
            "verification_issues": {"type": "array", "items": {"type": "object"}},
            "worktree_clean": {"type": "boolean"},
            "stopped_tasks": {"type": "boolean"},
            "uncommitted_files": TEXTS,
            "blockers": TEXTS,
            "remaining_work": TEXTS,
        },
        optional=(
            "stage",
            "attempt_id",
            "outcome",
            "fix_commits",
            "fix_commit",
            "verification_sources",
            "verification_notes",
            "verification_issues",
        ),
    )


def dispatch_schema(role):
    # 其余任务上下文由 prompt 交接；这里只校验验收需要的身份。
    fields = (
        {"axis": {"enum": ["standards", "spec"]}, "reviewed_base": SHA, "reviewed_head": SHA}
        if role == "reviewer"
        else {
            "parent_id": TEXT,
            "branch": TEXT,
            "base_commit": SHA,
        }
    )
    schema = obj(fields)
    schema["additionalProperties"] = True
    return schema


def validate(role, report, axis_schema, expected):
    try:
        workflow_contract.require_current(expected)
    except ValueError as error:
        return ["dispatch_contract: " + str(error)]
    if role == "implementer":
        return implementer_reports.implementer_errors(report, expected)
    problems = v.schema_errors(expected, dispatch_schema(role))
    if problems:
        return ["dispatch_schema: " + problem for problem in problems]
    problems = v.schema_errors(report, report_schema(role, axis_schema))
    if problems:
        return ["report_schema: " + problem for problem in problems]
    keys = (
        ("axis", "reviewed_base", "reviewed_head")
        if role == "reviewer"
        else ("parent_id", "branch", "base_commit")
    )
    failures = [key + "_matches_dispatch" for key in keys if report[key] != expected[key]]
    if role == "reviewer":
        try:
            review_context.check(expected)
        except Exception as error:
            failures.append("verification_view: " + str(error))
        if report.get("status") != "BLOCKED" and any(
            finding["axis"] != expected["axis"] for finding in report["findings"]
        ):
            failures.append("finding_axis_matches_dispatch")
        return failures
    if "stage" in expected or "stage" in report:
        if any(key not in report for key in ("stage", "attempt_id", "outcome", "fix_commits")):
            return failures + ["fixer_stage_fields"]
        if report["stage"] != expected.get("stage") or report["attempt_id"] != expected.get(
            "attempt_id"
        ):
            failures.append("fixer_stage_identity")
        if (report["outcome"] == "passed") != (report["status"] == "DONE"):
            failures.append("fixer_outcome_status")
        if report["fix_commits"] and report["fix_commits"][-1] != report["head_commit"]:
            failures.append("fixer_commit_head")
    if expected.get("role") == "fixer" and "attempt_id" in expected:
        try:
            final_verification.check(expected, report)
        except Exception as error:
            failures.append("fixer_verification: " + str(error))
    if report["status"] == "BLOCKED":
        if not report["blockers"]:
            failures.append("blocked_has_reason")
        return failures
    if report["blockers"] or report["remaining_work"] or report["uncommitted_files"]:
        failures.append("done_has_no_unfinished_work")
    if not report["worktree_clean"] or not report["stopped_tasks"]:
        failures.append("done_clean_and_stopped")
    commits = report.get("fix_commits", [report["fix_commit"]] if report.get("fix_commit") else [])
    if (
        not commits
        or commits[-1] != report["head_commit"]
        or report["head_commit"] == report["base_commit"]
    ):
        failures.append("fix_commit_is_new_delivery_head")
    if not report["dispositions"]:
        failures.append("fix_has_dispositions")
    latest = {
        item["gate"]: item
        for item in report["verification"]
        if item["head_commit"] == report["head_commit"]
    }
    required = {"gate-full"}
    if not required.issubset({gate for gate, item in latest.items() if item["passed"]}):
        failures.append("final_validation_on_delivery_head")
    return failures


def check(role, report_path, expected_path, receipt_path=None):
    """校验 worker 报告并返回 CLI 同形结果，不启动子进程。"""
    axis = review_schema.axis_report_schema()
    schema_validation.check_schema(axis)
    report, digest = v.read_json(report_path)
    expected, _ = v.read_json(expected_path)
    failures = validate(role, report, axis, expected)
    status = report.get("status", "COMPLETED") if isinstance(report, dict) else None
    if receipt_path:
        receipt, _ = v.read_json(receipt_path)
        problems = v.schema_errors(receipt, receipt_schema(role))
        failures.extend("receipt_schema: " + problem for problem in problems)
        if not problems:
            wanted = {
                "status": status,
                "report_path": os.path.abspath(report_path),
                "report_sha256": digest,
            }
            failures.extend(
                "receipt_" + key + "_matches"
                for key, value in wanted.items()
                if receipt[key] != value
            )
    return {
        "ok": not failures,
        "status": status,
        "report_sha256": digest,
        **({"failures": failures} if failures else {}),
    }


def schema(role, receipt=False):
    """返回 worker 报告或回执 schema。"""
    if receipt:
        return receipt_schema(role)
    axis = review_schema.axis_report_schema()
    schema_validation.check_schema(axis)
    result = report_schema(role, axis)
    schema_validation.check_schema(result)
    return result


def execute(args):
    """执行已经由统一 CLI 解析的 worker 报告校验。"""
    if args.schema:
        return schema(args.schema)
    if args.receipt_schema:
        return receipt_schema(args.receipt_schema)
    role, path = args.role, args.check_report
    result = check(role, path, args.expected, args.receipt)
    failures = result.get("failures", [])
    status, digest = result["status"], result["report_sha256"]
    if args.emit_receipt:
        if args.receipt or failures:
            raise ValueError(
                json.dumps(failures or ["receipt 自检不接受已有 receipt"], ensure_ascii=False)
            )
        return {"status": status, "report_path": os.path.abspath(path), "report_sha256": digest}
    return result

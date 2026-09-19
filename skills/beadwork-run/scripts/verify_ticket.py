#!/usr/bin/env python3
"""beadwork-run 内置只读验收脚本。

用法:
  python3 verify-ticket.py --schema
  python3 verify-ticket.py --receipt-schema
  python3 verify-ticket.py --check-report <executor-report.json> [<receipt.json>]
  python3 verify-ticket.py <branch> <BASE> <HEAD> <status> <executor-report.json> <expected-plan.json>

校验结果为紧凑 JSON：ok、原始报告的 report_sha256，以及失败时的 failures；--schema 输出报告 schema，--receipt-schema 输出返回回执 schema。
仅对 Git 只读（symbolic-ref/rev-parse/rev-list/cat-file/merge-base/log/status），无任何写操作。

运行要求：Python >= 3.9，仅标准库。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import json
import os
import re
import subprocess
import sys

from review_schema import axis_report_schema
from schema_validation import object_schema, TEXT, SHA, TEXTS, SEAMS, schema_errors, check_schema, read_json
import evidence
import workflow_contract
import workflow_policy


FULL_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _use_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def git(args: List[str], allowed_codes: Tuple[int, ...] = (0,), cwd: str | None = None) -> Dict[str, Any]:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    code: Optional[int] = None
    stderr_text = ""
    stdout_text = ""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd or os.getcwd(), env=env, capture_output=True
        )
        code = proc.returncode
        stderr_text = proc.stderr.decode("utf-8", "replace").strip()
        stdout_text = proc.stdout.decode("utf-8", "replace").rstrip()
    except OSError:
        pass
    # 对齐 TS 版：signal 或不在 allowedCodes 内都视为失败；spawn 失败 exit 显示为 null
    if code is None or code < 0 or code not in allowed_codes:
        display = "null" if code is None or code < 0 else str(code)
        raise RuntimeError(
            "git {} 失败：{}（exit {}）".format(" ".join(args), stderr_text, display)
        )
    return {"code": code, "text": stdout_text}


RECEIPT = object_schema({
    "status": {"enum": ["DONE", "NEEDS_CONTEXT", "BLOCKED"]},
    "report_path": TEXT,
    "report_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
})
EXPECTED_PLAN = object_schema({
    "mode": {"enum": ["TDD", "direct_verification"]},
    "approved_seams": SEAMS,
})


def executor_schema(review_schema: Dict[str, Any]) -> Dict[str, Any]:
    """派发与本地校验共用同一 schema；review 定义由本脚本提供。"""
    pair = object_schema({"standards": review_schema, "spec": review_schema})
    review = object_schema({
        "attempts": {"type": "integer", "enum": list(range(1, workflow_policy.MAX_STAGES + 1))},
        "gate": {"enum": ["PASS", "BLOCKED"]},
        "initial": pair,
        "final": pair,
        "rounds": {"type": "array", "items": pair, "minItems": 1, "maxItems": workflow_policy.MAX_STAGES},
        "sources": {"type": "array", "items": object_schema({"path": TEXT, "sha256": TEXT}), "minItems": 1, "maxItems": workflow_policy.MAX_STAGES},
    }, optional=("initial", "rounds", "sources"))
    review["oneOf"] = [
        {"properties": {"attempts": {"const": 1}}, "not": {"required": ["initial"]}},
        {"properties": {"attempts": {"enum": list(range(2, workflow_policy.MAX_STAGES + 1))}}, "required": ["initial"]},
    ]
    plan = object_schema({
        **EXPECTED_PLAN["properties"],
        "decision_source": TEXT,
        "red_evidence": {"anyOf": [TEXT, {"type": "null"}]},
    })
    plan["allOf"] = [{
        "if": {"properties": {"mode": {"const": "direct_verification"}}},
        "then": {"properties": {"red_evidence": {"type": "null"}}},
    }]
    schema = object_schema({
        "execution": object_schema({
            "root": object_schema({"path": TEXT, "sha256": TEXT}),
            "stage_dispatch": object_schema({"path": TEXT, "sha256": TEXT}),
            "previous_stages": {"type": "array", "items": {"type": "object"}},
            "implementers": {"type": "array", "items": {"type": "object"}},
            "stopped_tasks": {"type": "boolean"},
        }),
        "delivery_kind": {"enum": ["changed", "already_satisfied", None]},
        "status": {"enum": ["DONE", "NEEDS_CONTEXT", "BLOCKED"]},
        "stage": {"type": "integer", "enum": list(range(workflow_policy.MAX_STAGES))},
        "outcome": {"enum": ["passed", "code_failure", "interrupted", "blocked"]},
        "base_commit": {"anyOf": [SHA, {"type": "null"}]},
        "head_commit": {"anyOf": [SHA, {"type": "null"}]},
        "implementation_commits": {
            "type": "array", "items": object_schema({"sha": SHA, "subject": TEXT}),
        },
        "test_plan": {"anyOf": [plan, {"type": "null"}]},
        "acceptance": {
            "type": "array", "items": object_schema({"criterion": TEXT, "evidence": TEXT}),
        },
        "verification": {
            "type": "array", "items": object_schema({"command": TEXT, "result": TEXT}),
        },
        "review": {"anyOf": [review, {"type": "null"}]},
        "requested_context": TEXTS,
        "blockers": TEXTS,
        "concerns": TEXTS,
    }, optional=("stage", "outcome", "delivery_kind", "execution"))
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    schema["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "DONE"}}},
            "then": {"properties": {
                "base_commit": SHA, "head_commit": SHA,
                "implementation_commits": {"minItems": 0},
                "acceptance": {"minItems": 1}, "verification": {"minItems": 1},
                "blockers": {"maxItems": 0}, "requested_context": {"maxItems": 0},
                "review": {"type": "object", "properties": {"gate": {"const": "PASS"}}},
                "test_plan": {
                    "type": "object",
                    "if": {"properties": {"mode": {"const": "TDD"}}},
                    "then": {"properties": {
                        "approved_seams": {"minItems": 1}, "red_evidence": TEXT,
                    }},
                },
            }},
        },
        {
            "if": {"properties": {"status": {"const": "NEEDS_CONTEXT"}}},
            "then": {"properties": {"requested_context": {"minItems": 1}}},
        },
        {
            "if": {"properties": {"status": {"const": "BLOCKED"}}},
            "then": {"properties": {"blockers": {"minItems": 1}}},
        },
    ]
    schema["allOf"].append({
        "if": {"properties": {"status": {"const": "DONE"}}},
        "then": {
            "if": {"required": ["delivery_kind"], "properties": {"delivery_kind": {"const": "already_satisfied"}}},
            "then": {"properties": {"implementation_commits": {"maxItems": 0}}},
            "else": {"properties": {"implementation_commits": {"minItems": 1}}},
        },
    })
    return schema


def review_pairs(review):
    if review is None:
        return []
    return review.get("rounds", ([review["initial"]] if "initial" in review else []) + [review["final"]])


def existing_behavior_round(report: Dict[str, Any], index: int) -> bool:
    """资格属于原始轮次，不随最终状态或后续 TDD 交付改变。"""
    try:
        pair = review_pairs(report["review"])[index]
        collection = evidence.read(evidence.bound(report["review"]["sources"][index]))
        record = evidence.read(evidence.bound(collection["round"]))
        dispatch = evidence.read(evidence.bound(record["dispatch"]))
        acceptance = evidence.read(evidence.bound(record["acceptance_evidence"]))
        base = report["base_commit"]
        # 完整 collection/轴身份仍由 ticket_reports 重验；这里不重复派生审查结果。
        return (
            record["review_kind"] == "existing_behavior"
            and record["reviewed_base"] == record["reviewed_head"] == base
            and all(axis["reviewed_base"] == axis["reviewed_head"] == base for axis in pair.values())
            and collection["pair"] == pair
            and dispatch["role"] == "executor"
            and dispatch.get("workflow_contract_version") == workflow_contract.VERSION
            and dispatch["base_commit"] == base
            and dispatch["test_mode"] == "direct_verification"
            and isinstance(acceptance, list) and bool(acceptance)
        )
    except (KeyError, IndexError, TypeError, AttributeError, ValueError, OSError):
        return False


def report_errors(report: Any, schema: Dict[str, Any]) -> List[Dict[str, Any]]:
    problems = schema_errors(report, schema)
    if problems:
        return [{"check": "report_schema", "observed": problems}]
    failures: List[Dict[str, Any]] = []
    identities = [report["base_commit"], report["head_commit"]]
    identities.extend(item["sha"] for item in report["implementation_commits"])
    if report["review"] is not None:
        for pair in review_pairs(report["review"]):
            for axis in pair.values():
                identities.extend((axis["reviewed_base"], axis["reviewed_head"]))
    if any(value is not None and FULL_SHA.fullmatch(value) is None for value in identities):
        failures.append({"check": "full_commit_identity"})
    commits = [item["sha"] for item in report["implementation_commits"]]
    if report["status"] == "DONE":
        no_change = report.get("delivery_kind") == "already_satisfied"
        if no_change:
            if commits or report["base_commit"] != report["head_commit"] or report["test_plan"]["mode"] != "direct_verification":
                failures.append({"check": "already_satisfied_identity"})
        elif not commits or report.get("delivery_kind", "changed") != "changed":
            failures.append({"check": "done_has_commits"})
    if len(commits) != len(set(commits)):
        failures.append({"check": "report_commits_unique"})
    if ("stage" in report) != ("outcome" in report):
        failures.append({"check": "stage_outcome_required_together"})
    if "stage" in report:
        if (report["outcome"] == "passed") != (report["status"] == "DONE"):
            failures.append({"check": "stage_outcome_status"})
        if report["outcome"] == "code_failure" and report["status"] != "BLOCKED":
            failures.append({"check": "code_failure_status"})
        if report["review"] is not None and ("rounds" not in report["review"] or
                report["review"]["attempts"] > report["stage"] + 1):
            failures.append({"check": "stage_review_rounds"})
    review = report["review"]
    if review is not None:
        if report["base_commit"] is None or report["head_commit"] is None:
            failures.append({"check": "review_requires_commit_identity"})
        pairs = review_pairs(review)
        if len(pairs) != review["attempts"] or pairs[-1] != review["final"] or (
            len(pairs) > 1 and pairs[0] != review["initial"]
        ):
            failures.append({"check": "review_rounds_complete"})
        if ("rounds" in review) != ("sources" in review) or (
            "sources" in review and (len(review["sources"]) != len(pairs)
                or len({item["path"] for item in review["sources"]}) != len(pairs))
        ):
            failures.append({"check": "review_sources_complete"})
        if any(not any(f["blocking"] for axis in pair.values() for f in axis["findings"])
               for pair in pairs[:-1]):
            failures.append({"check": "review_after_pass"})
        seen = {}
        for index, pair in enumerate(pairs):
            head = pair["standards"]["reviewed_head"]
            if head in seen and not (existing_behavior_round(report, seen[head])
                                     and existing_behavior_round(report, index)):
                failures.append({"check": "review_requires_new_head"})
                break
            seen[head] = index
        for index, pair in enumerate(pairs):
            name = str(index + 1)
            for axis, result in pair.items():
                if result["axis"] != axis or any(f["axis"] != axis for f in result["findings"]):
                    failures.append({"check": "review_axis", "observed": name + "." + axis})
                if result["reviewed_base"] != report["base_commit"]:
                    failures.append({"check": "review_base", "observed": name + "." + axis})
            if pair["standards"]["reviewed_head"] != pair["spec"]["reviewed_head"]:
                failures.append({"check": "review_heads_agree", "observed": name})
        final = review["final"]
        blocking = any(f["blocking"] for result in final.values() for f in result["findings"])
        expected_gate = "BLOCKED" if blocking else "PASS"
        if review["gate"] != expected_gate:
            failures.append({"check": "review_gate", "expected": expected_gate})
        if report["status"] == "DONE" and any(
            result["reviewed_head"] != report["head_commit"] for result in final.values()
        ):
            failures.append({"check": "review_head_matches_reported"})
    return failures


def validate_report(
    report: Dict[str, Any], status: str, reported_head: str, base: str,
    expected_plan: Dict[str, Any], cwd: str | None = None,
) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    if report["status"] != status:
        failures.append({"check": "status_matches"})
    if report["base_commit"] is not None and report["base_commit"] != base:
        failures.append({"check": "base_matches_reported"})
    if report["head_commit"] is not None and report["head_commit"] != reported_head:
        failures.append({"check": "head_matches_argument"})
    plan = report["test_plan"]
    if plan is not None and (
        plan["mode"] != expected_plan["mode"]
        or set(plan["approved_seams"]) != set(expected_plan["approved_seams"])
    ):
        failures.append({"check": "test_plan_matches_preflight"})
    commit_range = set(git(["rev-list", "{}..{}".format(base, reported_head)], cwd=cwd)["text"].splitlines())
    reported_commits = {item["sha"] for item in report["implementation_commits"]}
    if reported_commits != commit_range:
        failures.append({
            "check": "report_commits_match_range",
            "missing": sorted(commit_range - reported_commits),
            "unexpected": sorted(reported_commits - commit_range),
        })
    review = report["review"]
    if review is not None:
        previous = base
        for index, pair in enumerate(review_pairs(review)):
            name = str(index + 1)
            reviewed = pair["standards"]["reviewed_head"]
            base_review = reviewed == base and (
                existing_behavior_round(report, index)
                or (index == 0 and "delivery_kind" in report)
            )
            if (reviewed not in commit_range and not base_review) or git(["merge-base", "--is-ancestor", previous, reviewed], (0, 1), cwd=cwd)["code"]:
                failures.append({"check": "review_commit_range", "observed": name})
                continue
            previous = reviewed
    return failures


def check_delivery(cwd: str, branch: str, base: str, reported_head: str, status: str,
                   report_file: str, plan_file: str) -> Dict[str, Any]:
    """执行完整 executor Git 验收并返回结果，不启动 verifier 子进程。"""
    if not branch or not FULL_SHA.fullmatch(base) or not FULL_SHA.fullmatch(reported_head) or status not in (
        "DONE", "NEEDS_CONTEXT", "BLOCKED"
    ):
        raise ValueError("branch、完整 SHA 或 status 无效")
    schema = executor_schema(axis_report_schema())
    check_schema(schema)
    expected_plan, _ = read_json(plan_file)
    if schema_errors(expected_plan, EXPECTED_PLAN) or (
        expected_plan["mode"] == "TDD" and not expected_plan["approved_seams"]
    ):
        raise ValueError("preflight test plan 无效")
    report, report_hash = read_json(report_file)
    failures: List[Dict[str, Any]] = []
    actual_branch = git(["symbolic-ref", "--quiet", "--short", "HEAD"], (0, 1), cwd=cwd)
    if actual_branch["code"] == 1 or actual_branch["text"] != branch:
        failures.append({"check": "branch", "expected": branch,
                         "observed": None if actual_branch["code"] == 1 else actual_branch["text"]})
    head = git(["rev-parse", "HEAD"], cwd=cwd)["text"]
    if head != reported_head:
        failures.append({"check": "head_matches_reported", "expected": reported_head, "observed": head})
    if git(["cat-file", "-t", base], cwd=cwd)["text"] != "commit":
        raise RuntimeError("BASE 必须指向 commit")
    if git(["merge-base", "--is-ancestor", base, head], (0, 1), cwd=cwd)["code"] == 1:
        failures.append({"check": "base_is_ancestor"})
    beads_commit = git(["log", "--full-history", "-m", "-1", "--format=%H",
                        f"{base}..{head}", "--", ".beads"], cwd=cwd)["text"]
    if beads_commit:
        failures.append({"check": "no_beads_commits", "observed": beads_commit})
    beads_changes = git(["status", "--porcelain=v1", "--untracked-files=no", "--", ".beads"], cwd=cwd)["text"]
    if beads_changes:
        failures.append({"check": "no_beads_working_tree_changes", "observed": beads_changes})
    if status == "DONE":
        if base == head and report.get("delivery_kind") != "already_satisfied":
            failures.append({"check": "done_has_commits"})
        changes = git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=cwd)["text"]
        if changes:
            failures.append({"check": "done_clean_tree", "observed": changes})
    report_failures = report_errors(report, schema)
    failures.extend(report_failures)
    if not report_failures:
        failures.extend(validate_report(report, status, reported_head, base, expected_plan, cwd=cwd))
    return {"ok": not failures, "report_sha256": report_hash,
            **({"failures": failures} if failures else {})}


def emit_result(failures: List[Dict[str, Any]], report_hash: str) -> None:
    print(json.dumps(
        {"ok": not failures, "report_sha256": report_hash, **({"failures": failures} if failures else {})},
        ensure_ascii=False, separators=(",", ":"),
    ))


def main(argv: List[str]) -> None:
    emit_receipt = "--emit-receipt" in argv
    if emit_receipt:
        argv = list(argv)
        argv.remove("--emit-receipt")
        if not argv or argv[0] != "--check-report":
            raise ValueError("--emit-receipt 仅用于报告自检")
    if argv == ["--receipt-schema"]:
        print(json.dumps(RECEIPT, ensure_ascii=False, separators=(",", ":")))
        return
    if argv == ["--schema"]:
        axis_schema = axis_report_schema()
        schema = executor_schema(axis_schema)
        check_schema(schema)
        print(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
        return
    if len(argv) in (2, 3) and argv[0] == "--check-report":
        axis_schema = axis_report_schema()
        schema = executor_schema(axis_schema)
        check_schema(schema)
        report, report_hash = read_json(argv[1])
        failures = report_errors(report, schema)
        if len(argv) == 3:
            receipt, _ = read_json(argv[2])
            problems = schema_errors(receipt, RECEIPT)
            if problems:
                failures.append({"check": "receipt_schema", "observed": problems})
            else:
                expected = {
                    "status": report.get("status") if isinstance(report, dict) else None,
                    "report_path": os.path.abspath(argv[1]),
                    "report_sha256": report_hash,
                }
                for field, value in expected.items():
                    if receipt[field] != value:
                        failures.append({"check": "receipt_" + field + "_matches"})
        if emit_receipt:
            if len(argv) != 2 or failures:
                raise ValueError(json.dumps(failures or ["receipt 自检不接受已有 receipt"], ensure_ascii=False))
            print(json.dumps({"status": report["status"], "report_path": os.path.abspath(argv[1]), "report_sha256": report_hash}))
            return
        emit_result(failures, report_hash)
        return
    if len(argv) != 6:
        raise ValueError("用法：verify-ticket.py <branch> <BASE> <HEAD> <status> "
                         "<executor-report.json> <expected-plan.json>")
    branch, base, reported_head, status, report_file, plan_file = argv
    result = check_delivery(os.getcwd(), branch, base, reported_head, status, report_file, plan_file)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    _use_utf8()
    try:
        main(sys.argv[1:])
    except Exception as error:  # noqa: BLE001 - 对齐 TS 版顶层 catch 行为
        _use_utf8()
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        sys.exit(1)

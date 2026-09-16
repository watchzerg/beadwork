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

import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

FULL_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _use_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]


def git(args: List[str], allowed_codes: Tuple[int, ...] = (0,)) -> Dict[str, Any]:
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    code: Optional[int] = None
    stderr_text = ""
    stdout_text = ""
    try:
        proc = subprocess.run(
            ["git", *args], cwd=os.getcwd(), env=env, capture_output=True
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


def object_schema(properties: Dict[str, Any], optional: Tuple[str, ...] = ()) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": [key for key in properties if key not in optional],
        "additionalProperties": False,
    }


TEXT = {"type": "string", "pattern": r"\S"}
SHA = {"type": "string", "pattern": r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"}
TEXTS = {"type": "array", "items": TEXT}
SEAMS = {**TEXTS, "uniqueItems": True}
RECEIPT = object_schema({
    "status": {"enum": ["DONE", "NEEDS_CONTEXT", "BLOCKED"]},
    "report_path": TEXT,
    "report_sha256": {"type": "string", "pattern": r"^[0-9a-f]{64}$"},
})
EXPECTED_PLAN = object_schema({
    "mode": {"enum": ["TDD", "direct_verification"]},
    "approved_seams": SEAMS,
})


def axis_report_schema() -> Dict[str, Any]:
    """本流程的单轴报告结构；审查语义见 agents/reviewer.md 与 references/review.md。"""
    finding = object_schema({
        "axis": {"enum": ["standards", "spec"]},
        "kind": {"enum": ["defect", "documented_standard", "smell"]},
        "blocking": {"type": "boolean"},
        "title": TEXT,
        "evidence": TEXT,
    })
    finding["allOf"] = [
        {"if": {"properties": {"kind": {"const": "defect"}}},
         "then": {"properties": {"blocking": {"const": True}}}},
        {"if": {"properties": {"kind": {"const": "documented_standard"}}},
         "then": {"properties": {"axis": {"const": "standards"}, "blocking": {"const": True}}}},
        {"if": {"properties": {"kind": {"const": "smell"}}},
         "then": {"properties": {"blocking": {"const": False}}}},
    ]
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "AxisReport",
        **object_schema({
            "reviewed_base": SHA,
            "reviewed_head": SHA,
            "axis": {"enum": ["standards", "spec"]},
            "findings": {"type": "array", "items": finding},
            "notes": TEXTS,
        }),
    }


def executor_schema(review_schema: Dict[str, Any]) -> Dict[str, Any]:
    """派发与本地校验共用同一 schema；review 定义由本脚本提供。"""
    pair = object_schema({"standards": review_schema, "spec": review_schema})
    review = object_schema({
        "attempts": {"type": "integer", "enum": [1, 2, 3, 4]},
        "gate": {"enum": ["PASS", "BLOCKED"]},
        "initial": pair,
        "final": pair,
        "rounds": {"type": "array", "items": pair, "minItems": 1, "maxItems": 4},
        "sources": {"type": "array", "items": object_schema({"path": TEXT, "sha256": TEXT}), "minItems": 1, "maxItems": 4},
    }, optional=("initial", "rounds", "sources"))
    review["oneOf"] = [
        {"properties": {"attempts": {"const": 1}}, "not": {"required": ["initial"]}},
        {"properties": {"attempts": {"enum": [2, 3, 4]}}, "required": ["initial"]},
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
        "stage": {"type": "integer", "enum": [0, 1, 2, 3]},
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


def schema_errors(value: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """仅实现这两份受控 schema 使用的 Draft 7 子集；未知规则拒绝加载。"""
    errors: List[str] = []
    kind = schema.get("type")
    matches = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, (int, float)) and not isinstance(value, bool)
        and (isinstance(value, int) or value.is_integer()),
        "null": value is None,
    }
    if kind is not None and not matches[kind]:
        return [path + ": expected " + kind]
    if "enum" in schema and not any(
        isinstance(value, bool) == isinstance(item, bool) and value == item for item in schema["enum"]
    ):
        errors.append(path + ": enum")
    if "const" in schema and (
        isinstance(value, bool) != isinstance(schema["const"], bool) or value != schema["const"]
    ):
        errors.append(path + ": const")
    if isinstance(value, dict):
        errors.extend(path + "." + key + ": required" for key in schema.get("required", []) if key not in value)
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                errors.extend(schema_errors(item, properties[key], path + "." + key))
            elif schema.get("additionalProperties") is False:
                errors.append(path + "." + key + ": unexpected")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            errors.append(path + ": item count")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(path + ": duplicate items")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(schema_errors(item, schema["items"], "{}[{}]".format(path, index)))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(path + ": minLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(path + ": pattern")
    for name in ("anyOf", "oneOf"):
        if name in schema:
            matching = sum(not schema_errors(value, item, path) for item in schema[name])
            if matching == 0 or (name == "oneOf" and matching != 1):
                errors.append(path + ": " + name)
    for item in schema.get("allOf", []):
        errors.extend(schema_errors(value, item, path))
    if "not" in schema and not schema_errors(value, schema["not"], path):
        errors.append(path + ": not")
    if "if" in schema:
        branch = "else" if schema_errors(value, schema["if"], path) else "then"
        if branch in schema:
            errors.extend(schema_errors(value, schema[branch], path))
    return errors


def check_schema(schema: Any) -> None:
    allowed = {
        "$schema", "title", "description", "type", "properties", "required",
        "additionalProperties", "items", "minItems", "maxItems", "uniqueItems",
        "minLength", "pattern", "enum", "const", "anyOf", "oneOf", "allOf", "not",
        "if", "then", "else",
    }
    if not isinstance(schema, dict) or set(schema) - allowed:
        raise ValueError("schema 含不支持的规则")
    if "type" in schema and schema["type"] not in ("object", "array", "string", "boolean", "integer", "null"):
        raise ValueError("schema 含不支持的 type")
    for child in schema.get("properties", {}).values():
        check_schema(child)
    for key in ("items", "not", "if", "then", "else"):
        if key in schema:
            check_schema(schema[key])
    for key in ("anyOf", "oneOf", "allOf"):
        for child in schema.get(key, []):
            check_schema(child)


def unique_object(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 含重复字段：" + key)
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError("JSON 含非法常量：" + value)


def read_json(path: str) -> Tuple[Any, str]:
    with open(path, "rb") as handle:
        raw = handle.read()
    return (
        json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant),
        hashlib.sha256(raw).hexdigest(),
    )


def review_pairs(review):
    if review is None:
        return []
    return review.get("rounds", ([review["initial"]] if "initial" in review else []) + [review["final"]])


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
        if len({pair["standards"]["reviewed_head"] for pair in pairs}) != len(pairs):
            failures.append({"check": "review_requires_new_head"})
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
    report: Dict[str, Any], status: str, reported_head: str, base: str, expected_plan: Dict[str, Any]
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
    commit_range = set(git(["rev-list", "{}..{}".format(base, reported_head)])["text"].splitlines())
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
            if (reviewed not in commit_range and not (index == 0 and reviewed == base and "delivery_kind" in report)) or git(["merge-base", "--is-ancestor", previous, reviewed], (0, 1))["code"]:
                failures.append({"check": "review_commit_range", "observed": name})
                continue
            previous = reviewed
    return failures


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
    if not branch or not FULL_SHA.fullmatch(base) or not FULL_SHA.fullmatch(reported_head) or status not in (
        "DONE", "NEEDS_CONTEXT", "BLOCKED"
    ):
        raise ValueError("branch、完整 SHA 或 status 无效")
    axis_schema = axis_report_schema()
    schema = executor_schema(axis_schema)
    check_schema(schema)
    expected_plan, _ = read_json(plan_file)
    if schema_errors(expected_plan, EXPECTED_PLAN) or (
        expected_plan["mode"] == "TDD" and not expected_plan["approved_seams"]
    ):
        raise ValueError("preflight test plan 无效")
    report, report_hash = read_json(report_file)
    failures: List[Dict[str, Any]] = []
    actual_branch = git(["symbolic-ref", "--quiet", "--short", "HEAD"], (0, 1))
    if actual_branch["code"] == 1 or actual_branch["text"] != branch:
        failures.append(
            {
                "check": "branch",
                "expected": branch,
                "observed": None
                if actual_branch["code"] == 1
                else actual_branch["text"],
            }
        )
    head = git(["rev-parse", "HEAD"])["text"]
    if head != reported_head:
        failures.append(
            {
                "check": "head_matches_reported",
                "expected": reported_head,
                "observed": head,
            }
        )
    if git(["cat-file", "-t", base])["text"] != "commit":
        raise RuntimeError("BASE 必须指向 commit")
    ancestor = git(["merge-base", "--is-ancestor", base, head], (0, 1))
    if ancestor["code"] == 1:
        failures.append({"check": "base_is_ancestor"})
    # full-history + merge diffs 避免仅在 merge commit 引入的 .beads 改动被路径简化隐藏。
    beads_commit = git(
        [
            "log",
            "--full-history",
            "-m",
            "-1",
            "--format=%H",
            "{}..{}".format(base, head),
            "--",
            ".beads",
        ]
    )["text"]
    if beads_commit:
        failures.append({"check": "no_beads_commits", "observed": beads_commit})
    beads_changes = git(
        ["status", "--porcelain=v1", "--untracked-files=no", "--", ".beads"]
    )["text"]
    if beads_changes:
        failures.append(
            {"check": "no_beads_working_tree_changes", "observed": beads_changes}
        )
    if status == "DONE":
        if base == head and report.get("delivery_kind") != "already_satisfied":
            failures.append({"check": "done_has_commits"})
        changes = git(["status", "--porcelain=v1", "--untracked-files=all"])["text"]
        if changes:
            failures.append({"check": "done_clean_tree", "observed": changes})
    report_failures = report_errors(report, schema)
    failures.extend(report_failures)
    if not report_failures:
        failures.extend(validate_report(report, status, reported_head, base, expected_plan))
    emit_result(failures, report_hash)


if __name__ == "__main__":
    _use_utf8()
    try:
        main(sys.argv[1:])
    except Exception as error:  # noqa: BLE001 - 对齐 TS 版顶层 catch 行为
        _use_utf8()
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        sys.exit(1)

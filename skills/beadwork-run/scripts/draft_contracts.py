"""模型语义草稿的单一输入契约；输出报告由各组装器生成。"""

from pathlib import Path

import evidence
import role_instructions
from schema_validation import SHA, TEXT, TEXTS, object_schema, schema_errors


def nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


def rows(fields):
    return {"type": "array", "items": object_schema(fields)}


def plan_schema():
    return object_schema(
        {
            "mode": {"enum": ["TDD", "direct_verification"]},
            "approved_seams": {**TEXTS, "uniqueItems": True},
            **{
                key: nullable(TEXT)
                for key in ("observable_behavior", "expected_red", "reason", "verification")
            },
        }
    )


def schema(role):
    notes = {"type": "object", "additionalProperties": TEXT}
    outcome = {"enum": ["passed", "code_failure", "blocked", "interrupted"]}
    verification = rows({"command": TEXT, "result": TEXT})
    final_verification = rows(
        {
            "gate": TEXT,
            "command": TEXT,
            "result": TEXT,
            "log_path": TEXT,
            "head_commit": nullable(SHA),
            "passed": {"type": "boolean"},
        }
    )
    if role == "preflight":
        fields = {
            "status": {"enum": ["READY", "BLOCKED"]},
            "plans": {"type": "object", "additionalProperties": nullable(plan_schema())},
            "linked_spec": nullable(TEXT),
            "resume_evidence": TEXTS,
            "sources": TEXTS,
            "suggested_route": {
                "enum": ["new_batch", "resume_tickets", "finalize", "post_merge", None]
            },
            "checks": rows(
                {
                    "name": {"enum": ["spec_and_test_plans", "recovery"]},
                    "passed": {"type": "boolean"},
                    "evidence": TEXT,
                }
            ),
            "blockers": TEXTS,
            "remaining_work": TEXTS,
        }
    elif role in ("implementer", "executor"):
        fields = {
            "status": {"enum": ["DONE", "BLOCKED", "NEEDS_CONTEXT"]},
            "outcome": outcome,
            "test_plan": nullable(
                object_schema({"decision_source": TEXT, "red_evidence": nullable(TEXT)})
            ),
            "acceptance": rows({"criterion": TEXT, "evidence": TEXT}),
            "verification": verification,
            "requested_context": TEXTS,
            "blockers": TEXTS,
            "concerns": TEXTS,
            "stopped_tasks": {"type": "boolean"},
        }
        if role == "implementer":
            fields["verification_notes"] = notes
    elif role == "document-syncer":
        fields = {
            "status": {"enum": ["DONE", "BLOCKED"]},
            "outcome": {"enum": ["passed", "blocked", "interrupted"]},
            "result": {"enum": ["updated", "no_change_needed", "incomplete"]},
            "inspected": rows({"source": TEXT, "assessment": TEXT}),
            "summary": TEXT,
            "verification_notes": notes,
            "stopped_tasks": {"type": "boolean"},
            "blockers": TEXTS,
            "remaining_work": TEXTS,
        }
    elif role in ("fixer", "finalizer"):
        fields = {
            "status": {
                "enum": ["DONE", "BLOCKED"] if role == "fixer" else ["READY_TO_MERGE", "BLOCKED"]
            },
            "outcome": outcome,
            "verification_notes": notes,
            "stopped_tasks": {"type": "boolean"},
            "blockers": TEXTS,
            "remaining_work": TEXTS,
        }
        if role == "fixer":
            fields.update(
                dispositions=rows({"source": TEXT, "action": TEXT}), uncommitted_files=TEXTS
            )
        else:
            fields.update(sources=TEXTS, verification=final_verification)
    else:
        raise ValueError("未知 draft 角色：" + role)
    return object_schema(fields)


def publish(dispatch, role):
    role_instructions.publish(dispatch, role)
    path = Path(dispatch["dispatch_path"]).parent / "draft-schema.json"
    evidence.write(path, schema(role))
    dispatch["draft_schema_path"] = str(path)


def read(dispatch, path, role):
    expected = schema(role)
    if evidence.read(evidence.absolute(dispatch["draft_schema_path"])) != expected:
        raise ValueError("draft schema 与当前角色契约不符")
    value = evidence.read(path)
    errors = schema_errors(value, expected)
    if errors:
        raise ValueError("draft 输入不符：" + "; ".join(errors))
    return value

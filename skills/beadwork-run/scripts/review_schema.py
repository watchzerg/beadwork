"""双轴 review 报告的共用 schema。"""

from typing import Any

from schema_validation import SHA, TEXT, TEXTS, object_schema


def axis_report_schema() -> dict[str, Any]:
    finding = object_schema(
        {
            "axis": {"enum": ["standards", "spec"]},
            "kind": {"enum": ["defect", "documented_standard", "smell"]},
            "blocking": {"type": "boolean"},
            "title": TEXT,
            "evidence": TEXT,
        }
    )
    finding["allOf"] = [
        {
            "if": {"properties": {"kind": {"const": "defect"}}},
            "then": {"properties": {"blocking": {"const": True}}},
        },
        {
            "if": {"properties": {"kind": {"const": "documented_standard"}}},
            "then": {"properties": {"axis": {"const": "standards"}, "blocking": {"const": True}}},
        },
        {
            "if": {"properties": {"kind": {"const": "smell"}}},
            "then": {"properties": {"blocking": {"const": False}}},
        },
    ]
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "AxisReport",
        **object_schema(
            {
                "reviewed_base": SHA,
                "reviewed_head": SHA,
                "axis": {"enum": ["standards", "spec"]},
                "findings": {"type": "array", "items": finding},
                "notes": TEXTS,
            }
        ),
    }

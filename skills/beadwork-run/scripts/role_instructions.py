"""按当前角色与有效测试模式生成正常路径读取清单。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINTS = {
    "preflight": "preflight",
    "executor": "ticket-executor",
    "implementer": "implementer",
    "finalizer": "finalizer",
    "fixer": "fixer",
    "document-syncer": "document-syncer",
    "reviewer": "reviewer",
}


def relative_reads(role, mode=None, scope=None, axis=None, ticket_scope=None):
    reads = [f"agents/{ENTRYPOINTS[role]}.md", "references/report-delivery.md"]
    references = {
        "preflight": ["testing-plan", "testing-seams", "testing-gates"],
        "executor": ["ticket-execution", "testing-plan", "testing-gates"],
        "implementer": ["writer-delivery", "executor-operations", "testing-plan", "testing-gates"],
        "finalizer": ["final-execution", "documentation-sync", "testing-gates"],
        "fixer": ["writer-delivery", "documentation-sync", "testing-gates"],
        "document-syncer": ["writer-delivery", "documentation-sync"],
        "reviewer": ["testing-gates"],
    }[role]
    if role == "executor" and ticket_scope == "root":
        references = ["ticket-execution"]
    elif role in ("executor", "implementer") and mode == "TDD":
        references += ["testing-seams", "testing-tdd"]
    if role == "reviewer":
        if scope == "batch" or mode == "TDD":
            references += ["testing-plan", "testing-seams", "testing-tdd"]
        elif axis == "spec":
            references += ["testing-plan"]
        if scope == "batch":
            references += ["documentation-sync"]
    reads += [f"references/{name}.md" for name in references]
    return reads


def publish(dispatch, role=None):
    role = role or dispatch["role"]
    dispatch["required_reads"] = [
        str(ROOT / name)
        for name in relative_reads(
            role,
            dispatch.get("test_mode"),
            dispatch.get("scope"),
            dispatch.get("axis"),
            dispatch.get("ticket_scope"),
        )
    ]

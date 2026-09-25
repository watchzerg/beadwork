"""角色读取策略只选择当前任务需要的材料。"""

from pathlib import Path

import pytest

import role_instructions

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("role", ["executor", "implementer"])
def test_effective_plan_changes_required_reads(role):
    dispatch = {"role": role, "test_mode": "TDD", "ticket_scope": "stage"}
    role_instructions.publish(dispatch)
    assert any(path.endswith("testing-tdd.md") for path in dispatch["required_reads"])
    dispatch["test_mode"] = "direct_verification"
    role_instructions.publish(dispatch)
    assert not any(path.endswith("testing-tdd.md") for path in dispatch["required_reads"])
    assert not any("recovery-" in path for path in dispatch["required_reads"])


def test_review_axis_and_batch_scope_select_testing_contract():
    standards = role_instructions.relative_reads(
        "reviewer", "direct_verification", "ticket", "standards"
    )
    spec = role_instructions.relative_reads("reviewer", "direct_verification", "ticket", "spec")
    batch = role_instructions.relative_reads("reviewer", scope="batch", axis="standards")
    assert "references/testing-plan.md" not in standards
    assert "references/testing-plan.md" in spec
    assert "references/testing-tdd.md" in batch
    assert "references/documentation-sync.md" in batch


def test_writer_reads_delivery_instead_of_coordinator_protocol():
    for role in ("implementer", "fixer", "document-syncer"):
        paths = role_instructions.relative_reads(role)
        assert "references/writer-delivery.md" in paths
        assert "references/ticket-execution.md" not in paths
        assert "references/final-execution.md" not in paths


@pytest.mark.parametrize("mode", ["TDD", "direct_verification"])
def test_executor_root_reads_only_coordination_contract(mode):
    dispatch = {"role": "executor", "test_mode": mode, "ticket_scope": "root"}
    role_instructions.publish(dispatch)
    assert [Path(path).name for path in dispatch["required_reads"]] == [
        "ticket-executor.md",
        "report-delivery.md",
        "ticket-execution.md",
    ]

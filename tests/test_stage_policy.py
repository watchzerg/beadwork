import pytest

import stage_policy
import workflow_policy


def inputs():
    limit = len(workflow_policy.STAGE_MODELS) - 1
    previous = {"stage": limit}
    report = {"outcome": "code_failure", "execution": {"stopped_tasks": True}}
    facts = {"additional_stages": 2, "extension_reason": "用户明确授权继续"}
    return previous, report, facts, limit


def test_authorize_extension_returns_normalized_record():
    previous, report, facts, limit = inputs()
    new_limit, record = stage_policy.authorize_extension(
        previous, {"path": "/evidence/report.json", "sha256": "a" * 64}, report, facts, limit)
    assert new_limit == limit + 2
    assert record["new_stage_limit"] == new_limit
    assert record["reason"] == "用户明确授权继续"


@pytest.mark.parametrize("mutation", [
    lambda p, r, f, limit: p.update(stage=limit - 1),
    lambda p, r, f, limit: r.update(outcome="blocked"),
    lambda p, r, f, limit: r["execution"].update(stopped_tasks=False),
    lambda p, r, f, limit: f.update(additional_stages=0),
    lambda p, r, f, limit: f.update(additional_stages=workflow_policy.MAX_STAGE_EXTENSION + 1),
    lambda p, r, f, limit: f.update(extension_reason="  "),
    lambda p, r, f, limit: f.update(recovery_reason="不允许混用"),
])
def test_authorize_extension_rejects_invalid_facts(mutation):
    previous, report, facts, limit = inputs()
    mutation(previous, report, facts, limit)
    with pytest.raises(ValueError):
        stage_policy.authorize_extension(previous, {"path": "x", "sha256": "a" * 64}, report, facts, limit)


def test_authorize_extension_is_one_time_only():
    previous, report, facts, limit = inputs()
    previous["stage_extension"] = {"path": "old", "sha256": "b" * 64}
    with pytest.raises(ValueError, match="仅允许追加一次"):
        stage_policy.authorize_extension(previous, {"path": "x", "sha256": "a" * 64}, report, facts, limit)

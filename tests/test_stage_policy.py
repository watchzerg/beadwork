import pytest

import stage_policy
import ticket_execution
import workflow_policy

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("complex_ticket,effort", [(False, "medium"), (True, "high")])
def test_coordinator_and_complex_role_floors(complex_ticket, effort):
    root = {"base_commit": "a" * 40, "complex_ticket": complex_ticket}
    ticket_execution.root_fields(root)
    assert root["coordinator_model"] == {"model": "gpt-6-sol", "reasoning_effort": effort}
    if complex_ticket:
        for stage in range(6):
            models = stage_policy.ticket_models(stage, True, None, {})
            assert models["implementer"] == workflow_policy.MODEL_LEVELS[1 if stage < 4 else 2]
            assert models["standards"] == models["spec"] == workflow_policy.MODEL_LEVELS[2]


def test_extension_override_uses_previous_floor_and_inherits_selection():
    previous = {
        role: workflow_policy.MODEL_LEVELS[2] for role in ("implementer", "standards", "spec")
    }
    facts = {
        "continuation": "extend",
        "model_overrides": {
            "implementer": workflow_policy.EXTENSION_MODEL_LEVELS[4],
            "standards": workflow_policy.MODEL_LEVELS[2],
        },
        "model_override_reason": "用户指定实现者 Astra-high，Standards 保持 Sol-high",
    }
    models = stage_policy.ticket_models(6, False, previous, facts)
    assert models["implementer"] == workflow_policy.EXTENSION_MODEL_LEVELS[4]
    assert models["standards"] == workflow_policy.MODEL_LEVELS[2]
    assert models["spec"] == workflow_policy.EXTENSION_MODEL_LEVELS[3]
    assert stage_policy.ticket_models(7, False, models, {"continuation": "repair"}) == models
    for role, model in (
        ("implementer", workflow_policy.EXTENSION_MODEL_LEVELS[3]),
        ("standards", workflow_policy.MODEL_LEVELS[1]),
    ):
        with pytest.raises(ValueError, match="模型只能升级"):
            stage_policy.ticket_models(
                7,
                False,
                models,
                {
                    "continuation": "repair",
                    "model_overrides": {role: model},
                    "model_override_reason": "不允许降档",
                },
            )


def inputs():
    limit = len(workflow_policy.STAGE_MODELS) - 1
    previous = {"stage": limit}
    report = {"outcome": "code_failure", "execution": {"stopped_tasks": True}}
    facts = {"additional_stages": 2, "extension_reason": "用户明确授权继续"}
    return previous, report, facts, limit


def test_authorize_extension_returns_normalized_record():
    previous, report, facts, limit = inputs()
    new_limit, record = stage_policy.authorize_extension(
        previous, {"path": "/evidence/report.json", "sha256": "a" * 64}, report, facts, limit
    )
    assert new_limit == limit + 2
    assert record["new_stage_limit"] == new_limit
    assert record["reason"] == "用户明确授权继续"


def test_authorize_extension_is_one_time_only():
    previous, report, facts, limit = inputs()
    previous["stage_extension"] = {"path": "old", "sha256": "b" * 64}
    with pytest.raises(ValueError, match="仅允许追加一次"):
        stage_policy.authorize_extension(
            previous, {"path": "x", "sha256": "a" * 64}, report, facts, limit
        )

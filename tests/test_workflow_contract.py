import pytest

import workflow_contract

pytestmark = pytest.mark.unit


def test_stamp_and_require_current():
    value = {"role": "executor"}
    assert workflow_contract.stamp(value) is value
    assert value == {
        "role": "executor",
        "workflow_contract_version": 7,
        "launch_context": {"fork_turns": "none", "required": True},
    }
    assert workflow_contract.require_current(value) is value
    assert workflow_contract.launch_context(value) == {
        "fork_turns": "none",
        "required": True,
    }


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"workflow_contract_version": 1},
        {"workflow_contract_version": 2},
        {"workflow_contract_version": 3},
        {"workflow_contract_version": 4},
        {"workflow_contract_version": 5},
        {"workflow_contract_version": 6},
        {"workflow_contract_version": 8},
    ],
)
def test_require_current_rejects_missing_or_unknown_version(value):
    before = dict(value)
    with pytest.raises(ValueError, match="契约版本"):
        workflow_contract.require_current(value)
    assert value == before


@pytest.mark.parametrize(
    "launch_context",
    [None, {}, {"fork_turns": "all", "required": True}, {"fork_turns": "none"}],
)
def test_require_current_rejects_invalid_launch_context(launch_context):
    value = {"workflow_contract_version": 7}
    if launch_context is not None:
        value["launch_context"] = launch_context
    with pytest.raises(ValueError, match="fork_turns"):
        workflow_contract.require_current(value)

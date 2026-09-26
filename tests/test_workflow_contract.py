import pytest

import workflow_contract

pytestmark = pytest.mark.unit


def test_dispatch_launch_context_has_no_version_stamp():
    value = {"role": "executor"}
    assert workflow_contract.set_launch_context(value) is value
    assert value == {
        "role": "executor",
        "launch_context": {"fork_turns": "none", "required": True},
    }


@pytest.mark.parametrize("context", [None, {"fork_turns": "all", "required": True}])
def test_launch_context_still_requires_independent_agent(context):
    with pytest.raises(ValueError, match="fork_turns"):
        workflow_contract.launch_context({"launch_context": context})

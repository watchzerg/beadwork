import pytest

import workflow_contract

pytestmark = pytest.mark.unit


def test_stamp_and_require_current():
    value = {"role": "executor"}
    assert workflow_contract.stamp(value) is value
    assert value == {"role": "executor", "workflow_contract_version": 2}
    assert workflow_contract.require_current(value) is value


@pytest.mark.parametrize(
    "value", [{}, {"workflow_contract_version": 0}, {"workflow_contract_version": 1}]
)
def test_require_current_rejects_missing_or_unknown_version(value):
    before = dict(value)
    with pytest.raises(ValueError, match="契约版本"):
        workflow_contract.require_current(value)
    assert value == before

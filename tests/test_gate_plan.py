"""gate-plan v2 三字段契约与单票选择规则。"""

import pytest

import gate_plan

pytestmark = pytest.mark.unit


RECIPES = {
    *gate_plan.REQUIRED_RECIPES,
    "gate-artifact",
    "gate-database",
    "gate-browser",
}


def test_parse_and_select_in_full_order():
    plan = gate_plan.parse(
        '{"core":"gate-core","full":["gate-core","gate-artifact","gate-database",'
        '"gate-browser"],"defer_to_final":["gate-browser"]}',
        RECIPES,
    )
    assert gate_plan.required_for_ticket(plan, ["gate-browser", "gate-database"]) == [
        "gate-core",
        "gate-database",
    ]
    assert gate_plan.deferred_for_ticket(plan, ["gate-browser", "gate-database"]) == [
        "gate-browser"
    ]
    assert gate_plan.required_for_ticket(plan, []) == ["gate-core"]


@pytest.mark.parametrize(
    "raw,message",
    [
        ('{"core":"gate-core","full":["gate-core"],"defer_to_final":[{}]}', "唯一的 gate 列表"),
        ('{"core":"gate-core","full":["gate-core"]}', "必须且只能"),
        (
            '{"core":"gate-core","full":["gate-core"],"defer_to_final":[],"extra":1}',
            "必须且只能",
        ),
        (
            '{"core":"gate-core","full":["gate-core","gate-browser"],'
            '"defer_to_final":["gate-browser","gate-browser"]}',
            "唯一的 gate 列表",
        ),
        (
            '{"core":"gate-core","full":["gate-core","gate-browser"],'
            '"defer_to_final":["gate-core"]}',
            "非 core 边界",
        ),
        (
            '{"core":"gate-core","full":["gate-core","gate-browser"],'
            '"defer_to_final":["gate-missing"]}',
            "非 core 边界",
        ),
    ],
)
def test_parse_rejects_non_v2_or_invalid_deferred(raw, message):
    with pytest.raises(ValueError, match=message):
        gate_plan.parse(raw, RECIPES)


def test_select_rejects_unknown_boundary():
    plan = gate_plan.parse(
        '{"core":"gate-core","full":["gate-core","gate-artifact","gate-database",'
        '"gate-browser"],"defer_to_final":[]}',
        RECIPES,
    )
    with pytest.raises(ValueError, match="不属于 gate-plan full"):
        gate_plan.required_for_ticket(plan, ["gate-system"])

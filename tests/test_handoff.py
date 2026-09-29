"""收尾 observation 的输入诊断与证据发布边界。"""

import pytest

import evidence
import handoff
from fixture_support import stop_observation

pytestmark = pytest.mark.integration


@pytest.fixture
def observation_inputs(tmp_path):
    dispatch = tmp_path / "dispatch.json"
    report = tmp_path / "report.json"
    evidence.write(dispatch, {})
    evidence.write(report, {"status": "DONE", "stopped_tasks": True})
    return dispatch, report, stop_observation(report)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("evidence", ["已观察任务退出"], "非空字符串"),
        ("task_id", None, "非空字符串"),
        ("observed_at", 123, "非空字符串"),
        ("evidence", "", "非空字符串"),
        ("task_id", " \t", "非空字符串"),
        ("observed_at", "\n", "非空字符串"),
        ("stopped", "true", "布尔值"),
        ("stopped", 1, "布尔值"),
        ("unresolved", "", "数组"),
    ],
)
def test_close_identifies_invalid_field_without_publishing(
    observation_inputs, field, value, expected
):
    dispatch, report, facts = observation_inputs
    facts[field] = value
    with pytest.raises(ValueError, match=rf"observation\.{field}.*{expected}"):
        handoff.close(dispatch, report, facts)
    assert not list(dispatch.parent.glob("closure-*.json"))


@pytest.mark.parametrize("case", ["missing", "extra", "not_object"])
def test_close_identifies_invalid_shape(observation_inputs, case):
    dispatch, report, facts = observation_inputs
    if case == "missing":
        del facts["evidence"]
        expected = "缺少.*evidence"
    elif case == "extra":
        facts["unexpected"] = True
        expected = "多余.*unexpected"
    else:
        facts = []
        expected = "observation.*JSON object"
    with pytest.raises(ValueError, match=expected):
        handoff.close(dispatch, report, facts)
    assert not list(dispatch.parent.glob("closure-*.json"))


def test_close_preserves_observation_and_binds_sources(observation_inputs):
    dispatch, report, facts = observation_inputs
    source = handoff.close(dispatch, report, facts)["closure_source"]
    record = handoff.check_close(dispatch, report, source)
    assert record == dict(
        facts, dispatch=evidence.binding(dispatch), report=evidence.binding(report)
    )


def test_close_still_rejects_unresolved_stopped_task(observation_inputs):
    dispatch, report, facts = observation_inputs
    facts["unresolved"] = ["命令仍在运行"]
    with pytest.raises(ValueError, match="仍有未结束事项"):
        handoff.close(dispatch, report, facts)
    assert not list(dispatch.parent.glob("closure-*.json"))

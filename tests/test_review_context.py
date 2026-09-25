"""紧凑视图按运行时间选择证据，不依赖随机目录名或来源拼接顺序。"""

import pytest

import review_context

pytestmark = pytest.mark.unit


def test_selection_uses_run_time_instead_of_manifest_order(monkeypatch):
    sources = [
        {"run_path": "verification-a", "started_ns": 30, "passed": True},
        {"run_path": "verification-b", "started_ns": 20, "passed": False},
        {"run_path": "verification-z", "started_ns": 10, "passed": False},
    ]
    monkeypatch.setattr(
        review_context,
        "_record",
        lambda item: dict(
            item,
            command="just --one -- gate-full",
            recipe="gate-full",
            head_commit="head",
            delivery_attempt=0,
            outcome="exited",
        ),
    )
    view = review_context.build(sources, "head", {}, {}, {})
    reasons = {row["run_path"]: row["selected_reasons"] for row in view["entries"]}
    assert reasons["verification-z"] == ["earliest_failure"]
    assert reasons["verification-b"] == []
    assert reasons["verification-a"] == [
        "latest_command_result",
        "latest_delivery_attempt",
        "latest_reviewed_head_result",
    ]
    assert view["selected_sources"] == [sources[2], sources[0]]

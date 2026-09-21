"""reviewer 验证视图的选择、绑定和防篡改回归。"""

import hashlib
from pathlib import Path

import pytest

import evidence
import review_context

pytestmark = pytest.mark.integration


def run_source(root, number, *, command="test", head=None, dirty="", exit_code=0, delivery=None):
    folder = root / f"verification-{number:04}"
    folder.mkdir()
    log = folder / "output.log"
    log.write_text(f"run {number}\n")
    started = {
        "dispatch_path": str(root / "dispatch.json"),
        "dispatch_sha256": "a" * 64,
        "cwd": str(root),
        "started_ns": number,
        "argv": ["just", "--one", "--", command],
        "before": {"head": head or "b" * 40, "status": dirty},
    }
    if delivery is not None:
        started["delivery_attempt"] = delivery
    evidence.write(folder / "started.json", started)
    if exit_code is None:
        return {
            "directory": str(folder),
            "started": evidence.binding(folder / "started.json"),
            "result": None,
        }
    result = {
        "started_sha256": evidence.digest(folder / "started.json"),
        "ended_ns": number + 1,
        "duration_seconds": 0.1,
        "outcome": "exited",
        "exit_code": exit_code,
        "cancel_signal": None,
        "process_group_gone": True,
        "error": None,
        "after": started["before"],
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "log_bytes": log.stat().st_size,
    }
    evidence.write(folder / "result.json", result)
    return {
        "directory": str(folder),
        "started": evidence.binding(folder / "started.json"),
        "result": evidence.binding(folder / "result.json"),
    }


def test_view_selects_red_latest_and_delivery_without_copying_all_sources(tmp_path):
    context = tmp_path / "context.json"
    evidence.write(context, {"kind": "writer"})
    sources = [
        run_source(tmp_path, 1, exit_code=1),
        run_source(tmp_path, 2),
        run_source(tmp_path, 3),
        run_source(tmp_path, 4, command="gate-core", delivery=1),
    ]
    manifest = tmp_path / "manifest.json"
    evidence.write(manifest, sources)
    view = review_context.build(
        sources,
        "b" * 40,
        {sources[1]["directory"]: "red 后的 green"},
        evidence.binding(context),
        evidence.binding(manifest),
    )
    selected = {Path(item["directory"]).name for item in view["selected_sources"]}
    assert selected == {
        "verification-0001",
        "verification-0002",
        "verification-0003",
        "verification-0004",
    }
    assert "source" not in view["entries"][0]
    assert view["entries"][0]["selected_reasons"] == ["earliest_failure"]
    assert "latest_delivery_attempt" in view["entries"][-1]["selected_reasons"]


def test_view_omits_superseded_middle_repeats(tmp_path):
    context = tmp_path / "context.json"
    evidence.write(context, {})
    sources = [run_source(tmp_path, number) for number in range(1, 5)]
    manifest = tmp_path / "manifest.json"
    evidence.write(manifest, sources)
    view = review_context.build(
        sources,
        "b" * 40,
        {},
        evidence.binding(context),
        evidence.binding(manifest),
    )
    assert [Path(item["directory"]).name for item in view["selected_sources"]] == [
        "verification-0004"
    ]


def test_view_keeps_unknown_and_noted_sources(tmp_path):
    context = tmp_path / "context.json"
    evidence.write(context, {})
    sources = [run_source(tmp_path, 1), run_source(tmp_path, 2, exit_code=None)]
    manifest = tmp_path / "manifest.json"
    evidence.write(manifest, sources)
    view = review_context.build(
        sources,
        "b" * 40,
        {sources[0]["directory"]: "需要保留的说明"},
        evidence.binding(context),
        evidence.binding(manifest),
    )
    assert view["selected_sources"] == sources
    assert "verification_note" in view["entries"][0]["selected_reasons"]
    assert "unknown_result" in view["entries"][1]["selected_reasons"]

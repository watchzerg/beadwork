from pathlib import Path

import pytest

import run_tests


pytestmark = pytest.mark.integration


def test_pytest_argv_keeps_unit_serial_and_parallelizes_slow_suites(tmp_path, monkeypatch):
    monkeypatch.setenv("BEADWORK_TEST_JOBS", "8")
    unit = run_tests.pytest_argv(Path(tmp_path), "unit", [])
    integration = run_tests.pytest_argv(Path(tmp_path), "integration", [])
    assert "-n" not in unit
    assert integration[-3:] == ["-n", "8", "--dist=worksteal"]


def test_all_is_unfiltered_and_gate_rejects_filters(tmp_path):
    command = run_tests.pytest_argv(Path(tmp_path), "all", [], gate=True)
    assert "-m" not in command[4:]
    with pytest.raises(ValueError, match="完整门禁"):
        run_tests.pytest_argv(Path(tmp_path), "all", ["-k", "one"], gate=True)


@pytest.mark.parametrize("extra", [["-m", "unit"], ["-m=unit"]])
def test_extra_marker_expression_cannot_override_suite(tmp_path, extra):
    with pytest.raises(ValueError, match="不能覆盖"):
        run_tests.pytest_argv(Path(tmp_path), "integration", extra)

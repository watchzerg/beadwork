"""统一 CLI 的发现、错误边界和最低版本启动检查。"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CLI = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"
GROUPS = (
    "controller",
    "executor",
    "preflight",
    "plan",
    "graph",
    "run-verification",
    "verify",
    "tracker",
    "batch-initialize",
    "batch-evidence",
)

pytestmark = pytest.mark.integration


def invoke(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(CLI), *arguments],
        cwd=CLI.parents[3],
        capture_output=True,
        text=True,
    )


def test_help_discovers_every_group_and_nested_verifiers() -> None:
    top = invoke("--help")
    assert top.returncode == 0
    for group in GROUPS:
        assert group in top.stdout
        result = invoke(group, "--help")
        assert result.returncode == 0, result.stderr
    verify = invoke("verify", "--help")
    assert all(name in verify.stdout for name in ("ticket", "phase", "worker"))


def test_argument_errors_use_stderr_and_schema_uses_json_stdout() -> None:
    for arguments in (("unknown",), ("controller",), ("verify", "worker", "--schema")):
        result = invoke(*arguments)
        assert result.returncode == 2
        assert not result.stdout
        assert "usage:" in result.stderr
    result = invoke("verify", "ticket", "--schema")
    assert result.returncode == 0
    assert not result.stderr
    assert isinstance(json.loads(result.stdout), dict)


def test_python_below_minimum_fails_before_loading_runtime_modules() -> None:
    code = """import runpy,sys
class Version(tuple):
    major=3; minor=13; micro=9
sys.version_info=Version((3,13,9))
runpy.run_path(sys.argv[1], run_name='beadwork_version_probe')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(CLI)], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert not result.stdout
    diagnostic = json.loads(result.stderr)
    assert "Python 3.14" in diagnostic["error"]

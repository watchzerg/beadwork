"""独立复制后的 skill 分发边界与最低 Python 版本验收。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "skills/beadwork-run"
GENERATED_PATTERNS = ("__pycache__", ".pytest_cache", "*.pyc", "*.pyo", ".DS_Store")
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
PHASES = ("preflight", "finalizer")
WORKER_ROLES = ("fixer", "reviewer", "implementer")

pytestmark = [pytest.mark.integration, pytest.mark.distribution]


@dataclass(frozen=True)
class DistributionRuntime:
    root: Path
    cwd: Path
    environment: dict[str, str]

    @property
    def entrypoint(self) -> Path:
        return self.root / "scripts/beadwork.py"

    def run(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-S", "-B", str(self.entrypoint), *arguments],
            cwd=self.cwd,
            env=self.environment if environment is None else environment,
            capture_output=True,
            text=True,
        )

    def run_code(self, code: str, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-S", "-B", "-c", code, *arguments],
            cwd=self.cwd,
            env=self.environment,
            capture_output=True,
            text=True,
        )


@pytest.fixture
def copied_distribution(tmp_path: Path) -> Path:
    destination = tmp_path / "distribution/beadwork-run"
    shutil.copytree(
        SOURCE,
        destination,
        symlinks=True,
        ignore=shutil.ignore_patterns(*GENERATED_PATTERNS),
    )
    return destination


@pytest.fixture
def distribution_runtime(copied_distribution: Path, tmp_path: Path) -> DistributionRuntime:
    assert sys.version_info[:2] == (3, 14), (
        "distribution suite 必须使用准备好的 Python 3.14，"
        f"当前为 {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    )
    cwd = tmp_path / "unrelated-cwd"
    cwd.mkdir()
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT"):
        environment.pop(name, None)
    environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1")
    return DistributionRuntime(copied_distribution, cwd, environment)


def relative_files(root: Path) -> set[Path]:
    return {path.relative_to(root) for path in root.rglob("*") if path.is_file()}


def test_isolated_runtime_uses_python_314_without_development_paths(
    distribution_runtime: DistributionRuntime,
) -> None:
    assert distribution_runtime.entrypoint.is_file()
    assert distribution_runtime.cwd != SOURCE.parents[1]
    assert "PYTHONPATH" not in distribution_runtime.environment
    result = distribution_runtime.run("--help")
    assert result.returncode == 0, result.stderr
    assert "beadwork.py" in result.stdout
    assert not any(
        path.name in {"__pycache__", ".pytest_cache"} or path.suffix in {".pyc", ".pyo"}
        for path in distribution_runtime.root.rglob("*")
    )


def test_all_cli_groups_and_role_schemas_run_from_copy(
    distribution_runtime: DistributionRuntime,
) -> None:
    top = distribution_runtime.run("--help")
    assert top.returncode == 0, top.stderr
    for group in GROUPS:
        assert group in top.stdout
        result = distribution_runtime.run(group, "--help")
        assert result.returncode == 0, result.stderr
    for kind in ("ticket", "phase", "worker"):
        result = distribution_runtime.run("verify", kind, "--help")
        assert result.returncode == 0, result.stderr

    commands = [("verify", "ticket", "--schema")]
    commands.extend(("verify", "phase", "--schema", phase) for phase in PHASES)
    commands.extend(("verify", "worker", "--schema", role) for role in WORKER_ROLES)
    for command in commands:
        result = distribution_runtime.run(*command)
        assert result.returncode == 0, result.stderr
        assert isinstance(json.loads(result.stdout), dict)

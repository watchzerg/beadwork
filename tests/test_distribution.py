"""独立复制后的 skill 分发边界与最低 Python 版本验收。"""

from __future__ import annotations

import ast
import json
import os
import re
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


def test_copied_distribution_contains_only_skill_content(copied_distribution: Path) -> None:
    expected = {
        path.relative_to(SOURCE)
        for path in SOURCE.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.name not in {".DS_Store"}
        and path.suffix not in {".pyc", ".pyo"}
        and ".pytest_cache" not in path.parts
    }
    assert relative_files(copied_distribution) == expected
    assert {path.name for path in copied_distribution.iterdir()} == {
        "SKILL.md",
        "agents",
        "references",
        "scripts",
    }
    assert not any(
        part in {"__pycache__", ".pytest_cache"}
        or path.suffix in {".pyc", ".pyo"}
        or path.name == ".DS_Store"
        for path in copied_distribution.rglob("*")
        for part in path.parts
    )


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


def test_report_file_and_local_git_boundary_run_from_copy(
    distribution_runtime: DistributionRuntime,
    tmp_path: Path,
) -> None:
    invalid_report = tmp_path / "invalid-report.json"
    invalid_report.write_text("{}", encoding="utf-8")
    checked = distribution_runtime.run("verify", "ticket", "--check-report", str(invalid_report))
    assert checked.returncode == 1, checked.stderr
    assert json.loads(checked.stdout)["ok"] is False

    git = shutil.which("git")
    assert git is not None, "distribution suite 需要宿主 Git 验收本地边界"
    repository = tmp_path / "local-repository"
    repository.mkdir()
    for arguments in (
        ("init", "-b", "main"),
        ("config", "user.email", "distribution@example.com"),
        ("config", "user.name", "Distribution Test"),
    ):
        result = subprocess.run(
            [git, "-C", str(repository), *arguments], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr
    (repository / "tracked.txt").write_text("copied distribution\n", encoding="utf-8")
    for arguments in (("add", "tracked.txt"), ("commit", "-m", "initial")):
        result = subprocess.run(
            [git, "-C", str(repository), *arguments], capture_output=True, text=True
        )
        assert result.returncode == 0, result.stderr

    command_bin = tmp_path / "external-tools"
    command_bin.mkdir()
    bd = command_bin / "bd"
    bd.write_text(
        "#!" + sys.executable + "\n"
        "import json,sys\n"
        "print(json.dumps([] if sys.argv[1] in {'show','comments'} else {}))\n",
        encoding="utf-8",
    )
    bd.chmod(0o755)
    environment = distribution_runtime.environment.copy()
    environment["PATH"] = str(command_bin) + os.pathsep + environment.get("PATH", "")
    output = tmp_path / "batch-facts.json"
    inspected = distribution_runtime.run(
        "batch-evidence",
        "--output",
        str(output),
        "inspect",
        "--repository-root",
        str(repository),
        "--parent-id",
        "demo",
        environment=environment,
    )
    assert inspected.returncode == 0, inspected.stderr
    facts = json.loads(output.read_text(encoding="utf-8"))
    assert facts["repository_root"] == str(repository)
    assert re.fullmatch(r"[0-9a-f]{40}", facts["primary_head"])
    assert facts["parent"] == []
    assert facts["comments"] == []


def test_copied_resources_stay_inside_distribution(copied_distribution: Path) -> None:
    root = copied_distribution.resolve()
    for path in copied_distribution.rglob("*"):
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            assert resolved.is_relative_to(root), (path, resolved)

    failures = []
    for source in copied_distribution.rglob("*.md"):
        text = source.read_text(encoding="utf-8")
        for raw_target in re.findall(r"\[[^]]*\]\(([^)]+)\)", text):
            target = raw_target.split("#", 1)[0]
            if not target or "://" in target or target.startswith(("#", "<")):
                continue
            resolved = (source.parent / target).resolve()
            if not resolved.is_relative_to(root) or not resolved.exists():
                failures.append((str(source.relative_to(root)), raw_target))
    assert not failures


def test_missing_required_external_tool_fails_clearly(
    distribution_runtime: DistributionRuntime,
) -> None:
    environment = distribution_runtime.environment.copy()
    environment["PATH"] = ""
    result = distribution_runtime.run("graph", "check-flat", "demo-parent", environment=environment)
    assert result.returncode == 1
    assert not result.stdout
    diagnostic = json.loads(result.stderr)
    assert "bd" in diagnostic["error"]
    assert "失败" in diagnostic["error"]


def test_runtime_imports_are_stdlib_or_bundled(
    distribution_runtime: DistributionRuntime,
) -> None:
    scripts = distribution_runtime.root / "scripts"
    bundled = {path.stem for path in scripts.glob("*.py")}
    unexpected = []
    dynamic_importers = set()
    for path in scripts.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                names = []
            for name in names:
                top_level = name.split(".", 1)[0]
                if top_level not in bundled and top_level not in sys.stdlib_module_names:
                    unexpected.append((path.name, name))
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
            ):
                dynamic_importers.add(path.name)
    assert not unexpected
    assert dynamic_importers == set()

    probe = """import json,sys
from pathlib import Path
scripts=Path(sys.argv[1]).resolve()
sys.path.insert(0,str(scripts))
import report_io
values=[
 report_io.verifier('executor','--schema'),
 report_io.verifier('preflight','--schema'),
 report_io.verifier('finalizer','--schema'),
 report_io.reviewer('--schema'),
 report_io.implementer('--schema'),
 report_io.fixer('--schema'),
]
names=('report_io','verify_ticket','phase_validation','worker_validation')
origins={name:str(Path(sys.modules[name].__file__).resolve()) for name in names}
print(json.dumps({'schemas':len(values),'origins':origins}))
"""
    result = distribution_runtime.run_code(probe, str(scripts))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schemas"] == 6
    assert all(
        Path(origin).is_relative_to(distribution_runtime.root.resolve())
        for origin in payload["origins"].values()
    )


def test_cli_loads_no_modules_from_repository_or_site_packages(
    distribution_runtime: DistributionRuntime,
    tmp_path: Path,
) -> None:
    audit = tmp_path / "module-audit.json"
    probe = """import json,runpy,sys,sysconfig
from pathlib import Path
entry=Path(sys.argv[1]).resolve()
audit=Path(sys.argv[2])
root=entry.parents[1]
stdlib=Path(sysconfig.get_path('stdlib')).resolve()
sys.argv=[str(entry),'--help']
try:
 runpy.run_path(str(entry),run_name='__main__')
except SystemExit as error:
 code=error.code if isinstance(error.code,int) else 1
external={}
origins={}
bundled={path.stem for path in (root/'scripts').glob('*.py')}
for name,module in tuple(sys.modules.items()):
 origin=getattr(module,'__file__',None)
 if not origin:
  continue
 path=Path(origin).resolve()
 if name in bundled:
  origins[name]=str(path)
 if not path.is_relative_to(root) and not path.is_relative_to(stdlib):
  external[name]=str(path)
audit.write_text(json.dumps({'code':code,'external':external,'origins':origins,'sys_path':sys.path}))
raise SystemExit(code)
"""
    result = distribution_runtime.run_code(probe, str(distribution_runtime.entrypoint), str(audit))
    assert result.returncode == 0, result.stderr
    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert payload["external"] == {}
    assert "cli" in payload["origins"]
    assert all(
        Path(origin).is_relative_to(distribution_runtime.root.resolve())
        for origin in payload["origins"].values()
    )
    repository_root = str(SOURCE.parents[1].resolve())
    assert all(repository_root not in entry for entry in payload["sys_path"])

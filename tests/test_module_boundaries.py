"""模块边界与安装入口回归：防止基础层反向依赖和冷启动副作用。"""

import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

import report_io

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts"

pytestmark = pytest.mark.integration


def dependencies():
    files = {
        p.stem: p for p in SCRIPTS.glob("*.py") if not p.name.startswith(("test_", "fixture_"))
    }
    edges = {}
    for name, path in files.items():
        imports = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "__import__"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                imports.add(node.args[0].value)
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "importlib"
                and node.func.attr == "import_module"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                imports.add(node.args[0].value)
        edges[name] = imports & files.keys()
    return edges


class ModuleBoundaryTests(unittest.TestCase):
    def test_no_cycles_or_reverse_entry_dependencies(self):
        edges = dependencies()
        entry = {"cli"}
        operations = {"controller", "executor_operations"}
        for name, imports in edges.items():
            if name not in {"beadwork", "cli"}:
                self.assertFalse(imports & entry, (name, imports & entry))
            if name not in {"cli", *operations}:
                self.assertFalse(imports & operations, (name, imports & operations))
            seen = set()
            pending = list(imports)
            while pending:
                current = pending.pop()
                self.assertNotEqual(current, name, (name, seen))
                if current not in seen:
                    seen.add(current)
                    pending.extend(edges[current] - seen)
        foundations = {
            "evidence",
            "process_runner",
            "verification_records",
            "schema_validation",
            "review_schema",
            "workflow_policy",
            "repository",
            "dispatch_contract",
            "workflow_contract",
        }
        for name in foundations:
            self.assertLessEqual(edges[name], foundations, name)
        operations = {
            "cli",
            "controller",
            "executor_operations",
            "ticket_execution",
            "finalization",
            "review_operations",
            "run_verification",
        }
        for name in (
            "ticket_state",
            "final_state",
            "gate_repair",
            "ticket_verification",
            "final_verification",
            "handoff",
            "review_evidence",
            "implementer_reports",
            "ticket_reports",
            "fixer_reports",
        ):
            self.assertFalse(edges[name] & operations, (name, edges[name] & operations))

    def test_production_never_imports_test_fixtures(self):
        for path in SCRIPTS.glob("*.py"):
            if path.name.startswith(("test_", "fixture_")):
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                names = (
                    [x.name for x in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                self.assertFalse(any(x.startswith(("test_", "fixture_")) for x in names), path.name)

    def test_schema_construction_does_not_run_commands_or_scan_checkpoints(self):
        code = """from unittest.mock import patch
import runpy,sys
with patch('subprocess.Popen', side_effect=AssertionError('schema 不得执行命令')), patch('pathlib.Path.glob', side_effect=AssertionError('schema 不得扫描检查点')):
    worker = runpy.run_path(sys.argv[1])
    for role in worker['ROLES']:
        schema = worker['report_schema'](role, worker['review_schema'].axis_report_schema())
        worker['schema_validation'].check_schema(schema)
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(SCRIPTS / "worker_validation.py")],
            cwd=SCRIPTS,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_internal_schema_apis_do_not_start_subprocesses(self):
        with (
            patch("subprocess.run", side_effect=AssertionError("schema 不得启动子进程")),
            patch("subprocess.Popen", side_effect=AssertionError("schema 不得启动子进程")),
        ):
            values = [
                report_io.verifier("executor", "--schema"),
                report_io.verifier("preflight", "--schema"),
                report_io.verifier("finalizer", "--schema"),
                report_io.reviewer("--schema"),
                report_io.implementer("--schema"),
                report_io.fixer("--schema"),
            ]
        self.assertTrue(all(isinstance(value, dict) for value in values))

    def test_wrapper_schema_from_installed_symlink_and_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            installed = folder / "installed"
            installed.symlink_to(SCRIPTS.parent, target_is_directory=True)
            for arguments in [
                ("verify", "ticket", "--schema"),
                ("verify", "worker", "--schema", "implementer"),
                ("verify", "phase", "--schema", "finalizer"),
            ]:
                actual = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(installed / "scripts/beadwork.py"),
                        *arguments,
                    ],
                    cwd=folder,
                    capture_output=True,
                    text=True,
                )
                expected = subprocess.run(
                    [sys.executable, "-B", str(SCRIPTS / "beadwork.py"), *arguments],
                    cwd=SCRIPTS,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(actual.returncode, 0, actual.stderr)
                self.assertEqual(expected.returncode, 0, expected.stderr)
                self.assertEqual(json.loads(actual.stdout), json.loads(expected.stdout))


if __name__ == "__main__":
    unittest.main()

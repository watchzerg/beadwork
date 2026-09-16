"""模块边界与安装入口回归：防止基础层反向依赖和冷启动副作用。"""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent


def dependencies():
    files = {p.stem: p for p in SCRIPTS.glob('*.py')
             if not p.name.startswith(('test_', 'fixture_'))}
    edges = {}
    for name, path in files.items():
        imports = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imports.update(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                  and node.func.id == '__import__' and node.args
                  and isinstance(node.args[0], ast.Constant)):
                imports.add(node.args[0].value)
        edges[name] = imports & files.keys()
    return edges


class ModuleBoundaryTests(unittest.TestCase):
    def test_no_cycles_or_reverse_entry_dependencies(self):
        edges = dependencies()
        entries = {'controller', 'executor_operations'}
        for name, imports in edges.items():
            if name != 'executor-operations':
                self.assertFalse(imports & entries, (name, imports & entries))
            seen = set()
            pending = list(imports)
            while pending:
                current = pending.pop()
                self.assertNotEqual(current, name, (name, seen))
                if current not in seen:
                    seen.add(current)
                    pending.extend(edges[current] - seen)
        foundations = {'evidence', 'process_runner', 'verification_records',
                       'schema_validation', 'review_schema', 'workflow_policy',
                       'repository', 'dispatch_contract', 'report_io'}
        for name in foundations:
            self.assertLessEqual(edges[name], foundations, name)
        operations = {'controller', 'executor_operations', 'ticket_execution',
                      'finalization', 'review_operations', 'run_verification'}
        for name in ('ticket_state', 'final_state', 'gate_repair', 'ticket_verification',
                     'final_verification', 'handoff', 'review_evidence',
                     'implementer_reports', 'ticket_reports', 'fixer_reports'):
            self.assertFalse(edges[name] & operations, (name, edges[name] & operations))

    def test_schema_construction_does_not_run_commands_or_scan_checkpoints(self):
        code = '''from unittest.mock import patch
import runpy,sys
with patch('subprocess.Popen', side_effect=AssertionError('schema 不得执行命令')), patch('pathlib.Path.glob', side_effect=AssertionError('schema 不得扫描检查点')):
    worker = runpy.run_path(sys.argv[1])
    for role in worker['ROLES']:
        schema = worker['report_schema'](role, worker['review_schema'].axis_report_schema())
        worker['schema_validation'].check_schema(schema)
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, str(SCRIPTS / 'verify-worker.py')],
                                cwd=SCRIPTS, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrapper_schema_from_installed_symlink_and_unrelated_cwd(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            installed = folder / 'installed'
            installed.symlink_to(SCRIPTS.parent, target_is_directory=True)
            for name, role in [('verify-ticket.py', None), ('verify-worker.py', 'implementer'),
                               ('verify-phase.py', 'finalizer')]:
                args = ['--schema'] + ([role] if role else [])
                actual = subprocess.run([sys.executable, '-B', str(installed / 'scripts' / name), *args],
                                        cwd=folder, capture_output=True, text=True)
                expected = subprocess.run([sys.executable, '-B', str(SCRIPTS / name), *args],
                                          cwd=SCRIPTS, capture_output=True, text=True)
                self.assertEqual(actual.returncode, 0, actual.stderr)
                self.assertEqual(expected.returncode, 0, expected.stderr)
                self.assertEqual(json.loads(actual.stdout), json.loads(expected.stdout))


if __name__ == '__main__':
    unittest.main()

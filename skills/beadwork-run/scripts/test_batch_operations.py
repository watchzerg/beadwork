"""批次初始化、恢复事实、manifest 与摘要的公开事实边界。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import batch_evidence
import batch_initialize
import evidence
import execution_plan



BD_FIXTURE = r'''import json,os,sys,subprocess
from pathlib import Path
p=Path(os.environ['TRACKER_STATE']);s=json.loads(p.read_text());a=sys.argv[1:];root=p.parent
if a[0]=='show': print(json.dumps([s['issue']]))
elif a[0] in ('list','ready'): print(json.dumps(s['children']))
elif a[0]=='dep': print('[]')
elif a[:2]==['worktree','create']:
 subprocess.run(['git','-C',str(root),'worktree','add','-b',a[a.index('--branch')+1],a[2]],check=True)
elif a[:2]==['worktree','info']: print(json.dumps({'is_worktree':Path.cwd()!=root}))
elif a[0]=='where':
 place=root/'.beads' if not s.get('wrong_workspace') or Path.cwd()==root else root/'wrong'
 print(json.dumps({'path':str(place),'database_path':str(place/'db')}))
elif a[:2]==['update','demo']:
 s['issue'].update(status='in_progress',assignee='fixture');p.write_text(json.dumps(s));print('{}')
elif a[:2]==['comments','add']:
 body=Path(a[a.index('-f')+1]).read_text();s['comments'].append({'id':len(s['comments'])+1,'text':body});p.write_text(json.dumps(s));print('{}')
elif a[0]=='comments': print(json.dumps(s['comments']))
else: sys.exit(2)
'''
JUST_FIXTURE = r'''import json,os,sys
from pathlib import Path
p=Path(os.environ['TRACKER_STATE']);s=json.loads(p.read_text());recipe=sys.argv[3]
s.setdefault('runs',[]).append(recipe);p.write_text(json.dumps(s));print('执行 '+recipe)
sys.exit(1 if s.get('fail')==recipe else 0)
'''

class BatchOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"; self.root.mkdir()
        self.git("init", "-b", "main"); self.git("config", "user.email", "test@example.com"); self.git("config", "user.name", "Test")
        (self.root / "base.txt").write_text("base"); self.git("add", "."); self.git("commit", "-m", "base")
        (self.root / ".git/info/exclude").write_text("*\n")
        self.bin = self.root / "bin"; self.bin.mkdir(); self.state = self.root / "tracker.json"
        self.state.write_text(json.dumps({"issue": {"id": "demo", "status": "open", "assignee": None, "description": execution_plan.replace("", {"ticket_order": ["demo-1"]})}, "children": [{"id": "demo-1", "status": "open"}], "comments": []}))
        bd = self.bin / 'bd'; bd.write_text('#!' + sys.executable + '\n' + BD_FIXTURE); bd.chmod(0o755)
        just = self.bin / 'just'; just.write_text('#!' + sys.executable + '\n' + JUST_FIXTURE); just.chmod(0o755)
        old = os.environ.get("PATH", ""); os.environ["PATH"] = str(self.bin) + os.pathsep + old
        os.environ["TRACKER_STATE"] = str(self.state); self.addCleanup(lambda: os.environ.__setitem__("PATH", old))

    def git(self, *args):
        p = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr); return p.stdout.strip()

    def acceptance(self, role, ticket=None):
        folder = self.root / (role + ("-" + ticket if ticket else "")); folder.mkdir()
        gate_plan_path = folder / 'gate-plan.json'
        evidence.write(gate_plan_path, {"core": "gate-core", "full": ["gate-core", "gate-demo"]})
        dispatch = {"role": role, "parent_id": "demo", "ticket_id": ticket,
                    "dispatch_path": str(folder / "dispatch.json"), "repository_root": str(self.root)}
        report = ({"status": "READY", "expected_children": ["demo-1"], "suggested_route": "new_batch", "execution_plan": {"ticket_order": ["demo-1"]},
                   "gate_plan": {"core": "gate-core", "full": ["gate-core", "gate-demo"]},
                   "gate_plan_source": evidence.binding(gate_plan_path)} if role == "preflight" else
                  {"status": "DONE", "base_commit": self.git("rev-parse", "HEAD"),
                   "head_commit": self.git("rev-parse", "HEAD"), "implementation_commits": [],
                   "required_boundary_gates": ["gate-demo"]})
        receipt = {"status": report["status"]}
        for name, value in (("dispatch", dispatch), ("report", report), ("receipt", receipt)):
            evidence.write(folder / (name + ".json"), value)
        accepted = {"kind": "mechanical_acceptance", "role": role, "status": report["status"]}
        for name in ("dispatch", "report", "receipt"):
            path = folder / (name + ".json"); accepted[name + "_path"] = str(path); accepted[name + "_sha256"] = evidence.digest(path)
        path = folder / "accepted.json"; evidence.write(path, accepted); return path

    def initialize(self):
        accepted = self.acceptance('preflight')
        report_path = accepted.parent / 'report.json'
        selected = execution_plan.adopt(str(self.root), 'demo', {'ticket_order': ['demo-1']},
                                       [{'id': 'demo-1', 'status': 'open'}], [evidence.binding(report_path)], '测试批准')
        value = evidence.read(accepted); value['execution_plan_source'] = selected
        accepted.write_text(json.dumps(value))
        update = self.root / 'update-main.json'
        evidence.write(update, {'repository_root': str(self.root), 'main_commit': self.git('rev-parse', 'HEAD'),
                                'fetch_failed': False, 'note': ''})
        source = self.root / 'init-input.json'; evidence.write(source, {
            'repository_root': str(self.root), 'parent_id': 'demo', 'expected_children': ['demo-1'],
            'preflight_acceptance': evidence.binding(accepted), 'update_main_result': evidence.binding(update),
            'expected_assignee': 'fixture'})
        folder = self.root / '.worktrees/.evidence/demo/initialize/first'; folder.mkdir(parents=True)
        intent = folder / 'intent.json'
        self.cli('prepare', '--input', source, '--output', intent)
        return intent

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, '-B', str(Path(batch_initialize.__file__)), *map(str, args)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def change_state(self, **fields):
        value = json.loads(self.state.read_text()); value.update(fields); self.state.write_text(json.dumps(value))

    def test_initialization_is_resumable(self):
        intent = self.initialize()
        first = self.cli('execute', '--intent', intent)
        self.assertEqual(first, self.cli('execute', '--intent', intent))
        (intent.parent / 'ready.json').unlink()
        second = self.cli('execute', '--intent', intent)
        self.assertEqual(first['comment_id'], second['comment_id'])
        state = json.loads(self.state.read_text())
        self.assertEqual(state['issue']['status'], 'in_progress')
        self.assertEqual(len(state['comments']), 1)
        self.assertEqual(state['runs'], ['install', 'env-facts', 'gate-full'])

    def test_install_failure_and_gate_failure_resume_without_claiming_early(self):
        intent = self.initialize()
        self.change_state(fail='install')
        self.cli('execute', '--intent', intent, ok=False)
        self.assertEqual(json.loads(self.state.read_text())['issue']['status'], 'open')
        self.change_state(fail='gate-full')
        self.cli('execute', '--intent', intent, ok=False)
        self.assertEqual(json.loads(self.state.read_text())['comments'], [])
        self.change_state(fail='')
        self.cli('execute', '--intent', intent)
        self.assertEqual(json.loads(self.state.read_text())['runs'], ['install', 'install', 'env-facts', 'gate-full', 'gate-full'])
        self.assertEqual(len(list((intent.parent / 'install').glob('attempt-*'))), 2)

    def test_unknown_command_requires_bound_stop_observation(self):
        intent = self.initialize(); self.change_state(fail='install')
        self.cli('execute', '--intent', intent, ok=False)
        run = next((intent.parent / 'install').glob('attempt-*'))
        (run / 'result.json').unlink()
        self.change_state(fail='')
        error = self.cli('execute', '--intent', intent, ok=False)
        self.assertIn('收尾', error['error'])
        recovery = self.root / 'recovery.json'
        evidence.write(recovery, [{'run_path': str(run), 'task_id': 'fixture', 'stopped': True,
                                   'observed_at': '2026-09-17T00:00:00Z', 'evidence': '测试进程已退出', 'unresolved': []}])
        self.cli('execute', '--intent', intent, '--recovery', recovery)
        self.assertTrue((run / 'closure.json').exists())

    def test_wrong_workspace_and_started_child_stop_initialization(self):
        intent = self.initialize(); self.change_state(wrong_workspace=True)
        error = self.cli('execute', '--intent', intent, ok=False)
        self.assertIn('workspace', error['error'])
        self.assertNotIn('runs', json.loads(self.state.read_text()))
        self.change_state(wrong_workspace=False, children=[{'id': 'demo-1', 'status': 'in_progress', 'assignee': 'fixture'}])
        self.cli('execute', '--intent', intent, ok=False)
        self.assertNotIn('runs', json.loads(self.state.read_text()))

    def test_baseline_change_stops_before_worktree_creation(self):
        intent = self.initialize()
        (self.root / 'base.txt').write_text('新基线'); self.git('add', 'base.txt'); self.git('commit', '-m', '新基线')
        self.cli('execute', '--intent', intent, ok=False)
        self.assertFalse((self.root / '.worktrees/demo').exists())

    def test_lost_claim_and_comment_results_are_read_back_without_duplication(self):
        intent = self.initialize()
        first = self.cli('execute', '--intent', intent)
        for name in ('ready.json', 'claim-intent-result.json', 'comment-intent-result.json'):
            (intent.parent / name).unlink()
        again = self.cli('execute', '--intent', intent)
        self.assertEqual(first['comment_id'], again['comment_id'])
        self.assertEqual(len(json.loads(self.state.read_text())['comments']), 1)

    def test_manifest_and_summary(self):
        accepted = self.acceptance("executor", "demo-1")
        source = self.root / "manifest-input.json"; evidence.write(source, {
            "parent_id": "demo", "expected_children": ["demo-1"], "acceptances": [evidence.binding(accepted)]})
        manifest = batch_evidence.manifest(source); self.assertEqual(manifest["required_boundary_gates"], ["gate-demo"])
        manifest_path = self.root / "manifest.json"; evidence.write(manifest_path, manifest)
        facts = batch_evidence.inspect(self.root, "demo"); facts_path = self.root / "facts.json"; evidence.write(facts_path, facts)
        summary_input = self.root / "summary-input.json"; evidence.write(summary_input, {
            "facts": evidence.binding(facts_path), "manifest": evidence.binding(manifest_path),
            "status": "BLOCKED", "cause": "等待外部确认", "uncertainties": ["宿主任务状态"], "recommendation": "核对后恢复"})
        result = batch_evidence.summary(summary_input)
        self.assertIn("demo-1", result["text"]); self.assertTrue(result["facts"]["external_stop_observation_required"])

        bad = self.root / "bad-manifest.json"; evidence.write(bad, {
            "parent_id": "demo", "expected_children": ["demo-2"], "acceptances": [evidence.binding(accepted)]})
        with self.assertRaises(ValueError): batch_evidence.manifest(bad)
        Path(json.loads(accepted.read_text())["report_path"]).write_text("{}")
        with self.assertRaises(ValueError): batch_evidence.manifest(source)

    def test_inspect_reports_ambiguous_pending_operations(self):
        for name in ("a", "b"):
            folder = self.root / ".worktrees/.evidence/demo" / name; folder.mkdir(parents=True, exist_ok=True)
            evidence.write(folder / "intent.json", {"name": name})
        before = self.git("status", "--porcelain=v1", "--untracked-files=all")
        facts = batch_evidence.inspect(self.root, "demo")
        self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all"), before)
        self.assertEqual(len(facts["pending_operations"]), 2)
        self.assertTrue(facts["conflicts"])


if __name__ == "__main__": unittest.main()

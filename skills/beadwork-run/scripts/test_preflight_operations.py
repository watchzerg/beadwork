"""真实临时 Git/worktree 下检查采集、语义合并和既有 controller 验收。"""
import json
import execution_plan
import evidence
from pathlib import Path
import subprocess
import sys
import unittest

import test_controller as fixture
import test_verify_phase as phase_fixture

SCRIPT = Path(__file__).with_name('preflight-operations.py')


class PreflightOperationsTests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.ControllerTests(); self.h.setUp(); self.addCleanup(self.h.doCleanups)
        value = {'ticket_order': ['test-1', 'test-2']}
        approved = self.h.root / 'approved-order.json'; evidence.write(approved, value)
        execution_plan.adopt(self.h.primary, 'test', value,
            [{'id': ticket, 'status': 'open'} for ticket in value['ticket_order']], [evidence.binding(approved)], '测试批次首次批准')
        self.h.prepare('preflight', expected_children=['test-1', 'test-2'])
        self.h.put(self.h.root / 'parent.json', [{'id': 'test', 'status': 'in_progress', 'description': execution_plan.replace('已批准 S1', {'ticket_order': ['test-1', 'test-2']})}])
        self.h.put(self.h.root / 'children.json', [dict(id='test-1', status='open', labels=['ready-for-agent'], description='完整票据'),
                                                dict(id='test-2', status='closed')])
        self.h.put(self.h.root / 'config.json', [dict(key='export.auto', value='false'), dict(key='export.git-add', value=False)])
        self.h.put(self.h.root / 'edges.json', [])
        bd = self.h.root / 'bin/bd'
        bd.write_text('#!' + sys.executable + '\n' + '''import json, os, sys
from pathlib import Path
a = sys.argv[1:]
assert '--readonly' in a and '--json' in a, a
root = Path(os.environ['BD_FIXTURE_SHOW']).parent
with (root / 'calls.jsonl').open('a') as f: f.write(json.dumps(a) + '\\n')
name = {'show':'parent', 'list':'children', 'comments':'comments', 'config':'config', 'dep':'edges'}[a[0]]
print('[]' if a[0]=='dep' and '--type=blocks' in a else (root / (name + '.json')).read_text())
''')
        bd.chmod(0o755)
        just = self.h.root / 'bin/just'
        just.write_text('#!' + sys.executable + '\n' + '''import sys
if sys.argv[1:] == ['--summary']:
    print('check-toolchain install typecheck test gate-plan gate-core gate-full env-facts fmt gate-browser')
elif sys.argv[1:] == ['--one', '--', 'gate-plan']:
    print('{"core":"gate-core","full":["gate-core","gate-browser"]}')
else:
    assert sys.argv[1:] == ['--one', '--', 'check-toolchain'], sys.argv
''')
        just.chmod(0o755)
        self.draft = dict(status='READY', plans={'test-1': phase_fixture.PhaseValidatorTests().plan()},
                          linked_spec='test', resume_evidence=['已有批次记录'], sources=['已核对 spec'],
                          suggested_route='resume_tickets', checks=[dict(name=n, passed=True, evidence='已核对语义')
                          for n in ('spec_and_test_plans', 'recovery')], blockers=[], remaining_work=[])

    def call(self, command, *args, ok=True):
        p = subprocess.run([sys.executable, '-B', str(SCRIPT), command, '--dispatch', str(self.h.dispatch), *map(str, args)],
                           cwd=self.h.root, env=self.h.env, capture_output=True, text=True)
        self.assertEqual(p.returncode == 0, ok, p.stdout + p.stderr)
        return json.loads(p.stdout if ok else p.stderr)

    def collect(self):
        self.facts = self.call('collect')
        return self.facts

    def assemble(self, ok=True, name='report.json'):
        source = self.h.root / 'draft.json'; self.h.put(source, self.draft)
        return self.call('assemble', '--facts-sha256', self.facts['facts_sha256'], '--draft', source,
                         '--output', self.h.dispatch.parent / name, ok=ok)

    def test_collect_once_assemble_and_controller_accept(self):
        self.collect()
        calls = [json.loads(x) for x in (self.h.root / 'calls.jsonl').read_text().splitlines()]
        self.assertEqual([x[0] for x in calls].count('list'), 1)
        self.assertEqual([x[0] for x in calls].count('show'), 1)
        self.assertEqual(self.facts['pending_ids'], ['test-1'])
        self.assertEqual(self.facts['failed_checks'], [])
        snapshot = json.loads(Path(self.facts['facts_path']).read_text())
        self.assertEqual(snapshot['gate_plan'], {'core': 'gate-core', 'full': ['gate-core', 'gate-browser']})
        receipt = self.assemble()
        self.h.report = self.h.dispatch.parent / 'report.json'
        self.h.receipt = self.h.dispatch.parent / 'receipt.json'; self.h.put(self.h.receipt, receipt)
        self.h.accept()
        r = json.loads(self.h.report.read_text())
        self.assertEqual(r['boundary_gates'], ['gate-browser'])
        self.assertIsNone(r['tickets'][1]['test_plan'])
        timing = json.loads(self.h.report.with_suffix('.timing.json').read_text())
        self.assertEqual(timing['report_sha256'], receipt['report_sha256'])
        self.assertTrue(all(timing[k] >= 0 for k in ('collection_seconds', 'semantic_and_wait_seconds', 'assembly_seconds')))
        self.call('collect', ok=False)
        self.assemble(ok=False)

    def test_missing_parent_plan_cannot_be_overridden_by_ready_draft(self):
        self.h.put(self.h.root / 'parent.json', [{'id': 'test', 'status': 'in_progress', 'description': '没有执行计划'}])
        self.collect()
        self.assertIn('execution_plan', {x['name'] for x in self.facts['failed_checks']})
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_range_change_cannot_be_overridden_by_ready_draft(self):
        self.h.d['expected_children'] = ['test-1']; self.h.put(self.h.dispatch, self.h.d)
        self.collect()
        self.assertTrue(self.facts['blockers'])
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_failed_mechanical_config_and_graph_stay_blocked(self):
        self.h.put(self.h.root / 'config.json', [dict(key='export.auto', value='true')])
        self.h.put(self.h.root / 'edges.json', [{'id': 'grandchild-1'}])
        self.collect()
        self.assertEqual({x['name'] for x in self.facts['failed_checks']}, {'beads_config', 'flat_graph'})
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_invalid_json_is_preserved_and_blocks(self):
        (self.h.root / 'children.json').write_text('invalid')
        self.collect()
        self.draft['plans'] = {}
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_tampered_raw_evidence_and_snapshot_are_rejected(self):
        self.collect()
        source = self.h.dispatch.parent / 'facts/children.json'
        raw = source.read_bytes(); source.write_text('{}')
        self.assemble(ok=False)
        source.write_bytes(raw)
        Path(self.facts['facts_path']).write_text('{}')
        self.assemble(ok=False)

    def test_semantic_failure_missing_plan_and_extra_check(self):
        self.collect()
        self.draft['checks'][0]['passed'] = False
        self.assertEqual(self.assemble()['status'], 'BLOCKED')
        self.draft['checks'][0]['passed'] = True
        self.draft['plans'] = {}
        self.assemble(ok=False, name='report-2.json')
        self.draft['checks'].append(dict(name='toolchain', passed=True, evidence='尝试覆盖'))
        self.assemble(ok=False, name='report-3.json')

    def test_unknown_gate_is_blocked(self):
        self.collect()
        self.draft['plans']['test-1']['boundary_gates'] = ['gate-absent']
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_gate_plan_rejects_duplicate_and_unregistered_members(self):
        just = self.h.root / 'bin/just'
        just.write_text('#!' + sys.executable + '\n' + '''import sys
if sys.argv[1:] == ['--summary']:
    print('check-toolchain install typecheck test gate-plan gate-core gate-full env-facts fmt gate-browser gate-extra')
elif sys.argv[1:] == ['--one', '--', 'gate-plan']:
    print('{"core":"gate-core","full":["gate-core","gate-browser","gate-browser"]}')
else:
    assert sys.argv[1:] == ['--one', '--', 'check-toolchain'], sys.argv
''')
        just.chmod(0o755)
        self.collect()
        self.assertIn('gate_plan', {x['name'] for x in self.facts['failed_checks']})
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_command_failures_remain_inspectable(self):
        (self.h.root / 'bin/just').write_text('#!' + sys.executable + '\nimport sys\nsys.exit(9)\n')
        self.collect()
        self.assertEqual({x['name'] for x in self.facts['failed_checks']}, {'toolchain', 'just_recipes', 'gate_plan'})
        result = json.loads((self.h.dispatch.parent / 'facts/toolchain.json').read_text())
        self.assertEqual(result['exit_code'], 9)
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_existing_worktree_cannot_be_declared_new_batch(self):
        self.h.put(self.h.root / 'parent.json', [{'id': 'test', 'status': 'open'}])
        self.collect()
        self.draft['suggested_route'] = 'new_batch'
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_closed_parent_with_unfinished_children_is_blocked(self):
        self.h.put(self.h.root / 'parent.json', [{'id': 'test', 'status': 'closed'}])
        self.collect()
        self.draft['suggested_route'] = 'post_merge'
        self.assertEqual(self.assemble()['status'], 'BLOCKED')

    def test_all_closed_can_finalize_an_unmerged_batch(self):
        self.h.put(self.h.root / 'children.json', [dict(id='test-1', status='closed'), dict(id='test-2', status='closed')])
        self.collect()
        self.draft.update(plans={}, suggested_route='finalize')
        self.assertEqual(self.assemble()['status'], 'READY')

    def test_missing_worktree_is_a_new_batch_observation(self):
        self.h.h.git(self.h.primary, 'worktree', 'remove', str(self.h.wt))
        self.collect()
        f = json.loads(Path(self.facts['facts_path']).read_text())
        self.assertIsNone(f['workspace']['observed_head'])
        self.assertIsNone(f['workspace']['clean'])
        self.assertEqual(self.facts['failed_checks'], [])
        self.h.put(self.h.root / 'parent.json', [{'id': 'test', 'status': 'open'}])
        # 已采集 parent 是 in_progress，且分支仍在；两者都不能伪装成全新批次。
        self.draft['suggested_route'] = 'new_batch'
        self.assertEqual(self.assemble()['status'], 'BLOCKED')


if __name__ == '__main__':
    unittest.main()

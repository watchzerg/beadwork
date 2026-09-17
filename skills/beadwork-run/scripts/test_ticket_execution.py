"""通过公开 CLI 验证整票协调、implementer gate-fix、review 和恢复边界。"""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import evidence
import test_controller as fixture
import test_executor_operations as review_fixture

SCRIPTS = Path(__file__).resolve().parent


class TicketExecutionTests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.utility_fixture = False
        self.h.prepare(mode='new', test_mode='direct_verification', approved_seams=[], required_boundary_gates=['gate-demo'])
        self.root_dispatch = self.h.dispatch
        self.serial = 0
        fake = self.h.root / 'bin/just'
        fake.write_text('#!' + sys.executable + '\n' + '''import os,sys
if sys.argv[1:] == ['--summary']:
    print('check-toolchain install test typecheck gate-plan gate-core gate-full env-facts fmt gate-demo'); sys.exit(0)
assert sys.argv[1:3] == ['--one','--']
if sys.argv[3] == 'gate-plan':
    print('{"core":"gate-core","full":["gate-core","gate-demo"]}'); sys.exit(0)
print('验证结果')
sys.exit(7 if os.environ.get('FAIL_GATE') == sys.argv[3] else 0)
''')
        fake.chmod(0o755)
        self.stage()

    def cli(self, command, *args, ok=True, env=None):
        result = subprocess.run([sys.executable, '-B', str(SCRIPTS / command), *map(str, args)],
                                cwd=self.h.root, env=env or self.h.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def file(self, name, data, folder=None):
        self.serial += 1
        path = (folder or self.h.root) / f'{name}-{self.serial}.json'
        self.h.put(path, data)
        return path

    def stage(self, continuation='resume', ok=True, **facts):
        result = self.cli('executor-operations.py', 'ticket-stage', '--dispatch', self.root_dispatch,
                          '--input', self.file('facts', dict(continuation=continuation, **facts)), ok=ok)
        if ok:
            self.sd = Path(result['stage_dispatch'])
            self.wd = Path(result['implementer_dispatch'])
            self.stage_info = result
        return result

    def commit(self):
        self.serial += 1
        (self.h.wt / 'ticket.txt').write_text(f'实现 {self.serial}')
        self.h.h.git(self.h.wt, 'add', 'ticket.txt')
        self.h.h.git(self.h.wt, 'commit', '-m', f'test-1 实现 {self.serial}')

    def gate(self, recipe='gate-core', fail=False, delivery=True):
        argv = ['run-verification.py', '--dispatch', self.wd, '--recipe', recipe]
        if delivery: argv.append('--delivery')
        result = subprocess.run([sys.executable, '-B', str(SCRIPTS / argv[0]), *map(str, argv[1:])],
                                cwd=self.h.root, env={**self.h.env, 'FAIL_GATE': recipe if fail else ''}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1 if fail else 0, result.stdout + result.stderr)
        return Path(json.loads(result.stdout)['run_path']) / 'result.json'

    def draft(self, outcome='passed'):
        d = json.loads(self.wd.read_text())
        return {'status': 'DONE' if outcome == 'passed' else 'BLOCKED', 'outcome': outcome,
                'test_plan': {'decision_source': 'ticket/spec', 'red_evidence': '实际行为 red' if d['test_mode'] == 'TDD' else None},
                'acceptance': [{'criterion': '目标行为', 'evidence': '实现与 gate 日志'}], 'verification': [],
                'requested_context': [], 'blockers': [] if outcome == 'passed' else ['阶段未完成'], 'concerns': []}

    def implement(self, outcome='passed', ok=True, accept=True, **changes):
        draft = dict(self.draft(outcome), verification_notes={}, stopped_tasks=True, required_boundary_gates=['gate-demo'])
        draft.update(changes)
        output = self.file('unused', {}, self.wd.parent)
        output.unlink()
        receipt = self.cli('executor-operations.py', 'implementer-assemble', '--dispatch', self.wd,
                           '--draft', self.file('writer-draft', draft), '--output', output, ok=ok)
        if ok:
            rp = self.file('receipt', receipt, self.wd.parent)
            if accept:
                from test_controller import closure_source
                cp = closure_source(self.wd, output)
                self.cli('executor-operations.py', 'implementer-accept', '--dispatch', self.sd,
                         '--report', output, '--receipt', rp, '--closure', cp)
            self.writer_report, self.writer_receipt = output, rp
        return receipt

    def review(self, blocking=False):
        e = review_fixture.ExecutorOperationsTests()
        e.h, e.dispatch, e.directory = self.h, self.sd, self.sd.parent
        evidence = None
        if self.h.h.git(self.h.wt, 'rev-parse', 'HEAD') == json.loads(self.sd.read_text())['base_commit']:
            evidence = self.file('acceptance', [{'criterion': '目标行为', 'evidence': '现有行为与验证'}])
        return e.collect(e.round(blocking=blocking, evidence=evidence))

    def assemble(self, reviews=(), outcome='passed', ok=True, **changes):
        draft = dict(self.draft(outcome), stopped_tasks=True, **changes)
        output = self.file('unused', {}, self.sd.parent); output.unlink()
        argv = ['ticket-assemble', '--dispatch', self.sd, '--draft', self.file('stage-draft', draft), '--output', output]
        for review in reviews: argv += ['--review', review]
        result = self.cli('executor-operations.py', *argv, ok=ok)
        if ok: self.stage_report = output
        return result

    def deliver(self, ok=True):
        output = self.file('unused', {}, self.root_dispatch.parent); output.unlink()
        receipt = self.cli('executor-operations.py', 'ticket-deliver', '--dispatch', self.root_dispatch, '--output', output, ok=ok)
        if ok:
            rp = self.file('receipt', receipt, output.parent)
            self.root_report, self.root_receipt = output, rp
            self.acceptance = output.parent / ('accepted-' + str(self.serial) + '.json')
            from test_controller import closure_source
            cp = closure_source(self.root_dispatch, output)
            self.cli('controller.py', 'accept', '--dispatch', self.root_dispatch, '--report', output,
                     '--receipt', rp, '--output', self.acceptance, '--closure', cp)
        return receipt

    def ready_writer(self):
        self.commit(); self.gate(); self.gate('gate-demo'); self.implement()

    def test_full_ticket_and_controller_accept(self):
        self.ready_writer()
        self.assemble([self.review()])
        self.deliver()
        self.stage(ok=False)

    def test_stage_assemble_uses_checkpoint_selected_review(self):
        self.ready_writer()
        selected = self.review()
        self.assemble()
        report = json.loads(self.stage_report.read_text())
        self.assertEqual(report['review']['sources'], [evidence.binding(selected)])

    def test_no_commit_existing_behavior(self):
        self.gate(); self.gate('gate-demo'); self.implement()
        self.assemble([self.review()]); self.deliver()
        self.assertEqual(json.loads(self.stage_report.read_text())['delivery_kind'], 'already_satisfied')

    def test_implementer_done_cannot_close_ticket_or_skip_review(self):
        self.ready_writer()
        self.deliver(ok=False)
        self.assemble(ok=False)
        self.cli('controller.py', 'accept', '--dispatch', self.root_dispatch, '--report', self.writer_report,
                 '--receipt', self.writer_receipt, '--output', self.root_dispatch.parent / 'invalid.json', ok=False)

    def test_missing_gate_and_stale_head_rejected(self):
        self.commit(); self.gate(); self.implement(ok=False)
        self.gate('gate-demo'); self.commit(); self.implement(ok=False)
        self.gate(); self.gate('gate-demo'); self.implement()

    def test_review_requires_accepted_implementation_and_one_round(self):
        self.commit()
        self.cli('executor-operations.py', 'review-prepare', '--dispatch', self.sd, ok=False)
        self.gate(); self.gate('gate-demo'); self.implement()
        self.review()
        self.cli('executor-operations.py', 'review-prepare', '--dispatch', self.sd, ok=False)
        self.cli('run-verification.py', '--dispatch', self.wd, '--recipe', 'gate-core', '--delivery', ok=False)

    def test_six_review_stages_and_models(self):
        reviews = []
        for number in range(6):
            self.assertEqual(self.stage_info['stage'], number)
            expected = [('gpt-5.6-terra', 'medium'), ('gpt-5.6-terra', 'medium'),
                        ('gpt-5.6-terra', 'high'), ('gpt-5.6-terra', 'high'),
                        ('gpt-5.6-sol', 'medium'), ('gpt-5.6-sol', 'medium')][number]
            model = self.stage_info['models']['implementer']
            self.assertEqual((model['model'], model['reasoning_effort']), expected)
            self.ready_writer()
            reviews.append(self.review(blocking=number < 5))
            self.assemble(reviews, 'code_failure' if number < 5 else 'passed')
            if number < 5:
                self.deliver(ok=False)
                self.stage('repair')
        self.deliver()
        self.stage('repair', ok=False)
        self.assertEqual(self.stage_info['models']['implementer']['model'], 'gpt-5.6-sol')

    def test_gate_exhaustion_advances_only_after_three_repairs(self):
        self.commit()
        failure = self.gate(fail=True)
        self.implement('code_failure', ok=False)
        for number in range(3):
            result = self.cli('executor-operations.py', 'begin-gate-repair', '--dispatch', self.wd, '--failure', failure)
            self.assertEqual(result['repair_number'], number + 1)
            self.stage()
            self.commit(); failure = self.gate(fail=True)
        self.implement('code_failure'); self.assemble(outcome='code_failure')
        self.stage(ok=False); self.stage('repair')
        self.assertEqual(self.stage_info['stage'], 1)
        failure = self.gate(fail=True)
        result = self.cli('executor-operations.py', 'begin-gate-repair', '--dispatch', self.wd, '--failure', failure)
        self.assertEqual(result['repair_number'], 1)

    def test_interruption_and_executor_resume_preserve_stage_and_dirty_work(self):
        (self.h.wt / 'unfinished.txt').write_text('保留')
        self.implement('interrupted'); self.assemble(outcome='interrupted'); self.deliver()
        d = json.loads(self.root_dispatch.read_text())
        d.update(mode='resume', previous_dispatch=str(self.root_dispatch))
        result = self.cli('controller.py', 'prepare', 'executor', '--input', self.file('resume', d))
        self.assertEqual(result['dispatch_path'], str(self.root_dispatch))
        old = self.wd; self.stage()
        self.assertEqual(old, self.wd)
        self.assertEqual((self.h.wt / 'unfinished.txt').read_text(), '保留')
        self.stage('repair', ok=False)

    def test_external_blocking_review_does_not_advance(self):
        self.ready_writer()
        self.assemble([self.review(blocking=True)], 'blocked'); self.deliver()
        self.stage('repair', ok=False)
        self.stage()
        self.assertTrue(self.stage_info['review_started'])

    def test_tampered_writer_source_rejected(self):
        self.ready_writer()
        self.writer_report.write_text(self.writer_report.read_text() + '\n')
        self.cli('executor-operations.py', 'review-prepare', '--dispatch', self.sd, ok=False)

    def test_checkpoint_chain_tamper_rejected(self):
        first = self.root_dispatch.parent / 'checkpoint-000001.json'
        first.write_text(first.read_text() + '\n')
        # 单个检查点还没有后继 hash；追加后篡改必然被拒绝。
        self.implement('interrupted')
        first.write_text(first.read_text() + '\n')
        self.stage(ok=False)

    def test_baseline_adaptation_stays_in_stage_and_preserves_writer_history(self):
        # 从 direct verification 恢复 TDD 必须有已批准 seam，因此使用新的原始 TDD ticket。
        self.h.prepare(mode='new', test_mode='TDD', approved_seams=['S1'], required_boundary_gates=['gate-demo'])
        self.root_dispatch = self.h.dispatch; self.stage()
        self.gate('test', delivery=False)
        original = self.wd
        result = self.cli('executor-operations.py', 'ticket-adapt-plan', '--dispatch', self.sd, '--input',
                         self.file('adapt', {'mode': 'direct_verification', 'reason': 'BASE 已满足行为',
                             'acceptance': [{'criterion': '目标行为', 'evidence': 'BASE 实现'}],
                             'verification': [{'command': 'just test', 'result': 'BASE 通过'}], 'boundary_gates': ['gate-demo']}))
        self.sd, self.wd = Path(result['stage_dispatch']), Path(result['implementer_dispatch'])
        self.assertIn(str(original), json.loads(self.wd.read_text())['verification_dispatches'])
        self.gate(); self.gate('gate-demo'); self.implement()
        self.assemble([self.review()]); self.deliver()

    def test_latest_failed_gate_cannot_be_hidden_by_earlier_pass(self):
        self.commit(); self.gate(); self.gate('gate-demo')
        self.gate(fail=True)
        self.implement(ok=False)

    def test_latest_checkpoint_state_tamper_rejected(self):
        path = self.root_dispatch.parent / 'checkpoint-000001.json'
        data = json.loads(path.read_text())
        data['state']['stage_dispatch'] = None
        self.h.put(path, data)
        self.stage(ok=False)

    def test_review_failure_cannot_be_reported_as_interrupted(self):
        self.ready_writer()
        self.assemble([self.review(blocking=True)], 'interrupted', ok=False)

    def test_selected_blocking_review_cannot_be_omitted_after_assembly(self):
        self.ready_writer()
        review = self.review(blocking=True)
        self.assemble([review], 'code_failure')
        original = self.stage_report.read_bytes()
        self.assemble(outcome='interrupted', ok=False)
        self.assertEqual(self.stage_report.read_bytes(), original)
        self.stage('repair')

    def test_collected_review_survives_resume_before_stage_assembly(self):
        self.ready_writer()
        review = self.review(blocking=True)
        self.stage()
        self.assertEqual(self.stage_info['selected_review']['path'], str(review))
        self.assemble(outcome='interrupted', ok=False)
        self.assemble([review], 'code_failure')
        self.stage('repair')

    def test_completed_prior_stage_review_cannot_be_reselected(self):
        self.ready_writer()
        review = self.review(blocking=True)
        collection = json.loads(review.read_text())
        alternate = self.file('another-round', json.loads(Path(collection['round']['path']).read_text()), review.parent)
        self.cli('executor-operations.py', 'review-collect', '--round', alternate,
                 '--input', review.parent / 'selection.json', '--output', review.parent / 'another.json', ok=False)
        self.assemble([review], 'code_failure')
        self.stage('repair')
        self.cli('executor-operations.py', 'review-collect', '--round', collection['round']['path'],
                 '--input', review.parent / 'selection.json', '--output', review.parent / 'late.json', ok=False)
        self.assertIsNone(self.stage()['selected_review'])

    def test_uncollected_review_can_resume_and_collect_original_round(self):
        self.ready_writer()
        e = review_fixture.ExecutorOperationsTests()
        e.h, e.dispatch, e.directory = self.h, self.sd, self.sd.parent
        round_data = e.round()
        self.assemble(outcome='interrupted'); self.deliver()
        self.stage()
        self.assertIsNone(self.stage_info['selected_review'])
        self.assertEqual(self.stage_info['review_round'], str(round_data[0]))
        review = e.collect(round_data)
        self.assemble([review]); self.deliver()

    def test_history_omission_and_duplicate_review_rejected(self):
        self.ready_writer()
        first = self.review(blocking=True)
        self.assemble([first], 'code_failure'); self.stage('repair')
        self.ready_writer(); second = self.review()
        self.assemble([second], ok=False)
        self.assemble([first, first, second], ok=False)
        self.assemble([first, second]); self.deliver()

    def test_extra_boundary_gate_survives_stage_transition(self):
        fake = self.h.root / 'bin/just'
        fake.write_text(fake.read_text().replace('gate-core gate-full env-facts fmt gate-demo', 'gate-core gate-full env-facts fmt gate-demo gate-extra').replace('["gate-core","gate-demo"]', '["gate-core","gate-demo","gate-extra"]'))
        self.commit(); self.gate(); self.gate('gate-demo'); self.gate('gate-extra')
        self.implement(required_boundary_gates=['gate-demo', 'gate-extra'])
        self.assemble([self.review(blocking=True)], 'code_failure'); self.stage('repair')
        self.assertIn('gate-extra', json.loads(self.wd.read_text())['required_boundary_gates'])
        self.commit(); self.gate(); self.gate('gate-demo')
        self.implement(ok=False)

    def test_extra_boundary_gate_survives_same_stage_resume(self):
        fake = self.h.root / 'bin/just'
        fake.write_text(fake.read_text().replace('gate-core gate-full env-facts fmt gate-demo', 'gate-core gate-full env-facts fmt gate-demo gate-extra').replace('["gate-core","gate-demo"]', '["gate-core","gate-demo","gate-extra"]'))
        self.commit()
        self.implement('interrupted', required_boundary_gates=['gate-demo', 'gate-extra'])
        self.gate(); self.gate('gate-demo')
        self.implement(ok=False)
        self.gate('gate-extra')
        self.implement()
        self.assemble([self.review()])
        self.deliver()
        self.assertIn('gate-extra', json.loads(self.writer_report.read_text())['required_boundary_gates'])

    def test_delivery_gates_cannot_mix_gate_plan_definitions(self):
        self.commit(); self.gate()
        fake = self.h.root / 'bin/just'
        fake.write_text(fake.read_text().replace('["gate-core","gate-demo"]', '["gate-core","gate-demo","gate-extra"]').replace('fmt gate-demo', 'fmt gate-demo gate-extra'))
        self.gate('gate-demo')
        self.implement(ok=False)

    def test_review_prepare_interruption_reuses_reserved_round(self):
        self.ready_writer()
        code = '''import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import review_operations
o = review_operations
original = review_operations.evidence.write
def fail(path, value):
    if Path(path).name == 'round.json': raise OSError('模拟 round 写出前中断')
    return original(path, value)
review_operations.evidence.write = fail
o.prepare_review(SimpleNamespace(dispatch=sys.argv[2], evidence=None, resume=False))
'''
        failed = subprocess.run([sys.executable, '-B', '-c', code, str(SCRIPTS), str(self.sd)],
                                text=True, capture_output=True, env=self.h.env)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('模拟 round 写出前中断', failed.stderr)
        before = set(self.sd.parent.glob('review-*'))
        resumed = self.cli('executor-operations.py', 'review-prepare', '--dispatch', self.sd, '--resume')
        self.assertEqual(set(self.sd.parent.glob('review-*')), before)
        self.assertEqual(Path(resumed['round_path']).parent, next(iter(before)))

    def test_missing_log_can_deliver_partial_blocked_implementation(self):
        self.commit(); self.gate()
        log = next(self.wd.parent.glob('verification-*/output.log'))
        log.unlink()
        self.implement('blocked')
        report = json.loads(self.writer_report.read_text())
        self.assertEqual(report['outcome'], 'blocked')
        self.assertTrue(report['verification_issues'])
        self.assemble(outcome='blocked'); self.deliver()

    def test_same_head_review_correction_keeps_stage_and_original(self):
        self.ready_writer()
        first = self.review(blocking=True)
        self.assemble([first], 'code_failure')
        original = self.stage_report.read_bytes()
        collection = json.loads(first.read_text())
        selection = {}
        for axis, fields in collection['sources'].items():
            path = Path(fields['report']['path'])
            report = json.loads(path.read_text()); report['findings'] = []
            target = self.file('corrected', report, path.parent)
            receipt = self.file('receipt', {'status':'COMPLETED', 'report_path':str(target),
                                           'report_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}, path.parent)
            from test_controller import closure_source
            cp = closure_source(path.parent / 'dispatch.json', target)
            selection[axis] = {'report':str(target), 'receipt':str(receipt), 'closure':json.loads(cp.read_text())['path']}
        selected = self.file('selection', selection)
        target = first.parent / 'collection-corrected.json'
        self.cli('executor-operations.py', 'review-collect', '--round', collection['round']['path'],
                 '--input', selected, '--output', target)
        old_report = self.stage_report
        self.deliver(ok=False)
        self.stage('repair', ok=False)
        self.assemble([first], 'code_failure', ok=False)
        self.assemble([target]); self.deliver()
        self.assertEqual(old_report.read_bytes(), original)
        self.assertEqual(json.loads(self.stage_report.read_text())['stage'], 0)

    def test_model_upgrade_inherits_and_downgrade_is_rejected(self):
        self.ready_writer(); self.assemble([self.review(blocking=True)], 'code_failure')
        upgraded = {'model':'gpt-5.6-sol', 'reasoning_effort':'medium'}
        self.stage('repair', model_overrides={'implementer':upgraded}, model_override_reason='契约分歧')
        self.ready_writer(); reviews = json.loads(self.sd.read_text())['prior_reviews']
        current = self.review(blocking=True)
        self.assemble([Path(item['path']) for item in reviews] + [current], 'code_failure')
        self.stage('repair', ok=False, model_overrides={'implementer':{'model':'gpt-5.6-terra','reasoning_effort':'medium'}}, model_override_reason='不应降档')
        self.stage('repair')
        self.assertEqual(self.stage_info['models']['implementer'], upgraded)

    def test_root_inspect_after_resume_accepts_original_dirty_stage(self):
        e = review_fixture.ExecutorOperationsTests(); e.h = self.h
        e.context_fixture()
        (self.h.wt / 'unfinished.txt').write_text('保留')
        self.implement('interrupted'); self.assemble(outcome='interrupted')
        result = self.cli('executor-operations.py', 'inspect', '--dispatch', self.root_dispatch)
        self.assertIn('unfinished.txt', result['workspace']['untracked'])

    def test_old_writer_cannot_prepare_commit_after_review(self):
        self.ready_writer(); self.assemble([self.review()])
        (self.h.wt / 'after.txt').write_text('禁止提交')
        self.h.h.git(self.h.wt, 'add', 'after.txt')
        self.cli('executor-operations.py', 'check-layer', '--dispatch', self.wd,
                 '--input', self.file('layer', {'files':['after.txt'], 'message':'test-1 不应通过'}), ok=False)

    def test_sealed_gate_failure_cannot_be_replaced_with_interruption(self):
        self.commit(); failure = self.gate(fail=True)
        for _ in range(3):
            self.cli('executor-operations.py', 'begin-gate-repair', '--dispatch', self.wd, '--failure', failure)
            failure = self.gate(fail=True)
        self.implement('code_failure'); self.assemble(outcome='code_failure')
        self.implement('interrupted', accept=False)
        self.cli('executor-operations.py', 'implementer-accept', '--dispatch', self.sd,
                 '--report', self.writer_report, '--receipt', self.writer_receipt, ok=False)
        self.assemble(outcome='interrupted', ok=False)
        self.stage(ok=False)
        self.stage('repair')

    def test_completion_includes_stage_models_and_gate_lower_bound(self):
        self.ready_writer(); self.assemble([self.review()]); self.deliver()
        path = self.root_dispatch.parent / 'completion.md'
        self.cli('controller.py', 'comment', '--acceptance', self.acceptance,
                 '--summary', '完成', '--output', path)
        text = path.read_text()
        self.assertIn('交付阶段：0', text)
        self.assertIn('implementer', text)
        self.assertIn('Boundary gates：', text)
        self.assertIn('gate-demo', text)

    def test_six_gate_failure_stages_stop_at_limit(self):
        for stage in range(6):
            self.commit(); failure = self.gate(fail=True)
            for _ in range(3):
                self.cli('executor-operations.py', 'begin-gate-repair', '--dispatch', self.wd, '--failure', failure)
                self.commit(); failure = self.gate(fail=True)
            self.implement('code_failure'); self.assemble(outcome='code_failure')
            if stage < 5:
                self.stage('repair')
        self.deliver(); self.stage('repair', ok=False)

    def test_same_head_external_gate_retry_does_not_consume_repairs(self):
        self.commit(); self.gate(fail=True)
        self.implement('blocked'); self.assemble(outcome='blocked')
        old = self.wd; self.stage()
        self.assertEqual(self.wd, old)
        self.gate(); self.gate('gate-demo'); self.implement()
        self.assemble([self.review()]); self.deliver()
        self.assertFalse(list(Path(json.loads(self.wd.read_text())['gate_repair_root']).glob('gate-repair*.json')))

    def test_existing_behavior_review_failure_restores_tdd_in_next_stage(self):
        self.h.prepare(mode='new', test_mode='TDD', approved_seams=['S1'], required_boundary_gates=['gate-demo'])
        self.root_dispatch = self.h.dispatch; self.stage()
        def adapt(mode):
            result = self.cli('executor-operations.py', 'ticket-adapt-plan', '--dispatch', self.sd, '--input',
                self.file('adapt', {'mode':mode, 'reason':'按已核实行为调整验证策略',
                    'acceptance':[{'criterion':'目标行为','evidence':'BASE 与审查事实'}],
                    'verification':[{'command':'just test','result':'实际结果与判断依据'}], 'boundary_gates':['gate-demo']}))
            self.sd, self.wd = Path(result['stage_dispatch']), Path(result['implementer_dispatch'])
        adapt('direct_verification')
        self.gate(); self.gate('gate-demo'); self.implement()
        first = self.review(blocking=True); self.assemble([first], 'code_failure')
        self.stage('repair'); adapt('TDD')
        self.assertEqual(json.loads(self.wd.read_text())['approved_seams'], ['S1'])
        self.ready_writer(); self.assemble([first, self.review()]); self.deliver()
        self.assertEqual(json.loads(self.root_report.read_text())['test_plan']['mode'], 'TDD')

    def test_root_cannot_use_plan_adapter_to_create_another_stage_budget(self):
        self.h.prepare(mode='new', test_mode='TDD', approved_seams=['S1'], required_boundary_gates=['gate-demo'])
        self.root_dispatch = self.h.dispatch; self.stage()
        facts = self.file('adapt-root', {'mode':'direct_verification', 'reason':'BASE 已满足',
            'acceptance':[{'criterion':'目标行为','evidence':'BASE 验证'}],
            'verification':[{'command':'just test','result':'通过'}], 'boundary_gates':['gate-demo']})
        self.cli('controller.py', 'adapt-plan', '--dispatch', self.root_dispatch, '--input', facts, ok=False)
        self.assertEqual(self.stage()['stage'], 0)


if __name__ == '__main__':
    unittest.main()

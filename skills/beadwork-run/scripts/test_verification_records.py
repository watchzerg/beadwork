"""固定快照、部分损坏交付与线性读取的回归。"""
import copy
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

import evidence
import ticket_verification
import verification_records


class VerificationRecordTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.dispatch = self.root / 'dispatch.json'
        self.d = dict(role='implementer', ticket_execution_version=1,
                      dispatch_path=str(self.dispatch), report_path=str(self.root / 'report.json'),
                      worktree=str(self.root), verification_dispatches=[])
        evidence.write(self.dispatch, self.d)

    def run_record(self, number):
        folder = self.root / f'verification-{number:04}'
        folder.mkdir()
        evidence.write(folder / 'started.json', dict(
            dispatch_path=str(self.dispatch), dispatch_sha256=evidence.digest(self.dispatch),
            cwd=str(self.root), started_ns=number, argv=['just', '--one', '--', 'gate-core'],
            before={'head': 'a' * 40, 'status': ''}))
        return folder

    def test_collect_reads_each_record_once_without_directory_scan(self):
        for number in range(80):
            self.run_record(number)
        snapshot = ticket_verification.verification_snapshot(self.d)
        with patch.object(Path, 'glob', side_effect=AssertionError('固定快照不应重新扫描')), patch.object(
                verification_records, 'read', wraps=verification_records.read) as reads:
            rows, issues = ticket_verification.collect_verification(self.d, snapshot, {}, 'BLOCKED')
        self.assertEqual((len(rows), len(issues), reads.call_count), (80, 0, 80))

    def test_missing_and_truncated_started_preserve_other_records(self):
        good = self.run_record(0)
        missing = self.run_record(1)
        truncated = self.run_record(2)
        (missing / 'started.json').unlink()
        (truncated / 'started.json').write_text('{')
        snapshot = ticket_verification.verification_snapshot(self.d)
        rows, issues = ticket_verification.collect_verification(self.d, snapshot, {}, 'BLOCKED')
        self.assertEqual(len(rows), 1)
        self.assertIn(str(good), rows[0]['result'])
        self.assertEqual([item['source']['directory'] for item in issues], [str(missing), str(truncated)])
        self.assertIsNone(issues[0]['source']['started'])
        self.assertIsNotNone(issues[1]['source']['started'])

    def test_bound_source_changes_are_issues_and_missing_source_reappearance_changes_reason(self):
        folder = self.run_record(0)
        snapshot = ticket_verification.verification_snapshot(self.d)
        (folder / 'started.json').write_text('{}')
        _, issues = ticket_verification.collect_verification(self.d, snapshot, {}, 'BLOCKED')
        self.assertIn('证据文件已变化', issues[0]['reason'])
        (folder / 'started.json').unlink()
        missing = ticket_verification.verification_snapshot(self.d)
        _, before = ticket_verification.collect_verification(self.d, missing, {}, 'BLOCKED')
        (folder / 'started.json').write_text('{}')
        _, after = ticket_verification.collect_verification(self.d, missing, {}, 'BLOCKED')
        self.assertNotEqual(before, after)

    def test_foreign_duplicate_and_moved_binding_cannot_be_partial_issues(self):
        self.run_record(0)
        snapshot = ticket_verification.verification_snapshot(self.d)
        invalid = copy.deepcopy(snapshot)
        invalid[0]['directory'] = str(self.root / 'foreign' / 'verification-0')
        invalid[0]['started'] = None
        moved = copy.deepcopy(snapshot)
        moved[0]['started']['path'] = str(self.root / 'started.json')
        for selected in (snapshot * 2, invalid, moved):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                ticket_verification.collect_verification(self.d, selected, {}, 'BLOCKED')

    def test_historical_snapshot_does_not_discover_new_runs_or_terminal_results(self):
        folder = self.run_record(0)
        snapshot = ticket_verification.verification_snapshot(self.d)
        before = ticket_verification.collect_verification(self.d, snapshot, {}, 'BLOCKED')
        self.run_record(1)
        evidence.write(folder / 'result.json', {'invalid': '快照之后新增的终态'})
        self.assertEqual(ticket_verification.collect_verification(self.d, snapshot, {}, 'BLOCKED'), before)
        self.assertNotEqual(ticket_verification.verification_snapshot(self.d), snapshot)

    def test_unknown_notes_are_rejected(self):
        self.run_record(0)
        with self.assertRaisesRegex(ValueError, '未收集'):
            ticket_verification.collect_verification(self.d, ticket_verification.verification_snapshot(self.d),
                                                    {'/unknown': '已收尾'}, 'BLOCKED')


if __name__ == '__main__':
    main()

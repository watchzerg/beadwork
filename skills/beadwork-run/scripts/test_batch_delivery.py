"""公开 push/cleanup 入口：本地 bare remote、部分失败与显式跳过。"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import evidence
import test_controller as fixture


class BatchDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.ControllerTests(); self.h.setUp(); self.addCleanup(self.h.doCleanups)
        self.h.ready(); self.h.merge()
        self.remote = self.h.root / 'remote.git'
        self.h.h.git(self.h.root, 'init', '--bare', str(self.remote))
        self.h.h.git(self.h.primary, 'remote', 'add', 'origin', str(self.remote))
        binary = self.h.root / 'bin/bd'
        original = binary.read_text()
        original = original.replace("assert a[0] in ('show','comments'), a", '''
if a[:2]==['dolt','push']:
 root=Path(os.environ['BD_FIXTURE_SHOW']).parent
 with (root/'beads-pushes.log').open('a') as f: f.write((root/'comments.json').read_text()+'\\n')
 sys.exit(1 if (root/'fail-beads').exists() else 0)
assert a[0] in ('show','comments'), a''')
        binary.write_text(original)
        self.serial = 0

    def push(self, policy=None, ok=True):
        self.serial += 1
        request = self.h.root / f'push-{self.serial}.json'
        self.h.put(request, {'merge_record': evidence.binding(self.h.merge_record),
                            'policy': policy or {'git': {'action': 'push'}, 'beads': {'action': 'push'}}})
        return self.h.call('push', '--input', request, ok=ok)

    def test_push_readback_and_cleanup(self):
        result = self.push()
        self.assertEqual(result['git']['remote_head'], self.h.h.head)
        self.assertEqual([x['name'] for x in result['commands']], ['git-push', 'git-readback', 'beads-push'])
        self.assertEqual(self.h.h.git(self.remote, 'rev-parse', 'main'), self.h.h.head)
        path = result['delivery_result']['path']
        for _ in range(2):
            self.h.call('cleanup', '--merge-record', self.h.merge_record, '--delivery-result', path)
        self.assertFalse(self.h.wt.exists())

    def test_beads_failure_preserves_checkout_and_retry_pushes_new_comments(self):
        failure = self.h.root / 'fail-beads'; failure.touch()
        self.push(ok=False)
        self.assertTrue(self.h.wt.exists())
        self.assertEqual(self.h.h.git(self.remote, 'rev-parse', 'main'), self.h.h.head)
        records = list((self.h.primary / '.worktrees/.evidence/test/delivery').glob('*/result.json'))
        failed = next(p for p in records if not json.loads(p.read_text())['ready'])
        self.h.call('cleanup', '--merge-record', self.h.merge_record, '--delivery-result', failed, ok=False)
        self.h.put(self.h.root / 'comments.json', [{'id': 8, 'text': '新增停止记录'}])
        failure.unlink(); self.push()
        lines = (self.h.root / 'beads-pushes.log').read_text().splitlines()
        self.assertEqual(len(lines), 2); self.assertIn('新增停止记录', lines[-1])

    def test_git_failure_does_not_push_beads(self):
        self.h.h.git(self.h.primary, 'remote', 'set-url', 'origin', str(self.h.root / 'missing.git'))
        self.push(ok=False)
        self.assertFalse((self.h.root / 'beads-pushes.log').exists())

    def test_mismatched_readback_does_not_push_beads(self):
        # 本地 receive hook 在推送成功后移动远端 ref，验证真实读回比较。
        hook = self.remote / 'hooks/post-receive'
        hook.write_text('#!/bin/sh\ngit update-ref refs/heads/main ' + self.h.h.base + '\n')
        hook.chmod(0o755)
        self.push(ok=False)
        self.assertFalse((self.h.root / 'beads-pushes.log').exists())

    def test_explicit_skip_combinations_and_missing_reason(self):
        for skipped in (('git',), ('beads',), ('git', 'beads')):
            policy = {key: {'action': 'skip', 'reason': '用户限制'} if key in skipped else {'action': 'push'}
                      for key in ('git', 'beads')}
            result = self.push(policy)
            self.assertTrue(result['ready'])
            for key in skipped: self.assertEqual(result[key]['status'], 'skipped')
        self.push({'git': {'action': 'skip'}, 'beads': {'action': 'push'}}, ok=False)

    def test_missing_or_tampered_delivery_cannot_clean(self):
        raw = subprocess.run([sys.executable, '-B', str(fixture.SCRIPT), 'cleanup',
                              '--merge-record', str(self.h.merge_record)], env=self.h.env, capture_output=True)
        self.assertNotEqual(raw.returncode, 0); self.assertTrue(self.h.wt.exists())
        result = self.push(); path = Path(result['delivery_result']['path'])
        value = json.loads(path.read_text()); value['merge_record']['sha256'] = '0' * 64
        path.write_text(json.dumps(value))
        self.h.call('cleanup', '--merge-record', self.h.merge_record, '--delivery-result', path, ok=False)
        self.assertTrue(self.h.wt.exists())


if __name__ == '__main__': unittest.main()

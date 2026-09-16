"""证据基础层的严格读取、绑定与不可覆盖发布。"""
import json
from pathlib import Path
import tempfile
import unittest

import evidence


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_strict_read_and_binding(self):
        path = self.root / 'value.json'
        evidence.write(path, {'value': '事实'})
        self.assertEqual(evidence.read(path), {'value': '事实'})
        self.assertEqual(evidence.bound(evidence.binding(path)), path)
        path.write_text('{"value":"改变"}')
        with self.assertRaisesRegex(ValueError, '已变化'):
            evidence.bound({'path': str(path), 'sha256': '0' * 64})

    def test_write_never_overwrites_published_file(self):
        path = self.root / 'value.json'
        evidence.write(path, {'version': 1})
        original = path.read_bytes()
        with self.assertRaises(FileExistsError):
            evidence.write(path, {'version': 2})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(self.root.glob('.*.pending-*')), [])

    def test_serialization_failure_does_not_publish_target(self):
        path = self.root / 'value.json'
        with self.assertRaises(TypeError):
            evidence.write(path, {'bad': object()})
        self.assertFalse(path.exists())
        self.assertEqual(list(self.root.glob('.*.pending-*')), [])

    def test_rejects_duplicate_keys_nonfinite_and_symlink_paths(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                evidence.loads(raw)
        real = self.root / 'real'; real.mkdir()
        alias = self.root / 'alias'; alias.symlink_to(real, target_is_directory=True)
        target = alias / 'file.json'; (real / 'file.json').write_text(json.dumps({'a': 1}))
        with self.assertRaisesRegex(ValueError, 'symlink'):
            evidence.absolute(target)


if __name__ == '__main__':
    unittest.main()

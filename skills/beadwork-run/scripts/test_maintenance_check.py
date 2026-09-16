import tempfile
from pathlib import Path
import unittest

import maintenance_check


class MaintenanceCheckTests(unittest.TestCase):
    def test_local_link_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "docs").mkdir(); (root / "skills").mkdir()
            (root / "docs/target.md").write_text("目标")
            source = root / "docs/source.md"; source.write_text("[有效](target.md) [外部](https://example.com)")
            self.assertEqual(maintenance_check.local_links(root), [])
            source.write_text("[断裂](missing.md)")
            self.assertEqual(maintenance_check.local_links(root), [{"source": "docs/source.md", "target": "missing.md"}])


if __name__ == "__main__": unittest.main()

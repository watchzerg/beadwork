"""tracker intent 的读回协调与重入测试。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import evidence
import tracker_operations as tracker


class TrackerOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.state = self.root / "state.json"
        self.state.write_text(json.dumps({"issue": {"id": "demo-1", "status": "open", "assignee": None}, "comments": []}))
        binary = self.root / "bd"
        binary.write_text("#!" + sys.executable + "\n" + '''import json, os, sys
from pathlib import Path
p=Path(os.environ['TRACKER_STATE']); s=json.loads(p.read_text()); a=sys.argv[1:]
if a[0]=='show': print(json.dumps([s['issue']]))
elif a[0]=='comments' and a[1]!='add': print(json.dumps(s['comments']))
elif a[:2]==['update','demo-1']:
 s['issue'].update(status='in_progress',assignee='fixture'); p.write_text(json.dumps(s)); print('{}')
elif a[:2]==['comments','add']:
 body=Path(a[a.index('-f')+1]).read_text(); s['comments'].append({'id':len(s['comments'])+1,'text':body}); p.write_text(json.dumps(s)); print('{}')
elif a[:2]==['close','demo-1']:
 s['issue']['status']='closed'; p.write_text(json.dumps(s)); print('{}')
else: print(json.dumps({'bad':a})); sys.exit(2)
''')
        binary.chmod(0o755)
        self.old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(self.root) + os.pathsep + self.old_path
        os.environ["TRACKER_STATE"] = str(self.state)
        self.addCleanup(lambda: os.environ.__setitem__("PATH", self.old_path))

    def intent(self, kind, **extra):
        source = self.root / (kind + "-input.json")
        source.write_text(json.dumps({"repository_root": str(self.root), "parent_id": "demo-1",
                                      "issue_id": "demo-1", "kind": kind, **extra}))
        target = self.root / (kind + "-intent.json")
        tracker.prepare(source, target)
        return target

    def test_claim_and_result_reuse(self):
        path = self.intent("claim", expected_assignee="fixture")
        first = tracker.execute(path); second = tracker.execute(path)
        self.assertEqual(first, second)
        self.assertEqual(first["after"]["status"], "in_progress")

    def test_existing_foreign_claim_is_not_adopted(self):
        state = json.loads(self.state.read_text()); state["issue"].update(status="in_progress", assignee="other")
        self.state.write_text(json.dumps(state))
        with self.assertRaises(ValueError):
            tracker.execute(self.intent("claim", expected_assignee="fixture"))

    def test_comment_marker_prevents_duplicate_after_lost_local_result(self):
        path = self.intent("comment", body="阶段完成")
        first = tracker.execute(path)
        self.assertEqual(first['comment_id'], '1')
        self.assertEqual(first, tracker.execute(path))
        path.with_name(path.stem + "-result.json").unlink()
        result = tracker.execute(path)
        self.assertTrue(result["already_applied"])
        self.assertEqual(result['comment_id'], first['comment_id'])
        self.assertEqual(len(json.loads(self.state.read_text())["comments"]), 1)

    def test_duplicate_marker_and_missing_id_are_rejected(self):
        path = self.intent('comment', body='发布')
        tracker.execute(path)
        result_path = path.with_name(path.stem + '-result.json')
        result_path.unlink()
        state = json.loads(self.state.read_text())
        original = state['comments'][0]
        for rows in ([original, dict(original, id=2)], [{'text': original['text']}]):
            state['comments'] = rows; self.state.write_text(json.dumps(state))
            with self.assertRaises(ValueError): tracker.execute(path)
            self.assertFalse(result_path.exists())

    def test_close_requires_bound_prerequisite_and_reads_back(self):
        report = self.root / "accepted.json"; evidence.write(report, {"kind": "mechanical_acceptance"})
        path = self.intent("close", reason="完成", prerequisite=evidence.binding(report))
        self.assertEqual(tracker.execute(path)["after"]["status"], "closed")
        with self.assertRaises(ValueError):
            self.intent("close", reason="完成")


if __name__ == "__main__":
    unittest.main()

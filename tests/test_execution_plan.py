"""串行计划公开 CLI 与可变 tracker fixture；覆盖排序、漂移、发布及恢复。"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import evidence
import execution_plan as plans
import tracker_operations as tracker

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts"

pytestmark = pytest.mark.integration


class ExecutionPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.env = dict(
            os.environ,
            BEADS_ACTOR="fixture",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.com",
            GIT_COMMITTER_NAME="Test",
            GIT_COMMITTER_EMAIL="test@example.com",
        )
        for args in (["init", "-b", "main"], ["commit", "--allow-empty", "-m", "fixture"]):
            subprocess.run(
                ["git", *args], cwd=self.root, env=self.env, check=True, capture_output=True
            )
        self.order = ["p-1.2", "p-1.17", "p-1.20"]
        self.value = {"ticket_order": self.order}
        self.state: dict[str, Any] = {
            "parent": {
                "id": "p-1",
                "status": "open",
                "description": plans.replace("保留正文", self.value),
            },
            "children": [
                {"id": x, "status": "open", "labels": ["ready-for-agent"]} for x in self.order
            ],
            "deps": {},
            "ready": list(reversed(self.order)),
            "writes": [],
        }
        self.state_path = self.root / "state.json"
        self.save()
        binary = self.root / "bd"
        binary.write_text(
            "#!"
            + sys.executable
            + "\n"
            + """import json,os,sys
from pathlib import Path
p=Path(os.environ['PLAN_STATE']);s=json.loads(p.read_text());a=sys.argv[1:]
if a[0]=='show': print(json.dumps([s['parent']] if a[1]==s['parent']['id'] else [x for x in s['children'] if x['id']==a[1]]))
elif a[0]=='list': print(json.dumps(s['children']))
elif a[:2]==['dep','list']:
 print(json.dumps([] if '--type=parent-child' in a else [{'id':x} for x in s['deps'].get(a[2],[])]))
elif a[0]=='ready':
 print(json.dumps([x for i in s['ready'] for x in s['children'] if x['id']==i and x['status']=='open' and not x.get('assignee')]))
elif a[0]=='update':
 if '--body-file' in a: s['parent']['description']=Path(a[a.index('--body-file')+1]).read_text()
 else:
  x=next(x for x in s['children'] if x['id']==a[1]);x.update(status='in_progress',assignee=a[a.index('--actor')+1])
 s['writes'].append(a);p.write_text(json.dumps(s));print('{}')
elif a[0]=='close':
 next(x for x in s['children'] if x['id']==a[1])['status']='closed';s['writes'].append(a);p.write_text(json.dumps(s));print('{}')
else: raise AssertionError(a)
"""
        )
        binary.chmod(0o755)
        self.env.update(
            PATH=str(self.root) + os.pathsep + self.env["PATH"], PLAN_STATE=str(self.state_path)
        )
        self.patch = patch.dict(os.environ, self.env)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        source = self.root / "approved.json"
        evidence.write(source, self.value)
        self.binding = plans.adopt(
            self.root,
            "p-1",
            self.value,
            self.state["children"],
            [evidence.binding(source)],
            "测试批准",
        )

    def save(self):
        self.state_path.write_text(json.dumps(self.state))

    def call(self, script, *args, ok=True):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "beadwork.py"), script, *map(str, args)],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def next(self):
        return self.call("graph", "next", "p-1", *self.order)

    def intent(self, name, ticket=None, kind="claim", **extra):
        source = self.root / (name + "-input.json")
        target = self.root / (name + ".json")
        evidence.write(
            source,
            dict(
                repository_root=str(self.root),
                parent_id="p-1",
                issue_id=ticket or self.order[0],
                kind=kind,
                **extra,
            ),
        )
        tracker.prepare(source, target)
        return target

    def test_claim_fixes_actor_before_environment_changes(self):
        intent = self.intent("claim")
        self.assertEqual(evidence.read(intent)["assignee_source"], "BEADS_ACTOR")
        with patch.dict(os.environ, BEADS_ACTOR="different-actor"):
            tracker.execute(intent)
            tracker.execute(intent)
        state = evidence.read(self.state_path)
        self.assertEqual(state["children"][0]["assignee"], "fixture")
        self.assertEqual(len(state["writes"]), 1)
        state["children"][0]["assignee"] = "another-owner"
        self.state_path.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "活动票归属不同"):
            tracker.execute(intent)
        self.assertEqual(len(evidence.read(self.state_path)["writes"]), 1)

    def test_claim_identity_uses_git_name_and_rejects_manual_input(self):
        for key, value in (("user.name", "Git Owner"), ("user.email", "different@example.com")):
            subprocess.run(
                ["git", "config", key, value],
                cwd=self.root,
                env=self.env,
                check=True,
                capture_output=True,
            )
        with patch.dict(os.environ):
            os.environ.pop("BEADS_ACTOR", None)
            intent = self.intent("git-claim")
        self.assertEqual(evidence.read(intent)["expected_assignee"], "Git Owner")
        self.assertEqual(evidence.read(intent)["assignee_source"], "git user.name")
        tracker.execute(intent)
        self.assertEqual(evidence.read(self.state_path)["children"][0]["assignee"], "Git Owner")
        with self.assertRaisesRegex(ValueError, "输入字段无效"):
            self.intent("manual", expected_assignee="different@example.com")
        with patch.dict(os.environ, BEADS_ACTOR="   "):
            with self.assertRaisesRegex(ValueError, "缺少领取身份"):
                self.intent("empty")
        self.assertFalse((self.root / "empty.json").exists())

    def test_next_blocked_never_skips_to_ready_later(self):
        self.state["ready"] = self.order[1:]
        self.save()
        self.assertEqual(self.next()["reason"], "next_ticket_not_ready")


if __name__ == "__main__":
    unittest.main()

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
  x=next(x for x in s['children'] if x['id']==a[1]);x.update(status='in_progress',assignee='fixture')
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
                expected_assignee="fixture",
                **extra,
            ),
        )
        tracker.prepare(source, target)
        return target

    def test_numeric_id_and_priority_do_not_override_order(self):
        self.assertEqual(self.next(), {"next": "claim", "ticket_id": self.order[0]})

    def test_next_blocked_never_skips_to_ready_later(self):
        self.state["ready"] = self.order[1:]
        self.save()
        self.assertEqual(self.next()["reason"], "next_ticket_not_ready")

    def test_missing_plan_never_falls_back(self):
        self.state["parent"]["description"] = "没有计划"
        self.save()
        self.assertEqual(self.next()["next"], "blocked")

    def test_invalid_dependency_and_scope(self):
        self.state["deps"][self.order[0]] = [self.order[1]]
        self.save()
        self.assertIn("违反依赖", self.next()["detail"])
        self.state["deps"] = {}
        self.state["children"].pop()
        self.save()
        self.assertEqual(self.next()["next"], "blocked")

    def test_formatting_and_unrelated_parent_changes_are_allowed(self):
        self.state["parent"]["description"] = (
            "新说明\n"
            + plans.START
            + "\n```json\n"
            + json.dumps(self.value)
            + "\n```\n"
            + plans.END
        )
        self.save()
        self.assertEqual(self.next()["next"], "claim")

    def test_reorder_requires_explicit_adoption_and_keeps_history(self):
        new = {"ticket_order": list(reversed(self.order))}
        self.state["parent"]["description"] = plans.replace("正文", new)
        self.save()
        self.assertEqual(self.next()["next"], "blocked")
        source = self.root / "reorder.json"
        evidence.write(
            source,
            dict(
                repository_root=str(self.root),
                parent_id="p-1",
                **new,
                previous=self.binding,
                reason="批准剩余票重排",
            ),
        )
        result = self.call("plan", "adopt", "--input", source)
        self.assertNotEqual(result, self.binding)
        evidence.bound(self.binding)
        self.assertEqual(self.next()["ticket_id"], self.order[-1])
        self.assertEqual(self.call("plan", "adopt", "--input", source), result)

    def test_claim_guard_and_stale_intent(self):
        path = self.intent("wrong", self.order[-1])
        with self.assertRaisesRegex(ValueError, "下一张票"):
            tracker.execute(path)
        self.assertEqual(json.loads(self.state_path.read_text())["writes"], [])
        good = self.intent("good")
        tracker.execute(good)
        tracker.execute(good)
        self.assertEqual(self.next()["next"], "resume")
        with self.assertRaisesRegex(ValueError, "原始领取 intent"):
            tracker.execute(self.intent("imposter"))

    def test_reopened_completed_ticket_blocks(self):
        claim = self.intent("start")
        tracker.execute(claim)
        report = self.root / "accepted.json"
        evidence.write(report, {"status": "DONE"})
        close = self.intent(
            "close", kind="close", reason="已验收", prerequisite=evidence.binding(report)
        )
        tracker.execute(close)
        self.assertEqual(self.next()["ticket_id"], self.order[1])
        self.state = json.loads(self.state_path.read_text())
        self.state["children"][0]["status"] = "open"
        self.save()
        self.assertIn("重新打开", self.next()["detail"])

    def test_publish_preserves_body_and_detects_concurrent_edit(self):
        source = self.root / "publish-input.json"
        evidence.write(
            source,
            dict(
                repository_root=str(self.root),
                parent_id="p-1",
                ticket_order=list(reversed(self.order)),
            ),
        )
        intent = self.root / "publish.json"
        self.call("plan", "prepare", "--input", source, "--output", intent)
        self.call("plan", "publish", "--intent", intent)
        intent.with_name(intent.stem + "-result.json").unlink()
        self.call("plan", "publish", "--intent", intent)
        state = json.loads(self.state_path.read_text())
        self.assertEqual(len(state["writes"]), 1)
        self.assertTrue(state["parent"]["description"].startswith("保留正文"))
        self.assertEqual(state["parent"]["status"], "open")
        state["parent"]["description"] += "\n人工编辑"
        self.state = state
        self.save()
        self.assertIn(
            "正文已变化",
            self.call("plan", "publish", "--intent", intent, ok=False)["error"],
        )

    def test_active_and_closed_tickets_cannot_be_moved(self):
        self.state["children"][0]["status"] = "closed"
        self.save()
        new = {"ticket_order": list(reversed(self.order))}
        self.state["parent"]["description"] = plans.replace("", new)
        self.save()
        source = self.root / "reorder-protected.json"
        evidence.write(
            source,
            dict(
                repository_root=str(self.root),
                parent_id="p-1",
                **new,
                previous=self.binding,
                reason="错误移动已关闭票",
            ),
        )
        self.assertIn(
            "不得移动",
            self.call("plan", "adopt", "--input", source, ok=False)["error"],
        )
        self.state["children"][0]["status"] = "open"
        self.state["children"][1]["status"] = "in_progress"
        self.state["parent"]["description"] = plans.replace("", self.value)
        self.save()
        self.assertIn("活动票", self.next()["detail"])

    def test_plan_adoption_invalidates_prepared_claim(self):
        intent = self.intent("stale")
        new = {"ticket_order": [self.order[0], self.order[2], self.order[1]]}
        self.state["parent"]["description"] = plans.replace("", new)
        self.save()
        source = self.root / "reorder-claim.json"
        evidence.write(
            source,
            dict(
                repository_root=str(self.root),
                parent_id="p-1",
                **new,
                previous=self.binding,
                reason="批准重排未开始部分",
            ),
        )
        self.call("plan", "adopt", "--input", source)
        with self.assertRaisesRegex(ValueError, "选择已变化"):
            tracker.execute(intent)
        self.assertEqual(json.loads(self.state_path.read_text())["writes"], [])

    def test_source_tamper_is_not_a_new_plan(self):
        record = evidence.read(evidence.bound(self.binding))
        Path(record["sources"][0]["path"]).write_text("{}")
        self.assertEqual(self.next()["next"], "blocked")

    def test_external_blocker_and_completed_batch(self):
        self.state["deps"][self.order[0]] = ["external-1"]
        self.state["ready"] = self.order[1:]
        self.save()
        self.assertEqual(self.next()["reason"], "next_ticket_not_ready")
        for child in self.state["children"]:
            child["status"] = "closed"
        self.save()
        self.assertEqual(self.next(), {"next": "done"})

    def test_pending_sync_prevents_plan_adoption(self):
        pending = self.root / ".worktrees/.evidence/p-1/main-sync/pending"
        pending.mkdir(parents=True)
        evidence.write(pending / "intent.json", {"pending": True})
        new = {"ticket_order": list(reversed(self.order))}
        self.state["parent"]["description"] = plans.replace("", new)
        self.save()
        source = self.root / "reorder-pending.json"
        evidence.write(
            source,
            dict(
                repository_root=str(self.root),
                parent_id="p-1",
                **new,
                previous=self.binding,
                reason="批准重排",
            ),
        )
        self.assertIn(
            "未完成 main-sync",
            self.call("plan", "adopt", "--input", source, ok=False)["error"],
        )
        self.assertEqual(plans.selected(self.root, "p-1"), self.binding)

    def test_no_adoption_or_migration_without_initial_preflight(self):
        source = self.root / "null-previous.json"
        evidence.write(
            source,
            dict(
                repository_root=str(self.root),
                parent_id="p-1",
                **self.value,
                previous=None,
                reason="不能作为初始化入口",
            ),
        )
        self.assertIn(
            "previous",
            self.call("plan", "adopt", "--input", source, ok=False)["error"],
        )
        with self.assertRaisesRegex(ValueError, "未开工批次"):
            plans.adopt(
                self.root,
                "another-parent",
                {"ticket_order": ["another-1"]},
                [{"id": "another-1", "status": "in_progress"}],
                [evidence.binding(source)],
                "不能导入活动票",
            )

    def test_strict_parser_and_no_version(self):
        for body in (
            "",
            plans.replace("", self.value) * 2,
            plans.START + '\n```json\n{"ticket_order":["x"],"version":1}\n```\n' + plans.END,
            plans.START
            + '\n```json\n{"ticket_order":["x"],"ticket_order":["y"]}\n```\n'
            + plans.END,
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                plans.parse(body)
        with self.assertRaises(ValueError):
            plans.plan({"ticket_order": ["x", "x"]})


if __name__ == "__main__":
    unittest.main()

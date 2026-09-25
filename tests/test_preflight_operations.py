"""真实临时 Git/worktree 下检查采集、语义合并和既有 controller 验收。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import pytest

import evidence
import execution_plan
import test_controller as fixture
import test_verify_phase as phase_fixture

SCRIPT = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"

pytestmark = pytest.mark.workflow


class PreflightOperationsTests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        value = {"ticket_order": ["test-1", "test-2"]}
        approved = self.h.root / "approved-order.json"
        evidence.write(approved, value)
        execution_plan.adopt(
            self.h.primary,
            "test",
            value,
            [{"id": ticket, "status": "open"} for ticket in value["ticket_order"]],
            [evidence.binding(approved)],
            "测试批次首次批准",
        )
        self.h.prepare("preflight", expected_children=["test-1", "test-2"])
        self.h.put(
            self.h.root / "parent.json",
            [
                {
                    "id": "test",
                    "status": "in_progress",
                    "description": execution_plan.replace(
                        "已批准 S1", {"ticket_order": ["test-1", "test-2"]}
                    ),
                }
            ],
        )
        self.h.put(
            self.h.root / "children.json",
            [
                dict(
                    id="test-1", status="open", labels=["ready-for-agent"], description="完整票据"
                ),
                dict(id="test-2", status="closed"),
            ],
        )
        self.h.put(
            self.h.root / "config.json",
            [dict(key="export.auto", value="false"), dict(key="export.git-add", value=False)],
        )
        self.h.put(self.h.root / "edges.json", [])
        bd = self.h.root / "bin/bd"
        bd.write_text(
            "#!"
            + sys.executable
            + "\n"
            + """import json, os, sys
from pathlib import Path
a = sys.argv[1:]
assert '--readonly' in a and '--json' in a, a
root = Path(os.environ['BD_FIXTURE_SHOW']).parent
with (root / 'calls.jsonl').open('a') as f: f.write(json.dumps(a) + '\\n')
name = {'show':'parent', 'list':'children', 'comments':'comments', 'config':'config', 'dep':'edges'}[a[0]]
print('[]' if a[0]=='dep' and '--type=blocks' in a else (root / (name + '.json')).read_text())
"""
        )
        bd.chmod(0o755)
        just = self.h.root / "bin/just"
        just.write_text(
            "#!"
            + sys.executable
            + "\n"
            + "import sys\nif sys.argv[1:] == ['--summary']:\n    print('install test gate-core gate-full')\nelse:\n    raise AssertionError(sys.argv)\n"
        )
        just.chmod(0o755)
        self.draft: dict[str, Any] = dict(
            status="READY",
            plans={"test-1": phase_fixture.PhaseValidatorTests().plan()},
            linked_spec="test",
            resume_evidence=["已有批次记录"],
            sources=["已核对 spec"],
            suggested_route="resume_tickets",
            checks=[
                dict(name=n, passed=True, evidence="已核对语义")
                for n in ("spec_and_test_plans", "recovery")
            ],
            blockers=[],
            remaining_work=[],
        )

    def call(self, command, *args, ok=True):
        p = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "preflight",
                command,
                "--dispatch",
                str(self.h.dispatch),
                *map(str, args),
            ],
            cwd=self.h.root,
            env=self.h.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode == 0, ok, p.stdout + p.stderr)
        return json.loads(p.stdout if ok else p.stderr)

    def collect(self):
        self.facts: dict[str, Any] = self.call("collect")
        return self.facts

    def assemble(self, ok=True, name="report.json"):
        source = self.h.root / "draft.json"
        self.h.put(source, self.draft)
        return self.call(
            "assemble",
            "--facts-sha256",
            self.facts["facts_sha256"],
            "--draft",
            source,
            "--output",
            self.h.dispatch.parent / name,
            ok=ok,
        )

    def test_collect_once_assemble_and_controller_accept(self):
        self.collect()
        calls = [json.loads(x) for x in (self.h.root / "calls.jsonl").read_text().splitlines()]
        self.assertEqual([x[0] for x in calls].count("list"), 1)
        self.assertEqual([x[0] for x in calls].count("show"), 1)
        self.assertEqual(self.facts["pending_ids"], ["test-1"])
        self.assertEqual(self.facts["failed_checks"], [])
        snapshot = json.loads(Path(self.facts["facts_path"]).read_text())
        self.assertEqual(snapshot["recipes"], ["install", "test", "gate-core", "gate-full"])
        receipt = self.assemble()
        self.h.report = self.h.dispatch.parent / "report.json"
        self.h.receipt = self.h.dispatch.parent / "receipt.json"
        self.h.put(self.h.receipt, receipt)
        self.h.accept()
        r = json.loads(self.h.report.read_text())
        self.assertIsNone(r["tickets"][1]["test_plan"])
        timing = json.loads(self.h.report.with_suffix(".timing.json").read_text())
        self.assertEqual(timing["report_sha256"], receipt["report_sha256"])
        self.assertTrue(
            all(
                timing[k] >= 0
                for k in ("collection_seconds", "semantic_and_wait_seconds", "assembly_seconds")
            )
        )
        self.call("collect", ok=False)
        self.assemble(ok=False)


if __name__ == "__main__":
    unittest.main()

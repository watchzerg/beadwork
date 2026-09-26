#!/usr/bin/env python3
"""子 agent 交付回归；仅写临时 JSON 文件，不操作 Git/Beads。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

import evidence
import review_context
import workflow_contract

VERIFIER = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"
A, B = "a" * 40, "b" * 40

pytestmark = pytest.mark.integration


class WorkerDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="worker-delivery-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        stage = self.root / "stage.json"
        evidence.write(stage, {})
        manifest = self.root / "verification-sources.json"
        evidence.write(manifest, [])
        view = self.root / "verification-view.json"
        evidence.write(
            view,
            review_context.build([], B, {}, evidence.binding(stage), evidence.binding(manifest)),
        )
        self.review_context = {
            "scope": "ticket",
            "stage_source": evidence.binding(stage),
            "writer_source": None,
            "verification_view_source": evidence.binding(view),
        }

    def expected(self, role):
        if role == "reviewer":
            return workflow_contract.set_launch_context(
                {
                    "axis": "spec",
                    "reviewed_base": A,
                    "reviewed_head": B,
                    **self.review_context,
                }
            )
        return workflow_contract.set_launch_context(
            {
                "parent_id": "demo-1",
                "branch": "implement/demo-1",
                "base_commit": A,
            }
        )

    def axis(self, blocking=False):
        return {
            "axis": "spec",
            "reviewed_base": A,
            "reviewed_head": B,
            "findings": [
                {
                    "axis": "spec",
                    "kind": "defect",
                    "repair_scope": "code",
                    "blocking": True,
                    "title": "遗漏需求",
                    "evidence": "需求和代码证据",
                }
            ]
            if blocking
            else [],
            "notes": [],
        }

    def fixer(self):
        return {
            "status": "DONE",
            "parent_id": "demo-1",
            "branch": "implement/demo-1",
            "base_commit": A,
            "head_commit": B,
            "fix_commit": B,
            "dispositions": [{"source": "finding.json", "action": "已修复"}],
            "verification": [
                {
                    "gate": "gate-full",
                    "command": "just gate-full",
                    "head_commit": B,
                    "passed": True,
                    "result": "通过",
                    "log_path": "gate-full.log",
                }
            ],
            "worktree_clean": True,
            "stopped_tasks": True,
            "uncommitted_files": [],
            "blockers": [],
            "remaining_work": [],
        }

    def invoke(self, role, report, expected=None, receipt_change=None):
        path, dispatch, receipt = (
            self.root / name for name in ("report.json", "dispatch.json", "receipt.json")
        )
        raw = json.dumps(report, ensure_ascii=False).encode()
        path.write_bytes(raw)
        dispatch.write_text(json.dumps(self.expected(role) if expected is None else expected))
        status = report.get("status", "COMPLETED")
        received = {
            "status": status,
            "report_path": str(path),
            "report_sha256": hashlib.sha256(raw).hexdigest(),
        }
        if receipt_change:
            received.update(receipt_change)
        receipt.write_text(json.dumps(received))
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(VERIFIER),
                "verify",
                "worker",
                "--check-report",
                role,
                str(path),
                str(receipt),
                "--expected",
                str(dispatch),
            ],
            capture_output=True,
            text=True,
        )
        parsed = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0 if parsed["ok"] else 1, result.stderr)
        self.assertEqual(raw, path.read_bytes())
        return parsed

    def reject(self, role, report, check):
        result = self.invoke(role, report)
        self.assertFalse(result["ok"], result)
        self.assertIn(check, result["failures"])

    def test_fixer_success_and_blocked_partial_state(self):
        self.assertTrue(self.invoke("fixer", self.fixer())["ok"])
        report = self.fixer()
        report.update(
            status="BLOCKED",
            fix_commit=None,
            head_commit=None,
            stopped_tasks=False,
            worktree_clean=False,
            uncommitted_files=["src/example.ts"],
            blockers=["验证失败"],
            remaining_work=["保留现场"],
        )
        self.assertTrue(self.invoke("fixer", report)["ok"])
        report["blockers"] = []
        self.reject("fixer", report, "blocked_has_reason")


if __name__ == "__main__":
    unittest.main()

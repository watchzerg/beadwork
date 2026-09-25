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
            return workflow_contract.stamp(
                {
                    "axis": "spec",
                    "reviewed_base": A,
                    "reviewed_head": B,
                    **self.review_context,
                }
            )
        return workflow_contract.stamp(
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

    def test_review_delivery_complete_even_with_blocking_findings(self):
        for blocking in (False, True):
            result = self.invoke("reviewer", self.axis(blocking))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["status"], "COMPLETED")

    def test_finding_classification_is_enforced(self):
        for axis, kind, blocking, valid in (
            ("spec", "smell", False, True),
            ("spec", "smell", True, False),
            ("standards", "documented_standard", True, True),
            ("spec", "documented_standard", True, False),
            ("standards", "documented_standard", False, False),
        ):
            with self.subTest(axis=axis, kind=kind, blocking=blocking):
                report = self.axis(True)
                report["axis"] = axis
                report["findings"][0].update(axis=axis, kind=kind, blocking=blocking)
                expected = {**self.expected("reviewer"), "axis": axis}
                self.assertEqual(self.invoke("reviewer", report, expected=expected)["ok"], valid)

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

    def test_fixer_done_requires_clean_stopped_new_commit(self):
        for key, value, check in (
            ("fix_commit", None, "fix_commit_is_new_delivery_head"),
            ("head_commit", A, "fix_commit_is_new_delivery_head"),
            ("worktree_clean", False, "done_clean_and_stopped"),
            ("stopped_tasks", False, "done_clean_and_stopped"),
            ("uncommitted_files", ["x"], "done_has_no_unfinished_work"),
        ):
            report = self.fixer()
            report[key] = value
            self.reject("fixer", report, check)

    def test_fixer_last_gate_result_wins_and_failed_history_is_preserved(self):
        report = self.fixer()
        failed = {**report["verification"][0], "passed": False, "result": "失败"}
        report["verification"].insert(0, failed)
        self.assertTrue(self.invoke("fixer", report)["ok"])
        report["verification"].append(failed)
        self.reject("fixer", report, "final_validation_on_delivery_head")


if __name__ == "__main__":
    unittest.main()

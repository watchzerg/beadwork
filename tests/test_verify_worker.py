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

VERIFIER = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/verify-worker.py"
A, B = "a" * 40, "b" * 40

pytestmark = pytest.mark.integration


class WorkerDeliveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="worker-delivery-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def expected(self, role):
        if role == "reviewer":
            return {"axis": "spec", "reviewed_base": A, "reviewed_head": B}
        return {
            "parent_id": "demo-1",
            "branch": "implement/demo-1",
            "base_commit": A,
            "required_boundary_gates": ["gate-browser"],
        }

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
            "boundary_gates": ["gate-browser"],
            "gate_sources": [{"gate": "gate-browser", "source": "ticket"}],
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
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(raw, path.read_bytes())
        return json.loads(result.stdout)

    def reject(self, role, report, check):
        result = self.invoke(role, report)
        self.assertFalse(result["ok"], result)
        self.assertIn(check, result["failures"])

    def test_review_delivery_complete_even_with_blocking_findings(self):
        for blocking in (False, True):
            result = self.invoke("reviewer", self.axis(blocking))
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["status"], "COMPLETED")

    def test_review_unavailable_has_explicit_blocked_report(self):
        report = {**self.expected("reviewer"), "status": "BLOCKED", "blockers": ["无法读取 spec"]}
        self.assertTrue(self.invoke("reviewer", report)["ok"])
        report["blockers"] = []
        self.assertFalse(self.invoke("reviewer", report)["ok"])

    def test_axis_and_fixed_commit_identity_are_bound(self):
        for key, value in (("axis", "standards"), ("reviewed_base", B), ("reviewed_head", A)):
            report = self.axis()
            report[key] = value
            self.reject("reviewer", report, key + "_matches_dispatch")
        report = self.axis(True)
        report["findings"][0]["axis"] = "standards"
        self.reject("reviewer", report, "finding_axis_matches_dispatch")

    def test_receipt_path_status_and_file_hash_are_bound(self):
        for changes in (
            {"status": "BLOCKED"},
            {"report_path": "/different/report.json"},
            {"report_sha256": "0" * 64},
        ):
            self.assertFalse(self.invoke("reviewer", self.axis(), receipt_change=changes)["ok"])

    def test_bad_review_structure_and_invalid_dispatch_fail(self):
        self.assertFalse(self.invoke("reviewer", {"findings": []})["ok"])
        self.assertFalse(self.invoke("reviewer", self.axis(), expected={})["ok"])
        report = self.axis(True)
        report["findings"][0]["blocking"] = False
        self.assertFalse(self.invoke("reviewer", report)["ok"])

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

    def test_fixer_gates_cannot_be_omitted_or_claimed_at_old_head(self):
        report = self.fixer()
        report["verification"] = report["verification"][1:]
        self.reject("fixer", report, "final_validation_on_delivery_head")
        report = self.fixer()
        for item in report["verification"]:
            item["head_commit"] = A
        self.reject("fixer", report, "final_validation_on_delivery_head")
        report = self.fixer()
        report["boundary_gates"] = []
        self.reject("fixer", report, "required_gates_retained")
        report = self.fixer()
        report["boundary_gates"].append("gate-postgres")
        self.reject("fixer", report, "boundary_gate_sources")

    def test_fixer_last_gate_result_wins_and_failed_history_is_preserved(self):
        report = self.fixer()
        failed = {**report["verification"][0], "passed": False, "result": "失败"}
        report["verification"].insert(0, failed)
        self.assertTrue(self.invoke("fixer", report)["ok"])
        report["verification"].append(failed)
        self.reject("fixer", report, "final_validation_on_delivery_head")

    def test_schema_and_self_check_commands(self):
        for role in ("reviewer", "fixer"):
            for args in (["--schema", role], ["--receipt-schema", role]):
                result = subprocess.run(
                    [sys.executable, "-B", str(VERIFIER), *args], capture_output=True, text=True
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIsInstance(json.loads(result.stdout), dict)
        report = self.axis()
        self.invoke("reviewer", report)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(VERIFIER),
                "--check-report",
                "reviewer",
                str(self.root / "report.json"),
                "--expected",
                str(self.root / "dispatch.json"),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""phase 验收契约回归；只写入临时报告，不触碰 Git/Beads。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

VERIFIER = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"
SHA_A = "a" * 40
SHA_B = "b" * 40

pytestmark = pytest.mark.integration


class PhaseValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="phase-validator-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.expected = {
            "parent_id": "demo-1",
            "expected_children": ["demo-2", "demo-3"],
            "reviewed_main": SHA_A,
            "start_head": SHA_B,
            "required_boundary_gates": ["gate-browser"],
        }

    def dispatch(self, phase: str) -> dict:
        common = {
            "repository_root": "/repo",
            "parent_id": "demo-1",
            "rules_paths": [],
            "skill_dir": "/skill",
            "report_path": "/evidence/report.json",
            "dispatch_path": "/evidence/dispatch.json",
        }
        if phase == "preflight":
            return {
                **common,
                "expected_branch": "implement/demo-1",
                "expected_worktree": "/repo/.worktrees/demo-1",
            }
        return {
            **common,
            "worktree": "/repo/.worktrees/demo-1",
            "branch": "implement/demo-1",
            "expected_children": self.expected["expected_children"],
            "linked_spec": "spec",
            "reviewed_main": SHA_A,
            "start_head": SHA_B,
            "ticket_evidence": [],
            "required_boundary_gates": ["gate-browser"],
            "prior_finalization": None,
        }

    def plan(self, mode: str = "TDD") -> dict:
        return {
            "mode": mode,
            "approved_seams": ["S1"] if mode == "TDD" else [],
            "boundary_gates": ["gate-browser"],
            "observable_behavior": "可观察行为" if mode == "TDD" else None,
            "expected_red": "BASE 失败" if mode == "TDD" else None,
            "reason": None if mode == "TDD" else "无需 red",
            "verification": None if mode == "TDD" else "just gate-browser",
        }

    def preflight(self, status: str = "READY") -> dict:
        checks = [
            {"name": name, "passed": True, "evidence": "已核对"}
            for name in (
                "parent_state",
                "children_nonempty",
                "ready_labels",
                "flat_graph",
                "execution_plan",
                "spec_and_test_plans",
                "beads_config",
                "primary_worktree",
                "worktree_ignored",
                "branch_name",
                "beads_clean",
                "toolchain",
                "just_recipes",
                "gate_plan",
                "review_schema",
                "recovery",
            )
        ]
        report = {
            "status": status,
            "parent": {"id": "demo-1", "status": "open"},
            "expected_children": ["demo-2", "demo-3"],
            "execution_plan": {"ticket_order": ["demo-2", "demo-3"]},
            "tickets": [
                {"id": "demo-2", "status": "open", "test_plan": self.plan()},
                {"id": "demo-3", "status": "open", "test_plan": self.plan("direct_verification")},
            ],
            "linked_spec": "spec",
            "boundary_gates": ["gate-browser"],
            "gate_plan": {
                "core": "gate-core",
                "full": ["gate-core", "gate-browser"],
                "defer_to_final": [],
            },
            "gate_plan_source": {"path": "/evidence/gate-plan.json", "sha256": "a" * 64},
            "workspace": {
                "primary_worktree": "/repo",
                "implementation_worktree": "/repo/.worktrees/demo-1",
                "branch": "implement/demo-1",
                "observed_head": SHA_A,
                "clean": True,
            },
            "resume_evidence": [],
            "sources": ["bd show"],
            "suggested_route": "new_batch",
            "checks": checks,
            "blockers": [],
            "remaining_work": [],
        }
        if status == "BLOCKED":
            report.update(
                blockers=["无法读取 parent"], remaining_work=["补齐 Beads 事实"], checks=[]
            )
            report["parent"] = {"id": None, "status": None}
            report["expected_children"] = []
            report["tickets"] = []
            report["boundary_gates"] = []
        return report

    def pair(self, base: str = SHA_A, head: str = SHA_B, blocking: bool = False) -> dict:
        finding = (
            [
                {
                    "axis": "spec",
                    "kind": "defect",
                    "blocking": True,
                    "title": "缺陷",
                    "evidence": "证据",
                }
            ]
            if blocking
            else []
        )
        return {
            "standards": {
                "reviewed_base": base,
                "reviewed_head": head,
                "axis": "standards",
                "findings": [],
                "notes": [],
            },
            "spec": {
                "reviewed_base": base,
                "reviewed_head": head,
                "axis": "spec",
                "findings": finding,
                "notes": [],
            },
        }

    def finalizer(self, status: str = "READY_TO_MERGE") -> dict:
        report = {
            "status": status,
            "parent_id": "demo-1",
            "expected_children": ["demo-2", "demo-3"],
            "reviewed_main": SHA_A,
            "start_head": SHA_B,
            "head_commit": SHA_B,
            "required_gates": ["gate-browser"],
            "boundary_gates": ["gate-browser"],
            "gate_sources": [{"gate": "gate-browser", "source": "ticket"}],
            "verification": [
                {
                    "gate": "gate-full",
                    "command": "just gate-full",
                    "result": "通过",
                    "log_path": "/evidence/gate-full.log",
                    "head_commit": SHA_B,
                    "passed": True,
                }
            ],
            "fix": {"used": False, "commits": [], "dispositions": []},
            "review_rounds": [self.pair()],
            "workspace": {"branch": "implement/demo-1", "observed_head": SHA_B, "clean": True},
            "sources": ["ticket evidence"],
            "stopped_tasks": True,
            "blockers": [],
            "remaining_work": [],
        }
        if status == "BLOCKED":
            report.update(
                reviewed_main=None,
                start_head=None,
                head_commit=None,
                verification=[],
                review_rounds=[],
                stopped_tasks=False,
                blockers=["gate 失败"],
                remaining_work=["修复"],
                required_gates=[],
                boundary_gates=[],
            )
        return report

    def invoke(
        self, phase: str, report: dict, *, expected: bool | dict = True, receipt: dict | None = None
    ) -> dict:
        report_path = self.root / (phase + ".json")
        raw = json.dumps(report, ensure_ascii=False).encode()
        report_path.write_bytes(raw)
        args = ["--check-report", phase, str(report_path)]
        if receipt is not None:
            receipt_path = self.root / "receipt.json"
            receipt_path.write_text(json.dumps(receipt))
            args.append(str(receipt_path))
        if expected:
            dispatch = self.root / "dispatch.json"
            dispatch.write_text(
                json.dumps(expected if isinstance(expected, dict) else self.dispatch(phase))
            )
            args.extend(["--expected", str(dispatch)])
        result = subprocess.run(
            [sys.executable, str(VERIFIER), "verify", "phase", *args],
            capture_output=True,
            text=True,
        )
        parsed = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0 if parsed["ok"] else 1, result.stderr)
        self.assertEqual(report_path.read_bytes(), raw)
        return parsed

    def rejected(self, phase: str, report: dict, check: str) -> None:
        actual = self.invoke(phase, report)
        self.assertFalse(actual["ok"])
        self.assertIn(check, {item["check"] for item in actual["failures"]})

    def test_preflight_ready_and_blocked_are_valid(self) -> None:
        self.assertTrue(self.invoke("preflight", self.preflight())["ok"])
        self.assertTrue(self.invoke("preflight", self.preflight("BLOCKED"), expected=False)["ok"])

    def test_preflight_rejects_missing_check_gate_and_changed_children(self) -> None:
        changed = self.preflight()
        changed["checks"] = []
        self.rejected("preflight", changed, "all_preflight_checks_passed")
        changed = self.preflight()
        changed["boundary_gates"] = []
        self.rejected("preflight", changed, "boundary_gates_are_ticket_union")
        changed = self.preflight()
        changed["expected_children"] = ["demo-2"]
        self.rejected("preflight", changed, "tickets_match_unique_children")

    def test_finalizer_ready_and_blocked_are_valid(self) -> None:
        self.assertTrue(self.invoke("finalizer", self.finalizer())["ok"])
        self.assertTrue(self.invoke("finalizer", self.finalizer("BLOCKED"), expected=False)["ok"])

    def test_finalizer_rejects_wrong_sha_omitted_gate_repair_and_live_writer(self) -> None:
        changed = self.finalizer()
        changed["review_rounds"] = [self.pair(base="c" * 40)]
        self.rejected("finalizer", changed, "review_sha_binding")
        changed = self.finalizer()
        changed["verification"] = []
        self.rejected("finalizer", changed, "required_gates_covered")
        changed = self.finalizer()
        changed["fix"] = {"used": False, "commits": ["c" * 40], "dispositions": []}
        self.rejected("finalizer", changed, "repair_limit")
        changed = self.finalizer()
        changed["stopped_tasks"] = False
        self.rejected("finalizer", changed, "writers_and_reviewers_stopped")

    def test_finalizer_uses_last_delivery_head_gate_result(self) -> None:
        changed = self.finalizer()
        changed["verification"].append(
            {
                "gate": "gate-full",
                "command": "just gate-full",
                "result": "失败",
                "log_path": "/evidence/retry.log",
                "head_commit": SHA_B,
                "passed": False,
            }
        )
        self.rejected("finalizer", changed, "required_gates_covered")

    def test_new_batch_without_worktree_and_post_merge_without_plans(self) -> None:
        report = self.preflight()
        report["workspace"].update(observed_head=None, clean=None)
        self.assertTrue(self.invoke("preflight", report)["ok"])
        report["parent"]["status"] = "closed"
        report["suggested_route"] = "post_merge"
        report["boundary_gates"] = []
        for ticket in report["tickets"]:
            ticket.update(status="closed", test_plan=None)
        self.assertTrue(self.invoke("preflight", report)["ok"])

    def test_preflight_replacement_keeps_children_and_blocked_unknown_facts(self) -> None:
        expected = self.dispatch("preflight")
        expected["expected_children"] = ["different-child"]
        self.assertFalse(self.invoke("preflight", self.preflight(), expected=expected)["ok"])
        report = self.preflight("BLOCKED")
        report["workspace"].update(observed_head=None, clean=None, branch=None)
        self.assertTrue(self.invoke("preflight", report)["ok"])

    def test_repair_retains_failed_validation_and_original_review_head(self) -> None:
        report = self.finalizer()
        old_head = "c" * 40
        report["fix"] = {"used": True, "commits": [SHA_B], "dispositions": ["修复原 finding"]}
        report["review_rounds"] = [self.pair(head=old_head, blocking=True), self.pair()]
        report["verification"].insert(
            0,
            {
                "gate": "gate-full",
                "command": "just gate-full",
                "result": "失败",
                "log_path": "/evidence/initial.log",
                "head_commit": old_head,
                "passed": False,
            },
        )
        self.assertTrue(self.invoke("finalizer", report)["ok"])
        report["review_rounds"] = [self.pair()]
        self.assertTrue(self.invoke("finalizer", report)["ok"])
        report["review_rounds"] = [self.pair(blocking=True)]
        self.rejected("finalizer", report, "final_review_gate_pass")

    def test_new_boundary_and_dirty_workspace_cannot_pass(self) -> None:
        report = self.finalizer()
        report["boundary_gates"].append("gate-postgres")
        self.rejected("finalizer", report, "boundary_gate_sources")
        report = self.finalizer()
        report["workspace"]["clean"] = False
        self.rejected("finalizer", report, "workspace_ready")

    def test_replacement_cannot_reset_used_repair_or_review_rounds(self) -> None:
        expected = self.dispatch("finalizer")
        expected["prior_finalization"] = {
            "fix_used": True,
            "review_rounds_used": 2,
            "report_path": "/evidence/prior.json",
        }
        report = self.finalizer()
        self.assertFalse(self.invoke("finalizer", report, expected=expected)["ok"])
        report["fix"] = {"used": True, "commits": [SHA_B], "dispositions": ["已修复"]}
        self.assertFalse(self.invoke("finalizer", report, expected=expected)["ok"])
        report["review_rounds"] = [self.pair(head="c" * 40, blocking=True), self.pair()]
        self.assertTrue(self.invoke("finalizer", report, expected=expected)["ok"])
        report["fix"]["commits"] = []
        self.assertFalse(self.invoke("finalizer", report, expected=expected)["ok"])

    def test_dispatch_without_snapshot_and_valid_prior(self) -> None:
        expected = self.dispatch("finalizer")
        self.assertTrue(self.invoke("finalizer", self.finalizer(), expected=expected)["ok"])
        for prior in (
            {},
            {"fix_used": "true", "review_rounds_used": 1},
            {"fix_used": True, "review_rounds_used": True, "report_path": "/evidence/prior.json"},
        ):
            expected = self.dispatch("finalizer")
            expected["prior_finalization"] = prior
            self.assertFalse(self.invoke("finalizer", self.finalizer(), expected=expected)["ok"])

    def test_receipt_binds_path_status_and_hash(self) -> None:
        report = self.preflight()
        path = self.root / "preflight.json"
        raw = json.dumps(report, ensure_ascii=False).encode()
        path.write_bytes(raw)
        receipt = {
            "status": "READY",
            "report_path": str(path.absolute()),
            "report_sha256": hashlib.sha256(raw).hexdigest(),
        }
        outcome = self.invoke("preflight", report, receipt=receipt)
        self.assertTrue(outcome["ok"], outcome)
        receipt["report_sha256"] = "0" * 64
        self.assertFalse(self.invoke("preflight", report, receipt=receipt)["ok"])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""phase 验收契约回归；只写入临时报告，不触碰 Git/Beads。"""

from __future__ import annotations

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
            "prior_finalization": None,
        }

    def plan(self, mode: str = "TDD") -> dict:
        return {
            "mode": mode,
            "approved_seams": ["S1"] if mode == "TDD" else [],
            "observable_behavior": "可观察行为" if mode == "TDD" else None,
            "expected_red": "BASE 失败" if mode == "TDD" else None,
            "reason": None if mode == "TDD" else "无需 red",
            "verification": "just test 相关场景，观察目标行为",
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
                "just_recipes",
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
            "document_sources": [],
            "document_commits": [],
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


if __name__ == "__main__":
    unittest.main()

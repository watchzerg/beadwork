#!/usr/bin/env python3
"""验收协议回归：在一次性 Git 仓库运行真实 CLI，不修改调用方仓库。

python3 test_verify_ticket.py
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import pytest

VERIFIER = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"

pytestmark = pytest.mark.integration


class TicketAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="ticket-acceptance-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.primary = self.root / "primary"
        self.worktree = self.root / "implementation"
        self.primary.mkdir()
        self.env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "验收回归",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "验收回归",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
        self.git(self.primary, "init", "-b", "main")
        (self.primary / "behavior.txt").write_text("baseline\n")
        self.git(self.primary, "add", ".")
        self.git(self.primary, "commit", "-m", "baseline")
        self.base = self.git(self.primary, "rev-parse", "HEAD")
        self.git(self.primary, "worktree", "add", "-b", "implement/test", str(self.worktree))
        self.commits = []
        for number in (1, 2):
            (self.worktree / "behavior.txt").write_text(f"behavior {number}\n")
            self.git(self.worktree, "add", ".")
            self.git(self.worktree, "commit", "-m", f"ticket layer {number}")
            self.commits.append(
                {
                    "sha": self.git(self.worktree, "rev-parse", "HEAD"),
                    "subject": f"ticket layer {number}",
                }
            )
        self.head = self.commits[-1]["sha"]
        self.snapshot = self.root / "baseline.txt"
        self.snapshot.write_text("")
        self.plan = {"mode": "TDD", "approved_seams": ["S1"]}
        self.report: dict[str, Any] = {
            "status": "DONE",
            "base_commit": self.base,
            "head_commit": self.head,
            "delivery_kind": "changed",
            "implementation_commits": self.commits,
            "test_plan": {
                **self.plan,
                "decision_source": "ticket/spec",
                "red_evidence": "BASE 行为断言失败，随后实现通过",
            },
            "acceptance": [{"criterion": "交付行为", "evidence": "观察到目标状态转换"}],
            "verification": [{"command": "just test", "result": "通过"}],
            "review": {"attempts": 1, "gate": "PASS", "final": self.pair(self.head)},
            "requested_context": [],
            "blockers": [],
            "concerns": [],
        }

    def git(self, cwd: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, *args],
            cwd=cwd,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def pair(self, head: str) -> dict:
        return {
            axis: {
                "reviewed_base": self.base,
                "reviewed_head": head,
                "axis": axis,
                "findings": [],
                "notes": [],
            }
            for axis in ("standards", "spec")
        }

    def invoke(
        self,
        report: object,
        *,
        plan: dict | None = None,
        status: str = "DONE",
        local: bool = False,
        base: str | None = None,
        head: str | None = None,
    ) -> dict:
        self.report_file = self.root / "report.json"
        raw = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        self.report_file.write_bytes(raw)
        plan_file = self.root / "expected-plan.json"
        plan_file.write_text(json.dumps(plan if plan is not None else self.plan))
        args = (
            ["--check-report", str(self.report_file)]
            if local
            else [
                "implement/test",
                base or self.base,
                head or self.head,
                status,
                str(self.report_file),
                str(plan_file),
            ]
        )
        result = subprocess.run(
            [sys.executable, str(VERIFIER), "verify", "ticket", *args],
            cwd=self.worktree,
            env=self.env,
            capture_output=True,
            text=True,
        )
        parsed = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0 if parsed["ok"] else 1, result.stderr)
        self.assertEqual(self.report_file.read_bytes(), raw, "验收不能覆写原始报告")
        self.assertEqual(parsed["report_sha256"], hashlib.sha256(raw).hexdigest())
        return parsed

    def reject(self, report: object, check: str, **kwargs: Any) -> None:
        result = self.invoke(report, **kwargs)
        self.assertFalse(result["ok"])
        self.assertIn(check, {failure["check"] for failure in result["failures"]})

    def check_receipt(self, receipt: object) -> dict:
        receipt_file = self.root / "receipt.json"
        receipt_file.write_text(json.dumps(receipt))
        original = self.report_file.read_bytes()
        result = subprocess.run(
            [
                sys.executable,
                str(VERIFIER),
                "verify",
                "ticket",
                "--check-report",
                str(self.report_file),
                str(receipt_file),
            ],
            cwd=self.worktree,
            env=self.env,
            capture_output=True,
            text=True,
        )
        parsed = json.loads(result.stdout)
        self.assertEqual(result.returncode, 0 if parsed["ok"] else 1, result.stderr)
        self.assertEqual(self.report_file.read_bytes(), original)
        return parsed

    def receipt(self) -> dict:
        return {
            "status": self.report["status"],
            "report_path": str(self.report_file),
            "report_sha256": hashlib.sha256(self.report_file.read_bytes()).hexdigest(),
        }

    def test_valid_done_preserves_original_and_accepts_nonblocking_smell(self) -> None:
        self.report["review"]["final"]["standards"]["findings"] = [
            {
                "axis": "standards",
                "kind": "smell",
                "blocking": False,
                "title": "可能重复",
                "evidence": "两段同形分支，但当前不值得引入抽象",
            }
        ]
        self.assertTrue(self.invoke(self.report)["ok"])
        self.assertTrue(self.invoke(self.report, local=True)["ok"])


if __name__ == "__main__":
    unittest.main()

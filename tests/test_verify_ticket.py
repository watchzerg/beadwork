#!/usr/bin/env python3
"""验收协议回归：在一次性 Git 仓库运行真实 CLI，不修改调用方仓库。

python3 test_verify_ticket.py
"""

from __future__ import annotations

import copy
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

import evidence

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

    def test_receipt_accepts_done_and_partial_reports_without_full_chat_copy(self) -> None:
        for status in ("DONE", "NEEDS_CONTEXT", "BLOCKED"):
            with self.subTest(status=status):
                self.report["status"] = status
                if status != "DONE":
                    self.report.update(
                        base_commit=None,
                        head_commit=None,
                        test_plan=None,
                        implementation_commits=[],
                        acceptance=[],
                        verification=[],
                        review=None,
                        requested_context=["缺少 spec"] if status == "NEEDS_CONTEXT" else [],
                        blockers=["环境不可用"] if status == "BLOCKED" else [],
                    )
                self.assertTrue(self.invoke(self.report, local=True)["ok"])
                self.assertTrue(self.check_receipt(self.receipt())["ok"])

    def test_receipt_cannot_select_another_report_or_misstate_status_or_hash(self) -> None:
        self.invoke(self.report, local=True)
        other = self.root / "other-report.json"
        other.write_bytes(self.report_file.read_bytes())
        for field, value in (
            ("report_path", str(other)),
            ("report_path", "report.json"),
            ("status", "BLOCKED"),
            ("report_sha256", "0" * 64),
        ):
            with self.subTest(field=field, value=value):
                receipt = {**self.receipt(), field: value}
                result = self.check_receipt(receipt)
                self.assertFalse(result["ok"])
                self.assertIn(
                    "receipt_" + field + "_matches", {f["check"] for f in result["failures"]}
                )

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

    def test_commit_set_must_be_complete_unique_and_exact(self) -> None:
        for commits, check in (
            (self.commits[:1], "report_commits_match_range"),
            (self.commits + [self.commits[0]], "report_commits_unique"),
            (
                self.commits + [{"sha": "f" * 40, "subject": "错误 SHA"}],
                "report_commits_match_range",
            ),
        ):
            with self.subTest(commits=commits):
                changed = copy.deepcopy(self.report)
                changed["implementation_commits"] = commits
                self.reject(changed, check)

    def test_controller_identity_and_preflight_plan_are_authoritative(self) -> None:
        changed = copy.deepcopy(self.report)
        changed["base_commit"] = "e" * 40
        for result in changed["review"]["final"].values():
            result["reviewed_base"] = changed["base_commit"]
        self.reject(changed, "base_matches_reported")
        changed = copy.deepcopy(self.report)
        changed["test_plan"]["approved_seams"] = ["S2"]
        self.reject(changed, "test_plan_matches_preflight")
        self.reject(self.report, "status_matches", status="BLOCKED")
        changed["test_plan"]["approved_seams"] = ["S2", "S1"]
        self.assertTrue(
            self.invoke(changed, plan={"mode": "TDD", "approved_seams": ["S1", "S2"]})["ok"]
        )

    def test_tdd_and_direct_verification_have_distinct_contracts(self) -> None:
        for field, value in (
            ("approved_seams", []),
            ("approved_seams", ["S1", "S1"]),
            ("red_evidence", None),
        ):
            with self.subTest(field=field, value=value):
                changed = copy.deepcopy(self.report)
                changed["test_plan"][field] = value
                self.reject(changed, "report_schema", local=True)
        changed = copy.deepcopy(self.report)
        changed["test_plan"].update(
            mode="direct_verification", approved_seams=[], red_evidence=None
        )
        plan = {"mode": "direct_verification", "approved_seams": []}
        self.assertTrue(self.invoke(changed, plan=plan)["ok"])
        changed["test_plan"]["red_evidence"] = "不应声称 red"
        self.reject(changed, "report_schema", local=True)

    def test_review_must_cover_the_delivered_head_on_both_axes(self) -> None:
        changed = copy.deepcopy(self.report)
        changed["review"]["final"] = self.pair(self.commits[0]["sha"])
        self.reject(changed, "review_head_matches_reported")
        changed["review"]["final"]["standards"]["reviewed_head"] = self.head
        self.reject(changed, "review_heads_agree")
        changed = copy.deepcopy(self.report)
        changed["review"]["final"]["spec"]["axis"] = "standards"
        self.reject(changed, "review_axis")

    def test_no_change_direct_verification_can_rereview_same_head(self) -> None:
        changed = copy.deepcopy(self.report)
        changed.update(
            base_commit=self.head,
            implementation_commits=[],
            delivery_kind="already_satisfied",
        )
        changed["test_plan"].update(
            mode="direct_verification",
            approved_seams=[],
            red_evidence=None,
        )
        initial = self.pair(self.head)
        for pair in (initial, changed["review"]["final"]):
            for axis in pair.values():
                axis["reviewed_base"] = self.head
        initial["spec"]["findings"] = [
            {
                "axis": "spec",
                "kind": "defect",
                "blocking": True,
                "title": "本机状态位置错误",
                "evidence": "ignored machine state 尚未写入实际运行 checkout",
            }
        ]
        changed["review"].update(attempts=2, initial=initial)

        pairs = [initial, changed["review"]["final"]]
        sources = []
        for index, pair in enumerate(pairs):
            folder = self.root.resolve() / f"existing-review-{index}"
            folder.mkdir()
            evidence.write(
                folder / "dispatch.json",
                {
                    "role": "executor",
                    "workflow_contract_version": 7,
                    "launch_context": {"fork_turns": "none", "required": True},
                    "base_commit": self.head,
                    "test_mode": "direct_verification",
                },
            )
            evidence.write(
                folder / "acceptance.json",
                [{"criterion": "本机配置", "evidence": "不含秘密的当前状态核对"}],
            )
            evidence.write(
                folder / "round.json",
                {
                    "review_kind": "existing_behavior",
                    "reviewed_base": self.head,
                    "reviewed_head": self.head,
                    "dispatch": evidence.binding(folder / "dispatch.json"),
                    "acceptance_evidence": evidence.binding(folder / "acceptance.json"),
                },
            )
            evidence.write(
                folder / "collection.json",
                {"round": evidence.binding(folder / "round.json"), "pair": pair},
            )
            sources.append(evidence.binding(folder / "collection.json"))
        changed["review"].update(rounds=pairs, sources=sources)

        direct_plan = {"mode": "direct_verification", "approved_seams": []}
        self.assertTrue(
            self.invoke(
                changed,
                plan=direct_plan,
                base=self.head,
                head=self.head,
            )["ok"]
        )

        missing = copy.deepcopy(changed)
        del missing["review"]["sources"], missing["review"]["rounds"]
        self.reject(missing, "review_requires_new_head", local=True)
        for filename in ("collection.json", "round.json", "dispatch.json", "acceptance.json"):
            path = folder / filename
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"\n")
                self.reject(changed, "review_requires_new_head", local=True)
            finally:
                path.write_bytes(original)

        changed = copy.deepcopy(self.report)
        initial = self.pair(self.head)
        initial["spec"]["findings"] = [
            {
                "axis": "spec",
                "kind": "defect",
                "blocking": True,
                "title": "代码缺陷",
                "evidence": "源码行为仍未实现",
            }
        ]
        changed["review"].update(attempts=2, initial=initial)
        self.reject(changed, "review_requires_new_head", local=True)

    def test_dirty_primary_allowed_but_dirty_done_tree_rejected(self) -> None:
        (self.primary / "unexpected.txt").write_text("意外变动")
        self.assertTrue(self.invoke(self.report)["ok"])
        (self.primary / "unexpected.txt").unlink()
        (self.worktree / "unexpected.txt").write_text("未提交")
        self.reject(self.report, "done_clean_tree")


if __name__ == "__main__":
    unittest.main()

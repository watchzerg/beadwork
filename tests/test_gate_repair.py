"""用真实验证记录检查三次修正、恢复继承与 review 冻结。"""

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

import test_run_verification as verification_fixture

pytestmark = pytest.mark.workflow


class GateRepairTests(unittest.TestCase):
    def setUp(self):
        self.v = verification_fixture.VerificationTests()
        self.v.setUp()
        self.addCleanup(self.v.doCleanups)
        self.h = self.v.h

    def run_gate(self, mode="fail", delivery=True, expected=1, recipe="gate-core"):
        argv = self.v.command(recipe)
        if delivery:
            argv.insert(argv.index("--"), "--delivery")
        r = subprocess.run(
            argv,
            env={**self.h.env, "TEST_MODE": mode},
            cwd=self.h.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, expected, r.stdout + r.stderr)
        if r.stdout:
            return Path(json.loads(r.stdout)["run_path"]) / "result.json"
        return r.stderr

    def begin(self, failure, expected=0):
        r = subprocess.run(
            [
                sys.executable,
                "-B",
                str(verification_fixture.ASSEMBLE),
                "executor",
                "begin-gate-repair",
                "--dispatch",
                str(self.v.dispatch),
                "--failure",
                str(failure),
            ],
            env=self.h.env,
            cwd=self.h.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, expected, r.stdout + r.stderr)
        return json.loads(r.stdout if expected == 0 else r.stderr)

    def test_three_repairs_idempotent_and_development_red_is_not_delivery(self):
        red = self.run_gate(delivery=False)
        self.begin(red, expected=1)
        failure = self.run_gate()
        first = self.begin(failure)
        self.assertEqual(self.begin(failure), first)
        second = self.run_gate()
        self.assertEqual(self.begin(second)["repair_number"], 2)
        third = self.run_gate(recipe="gate-demo")
        self.assertEqual(self.begin(third)["remaining_repairs"], 0)
        self.assertEqual(self.begin(failure), first)
        exhausted = self.run_gate()
        self.assertIn("三次", self.begin(exhausted, expected=1)["error"])
        self.assertTrue(failure.exists())
        self.run_gate(mode="pass", expected=0)

    def test_each_repair_binds_new_head_and_preserves_prior_evidence(self):
        failure = self.run_gate()
        other_failure = self.run_gate(recipe="gate-demo")
        snapshots = {}
        for number in range(1, 4):
            grant = self.begin(failure)
            self.assertEqual(grant["repair_number"], number)
            if number == 1:
                self.begin(other_failure, expected=1)
            path = Path(grant["gate_repair_path"])
            snapshots[path] = path.read_bytes()
            (self.h.wt / "repair.txt").write_text(f"修正 {number}")
            self.h.h.git(self.h.wt, "add", "repair.txt")
            self.h.h.git(self.h.wt, "commit", "-m", f"修正 {number}")
            failure = self.run_gate()
        self.begin(failure, expected=1)
        self.run_gate(mode="pass", expected=0)
        r = subprocess.run(
            [
                sys.executable,
                "-B",
                str(verification_fixture.ASSEMBLE),
                "executor",
                "review-prepare",
                "--dispatch",
                str(self.v.dispatch),
            ],
            env=self.h.env,
            cwd=self.h.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        for path, original in snapshots.items():
            self.assertEqual(path.read_bytes(), original)
        self.begin(failure, expected=1)

    def test_resume_inherits_and_new_stage_gets_new_opportunity(self):
        failure = self.run_gate()
        self.begin(failure)
        old = self.v.dispatch
        self.h.prepare(previous_dispatch=str(old))
        self.v.dispatch = self.h.dispatch
        self.assertEqual(
            self.begin(failure)["gate_repair_path"], str(old.parent / "gate-repair.json")
        )
        second = self.run_gate()
        self.assertEqual(self.begin(second)["repair_number"], 2)
        self.assertEqual(self.begin(self.run_gate())["repair_number"], 3)
        self.begin(self.run_gate(), expected=1)
        report = self.v.assemble()
        path = self.v.dispatch.parent / "report-run-1.json"
        report["outcome"] = "code_failure"
        self.h.put(path, report)
        receipt = self.v.dispatch.parent / "receipt.json"
        self.h.put(
            receipt,
            {
                "status": "BLOCKED",
                "report_path": str(path),
                "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
        )
        self.h.prepare(
            previous_dispatch=str(self.v.dispatch),
            previous_report=str(path),
            previous_receipt=str(receipt),
            continuation="repair",
            fixture_stage=1,
        )
        self.v.dispatch = self.h.dispatch
        self.assertEqual(self.h.d["stage"], 1)
        self.assertEqual(self.h.d["base_commit"], report["base_commit"])
        self.begin(self.run_gate())

    def test_candidate_head_is_fixed_and_review_blocks_repair(self):
        failure = self.run_gate()
        self.begin(failure)
        self.run_gate(mode="pass", expected=0)
        r = subprocess.run(
            [
                sys.executable,
                "-B",
                str(verification_fixture.ASSEMBLE),
                "executor",
                "review-prepare",
                "--dispatch",
                str(self.v.dispatch),
            ],
            env=self.h.env,
            cwd=self.h.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("review", self.begin(failure, expected=1)["error"])

    def test_review_scope_draft_does_not_block_gate_repair(self):
        failure = self.run_gate()
        draft = self.v.dispatch.parent / "review-scope.md"
        draft.write_text("待审范围草稿")
        self.assertTrue(self.begin(failure)["allowed"])
        self.assertEqual(draft.read_text(), "待审范围草稿")

    def test_review_marker_or_partial_directory_blocks_gate_repair(self):
        failure = self.run_gate()
        for name in ("gate-review-started.json", "review-partial"):
            with self.subTest(name=name):
                path = self.v.dispatch.parent / name
                if name.endswith(".json"):
                    path.write_text("{}")
                else:
                    path.mkdir()
                self.assertIn("review", self.begin(failure, expected=1)["error"])
                self.assertFalse((self.v.dispatch.parent / "gate-repair.json").exists())
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()

    def test_repaired_delivery_cannot_switch_candidates(self):
        self.begin(self.run_gate())
        self.run_gate(mode="pass", expected=0)
        (self.h.wt / "repair.txt").write_text("修正")
        self.h.h.git(self.h.wt, "add", "repair.txt")
        self.h.h.git(self.h.wt, "commit", "-m", "修正")
        self.assertIn("已有不同", self.run_gate(expected=2))
        r = subprocess.run(
            [
                sys.executable,
                "-B",
                str(verification_fixture.ASSEMBLE),
                "executor",
                "review-prepare",
                "--dispatch",
                str(self.v.dispatch),
            ],
            env=self.h.env,
            cwd=self.h.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(r.returncode, 1, r.stderr)

    def test_final_fixer_uses_same_allowance_across_resume(self):
        import test_finalization as final_fixture

        f = final_fixture.FinalizationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        fake = f.h.root / "bin" / "just"
        fake.write_text(self.v.fake.read_text().replace("gate-demo", "gate-browser"))
        fake.chmod(0o755)
        self.h = f.h
        self.v.h = f.h
        stage0 = f.stage()
        self.v.dispatch = stage0
        self.run_gate(recipe="gate-full")
        _, receipt0 = f.assemble(stage0, outcome="code_failure")
        stage1 = f.stage(previous=stage0, receipt=receipt0, continuation="repair")
        self.v.dispatch = stage1.parent / "fixer" / "dispatch.json"
        failed = self.run_gate(recipe="gate-full")
        first = self.begin(failed)
        _, receipt1 = f.assemble(stage1, outcome="interrupted")
        resumed = f.stage(previous=stage1, receipt=receipt1)
        self.v.dispatch = resumed.parent / "fixer" / "dispatch.json"
        self.assertEqual(self.begin(failed), first)
        self.assertEqual(self.begin(self.run_gate(recipe="gate-full"))["repair_number"], 2)
        self.assertEqual(self.begin(self.run_gate(recipe="gate-full"))["repair_number"], 3)
        self.begin(self.run_gate(recipe="gate-full"), expected=1)
        self.run_gate(mode="pass", expected=0, recipe="gate-full")

    def test_tampered_log_and_other_stage_are_rejected(self):
        failure = self.run_gate()
        log = failure.parent / "output.log"
        original = log.read_bytes()
        log.write_bytes(b"changed")
        self.begin(failure, expected=1)
        log.write_bytes(original)
        self.h.prepare()
        self.v.dispatch = self.h.dispatch
        self.begin(failure, expected=1)


if __name__ == "__main__":
    unittest.main()

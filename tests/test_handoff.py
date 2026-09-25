"""交接契约负例：公开 CLI、临时 Git worktree 与真实验证采集。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import pytest

import draft_contracts
import test_finalization as fixture
from fixture_support import closure_source

pytestmark = pytest.mark.workflow


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.f: Any = fixture.FinalizationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.bin = self.f.h.root / "bin/just"
        self.bin.write_text(
            "#!"
            + sys.executable
            + '\nimport os,sys,signal\nif sys.argv[1:]==["--summary"]: print(\'install test gate-core gate-full\')\nelif os.environ.get("GATE_INTERRUPT"): os.kill(os.getpid(),signal.SIGTERM)\nelse: print("collected 1 check");sys.exit(int(os.environ.get("GATE_EXIT", "0")))\n'
        )
        self.bin.chmod(0o755)
        self.original_review = self.f.review
        self.original_assemble = self.f.assemble
        self.original_fixer = self.f.done_fixer
        self.f.review = self.review
        self.f.assemble = self.assemble
        self.f.done_fixer = self.done_fixer

    def run_gate(
        self,
        dispatch,
        recipe="gate-full",
        failed=False,
        parameters=(),
        interrupted=False,
        delivery=True,
    ):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(fixture.OPS),
                "run-verification",
                "--dispatch",
                str(dispatch),
                "--recipe",
                recipe,
                *(["--delivery"] if delivery else []),
                *(["--", *parameters] if parameters else []),
            ],
            cwd=self.f.h.root,
            env=dict(
                self.f.h.env,
                GATE_EXIT="1" if failed else "0",
                GATE_INTERRUPT="1" if interrupted else "",
            ),
            text=True,
            capture_output=True,
        )
        self.assertEqual(
            result.returncode,
            3 if interrupted else 1 if failed else 0,
            result.stdout + result.stderr,
        )
        return Path(json.loads(result.stdout)["run_path"])

    def test_finalizer_rejects_auxiliary_calls_before_recording(self):
        stage = self.f.stage()
        for recipe in ("test", "gate-core", "gate-full"):
            with self.subTest(recipe=recipe):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(fixture.OPS),
                        "run-verification",
                        "--dispatch",
                        str(stage),
                        "--recipe",
                        recipe,
                    ],
                    cwd=self.f.h.root,
                    env=self.f.h.env,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn("finalizer 只采集", result.stderr)
                self.assertEqual(list(stage.parent.glob("verification-*")), [])

    def test_fixer_dirty_targeted_checks_survive_full_pipeline(self):
        stage = self.f.stage()
        _, receipt = self.f.assemble(stage, outcome="code_failure", failed_gate="gate-full")
        following = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        fd = following.parent / "fixer/dispatch.json"
        (self.f.h.wt / "targeted-test.txt").write_text("修复开发中的测试")
        red = self.run_gate(
            fd, "test", failed=True, parameters=("targeted-test.txt",), delivery=False
        )
        green = self.run_gate(fd, "test", parameters=("targeted-test.txt",), delivery=False)
        self.run_gate(fd, "gate-core", delivery=False)
        source = self.f.done_fixer(fd)
        value = json.loads(Path(source["report"]["path"]).read_text())
        self.assertEqual(
            [v["gate"] for v in value["verification"]], ["test", "test", "gate-core", "gate-full"]
        )
        self.assertFalse(value["verification"][0]["passed"])
        self.assertTrue(value["verification"][1]["passed"])
        self.assertTrue(json.loads((red / "started.json").read_text())["before"]["status"])
        self.assertTrue(json.loads((green / "started.json").read_text())["before"]["status"])
        review = self.f.review(following)
        self.f.assemble(
            following, reviews=[review], fixes=[source], status="READY_TO_MERGE", outcome="passed"
        )
        result = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "fixed.json",
        )
        self.assertEqual(result["status"], "READY_TO_MERGE")

    def gates(self, dispatch):
        for gate in ["gate-full"]:
            self.run_gate(dispatch, gate)

    def review(self, stage, **kwargs):
        d = json.loads(Path(stage).read_text())
        if d.get("stage") == 0:
            self.gates(stage)
        return self.original_review(stage, **kwargs)

    def assemble(self, stage, **kwargs):
        if kwargs.get("failed_gate"):
            self.run_gate(stage, kwargs["failed_gate"], failed=True)
        return self.original_assemble(stage, **kwargs)

    def done_fixer(self, dispatch, **kwargs):
        original = self.original_fixer(dispatch, **kwargs)
        r = json.loads(Path(original["report"]["path"]).read_text())
        self.gates(dispatch)
        folder = Path(dispatch).parent
        draft = folder / "recorded-draft.json"
        r["verification_notes"] = {}
        self.f.put(draft, {k: r[k] for k in draft_contracts.schema("fixer")["properties"]})
        result = self.f.call(
            "fixer-assemble",
            "--dispatch",
            dispatch,
            "--draft",
            draft,
            "--output",
            folder / "recorded-report.json",
        )
        receipt = folder / "recorded-receipt.json"
        self.f.put(receipt, result)
        cp = closure_source(dispatch, result["report_path"])
        self.f.put(cp, {"closure_source": json.loads(cp.read_text())})
        accepted = self.f.call(
            "fixer-accept",
            "--dispatch",
            Path(dispatch).parent.parent / "dispatch.json",
            "--report",
            result["report_path"],
            "--receipt",
            receipt,
            "--closure",
            cp,
        )
        return accepted["source"]

    def test_fixer_development_full_cannot_replace_delivery(self):
        stage = self.f.stage()
        _, receipt = self.f.assemble(stage, outcome="code_failure", failed_gate="gate-full")
        following = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        dispatch = following.parent / "fixer/dispatch.json"
        original = self.original_fixer(dispatch)
        report = json.loads(Path(original["report"]["path"]).read_text())
        development = self.run_gate(dispatch, delivery=False)
        folder = dispatch.parent
        draft = folder / "delivery-draft.json"
        report["verification_notes"] = {}
        self.f.put(draft, {k: report[k] for k in draft_contracts.schema("fixer")["properties"]})
        args = ("fixer-assemble", "--dispatch", dispatch, "--draft", draft)
        error = self.f.call(*args, "--output", folder / "development-report.json", ok=False)
        self.assertIn("交付模式", error["error"])

        delivery = self.run_gate(dispatch)
        result = self.f.call(*args, "--output", folder / "delivery-report.json")
        receipt = folder / "delivery-receipt.json"
        self.f.put(receipt, result)
        cp = closure_source(dispatch, result["report_path"])
        self.f.put(cp, {"closure_source": json.loads(cp.read_text())})
        self.f.call(
            "fixer-accept",
            "--dispatch",
            following,
            "--report",
            result["report_path"],
            "--receipt",
            receipt,
            "--closure",
            cp,
        )
        accepted = json.loads(Path(result["report_path"]).read_text())
        self.assertEqual(len(accepted["verification_sources"]), 2)
        self.assertFalse(json.loads((development / "started.json").read_text())["delivery"])
        self.assertTrue(json.loads((delivery / "started.json").read_text())["delivery"])
        self.original_review(following)
        self.f.assemble(following, status="READY_TO_MERGE", outcome="passed")
        final = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "delivery-root.json",
        )
        self.assertEqual(final["status"], "READY_TO_MERGE")

    def recover_verification(self, unknown=False):
        stage = self.f.stage()
        run = self.run_gate(stage, interrupted=True)
        if unknown:
            (run / "result.json").unlink()  # 模拟记录器只留下 started/log。
        error = self.f.call("review-prepare", "--dispatch", stage, ok=False)
        self.assertIn("收尾说明", error["error"])
        draft = self.f.draft("BLOCKED", "interrupted")
        draft["verification_notes"] = {
            str(run): "已确认旧任务和外部资源结束；恢复后重跑必要 gates。"
        }
        dp = stage.parent / "recovery-draft.json"
        self.f.put(dp, draft)
        report = stage.parent / "recovery-report.json"
        self.f.call("final-assemble", "--dispatch", stage, "--draft", dp, "--output", report)
        self.assertEqual(self.f.stage(), stage)
        self.gates(stage)
        return stage, run, report

    def test_interrupted_final_recovers_through_review_and_root_delivery(self):
        stage, run, recovery = self.recover_verification()
        original = recovery.read_bytes()
        review = self.original_review(stage)
        report, _ = self.f.assemble(
            stage, reviews=[review], status="READY_TO_MERGE", outcome="passed"
        )
        self.assertIn(str(run), json.loads(report.read_text())["verification_notes"])
        result = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "recovered.json",
        )
        self.assertEqual(result["status"], "READY_TO_MERGE")
        self.assertEqual(recovery.read_bytes(), original)

    def test_success_delivers_exact_bytes_and_controller_accepts(self):
        stage = self.f.stage()
        review = self.f.review(stage)
        report, _ = self.f.assemble(
            stage, reviews=[review], status="READY_TO_MERGE", outcome="passed"
        )
        output = self.f.root.parent / "delivered.json"
        receipt = self.f.call("final-deliver", "--dispatch", self.f.root, "--output", output)
        self.assertEqual(output.read_bytes(), report.read_bytes())
        self.f.h.report, self.f.h.receipt = output, output.with_name("delivered-receipt.json")
        self.f.h.accept()
        self.assertEqual(receipt["status"], "READY_TO_MERGE")

    def test_review_requires_real_gates(self):
        stage = self.f.stage()
        self.f.call("review-prepare", "--dispatch", stage, ok=False)

    def test_latest_failure_and_missing_log_cannot_support_review(self):
        stage = self.f.stage()
        self.gates(stage)
        self.run_gate(stage, "gate-full", failed=True)
        self.f.call("review-prepare", "--dispatch", stage, ok=False)
        run = self.run_gate(stage, "gate-full")
        (run / "output.log").unlink()
        self.f.call("review-prepare", "--dispatch", stage, ok=False)

    def test_fix_and_review_pipeline(self):
        stage = self.f.stage()
        _, receipt = self.f.assemble(
            stage, reviews=[self.f.review(stage, blocking=True)], outcome="code_failure"
        )
        following = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        source = self.f.done_fixer(following.parent / "fixer/dispatch.json")
        report, _ = self.f.assemble(
            following,
            reviews=[self.f.review(following)],
            fixes=[source],
            status="READY_TO_MERGE",
            outcome="passed",
        )
        self.f.h.deliver(json.loads(report.read_text()))
        self.f.h.accept()

    def test_missing_log_can_deliver_partial_blocked(self):
        stage = self.f.stage()
        run = self.run_gate(stage)
        (run / "output.log").unlink()
        report, _ = self.f.assemble(stage, outcome="blocked")
        self.assertTrue(json.loads(report.read_text())["verification_issues"])
        result = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "blocked.json",
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_six_stage_models_and_success_reach_strict_root_acceptance(self):
        self.f.six_stage_pipeline_uses_exact_models_and_final_pass_reaches_root_acceptance()

    def test_six_code_failure_stages_deliver_only_at_limit(self):
        stage = self.f.stage()
        for number in range(6):
            fixes = [self.f.done_fixer(stage.parent / "fixer/dispatch.json")] if number else []
            _, receipt = self.f.assemble(
                stage,
                reviews=[self.f.review(stage, blocking=True)],
                fixes=fixes,
                outcome="code_failure",
            )
            self.f.call(
                "final-deliver",
                "--dispatch",
                self.f.root,
                "--output",
                self.f.root.parent / f"failure-{number}.json",
                ok=number == 5,
            )
            if number < 5:
                stage = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        self.f.stage(previous=stage, receipt=receipt, continuation="repair", ok=False)

    def test_three_fixer_repairs_are_required_before_advancing(self):
        stage = self.f.stage()
        _, receipt = self.f.assemble(stage, outcome="code_failure", failed_gate="gate-full")
        following = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        fd = following.parent / "fixer/dispatch.json"
        original = self.original_fixer(fd)
        draft = json.loads(Path(original["report"]["path"]).read_text())
        draft.update(status="BLOCKED", outcome="code_failure", blockers=["候选代码验证仍失败"])
        for number in range(4):
            run = self.run_gate(fd, failed=True)
            if number < 3:
                self.f.call("begin-gate-repair", "--dispatch", fd, "--failure", run / "result.json")
        draft["verification_notes"] = {}
        path = fd.parent / "failure-draft.json"
        self.f.put(path, {k: draft[k] for k in draft_contracts.schema("fixer")["properties"]})
        result = self.f.call(
            "fixer-assemble",
            "--dispatch",
            fd,
            "--draft",
            path,
            "--output",
            fd.parent / "failed.json",
        )
        rp = fd.parent / "failed-receipt.json"
        self.f.put(rp, result)
        cp = closure_source(fd, result["report_path"])
        source = self.f.call(
            "fixer-accept",
            "--dispatch",
            following,
            "--report",
            result["report_path"],
            "--receipt",
            rp,
            "--closure",
            cp,
        )["source"]
        _, receipt = self.f.assemble(following, outcome="code_failure", fixes=[source])
        next_stage = self.f.stage(previous=following, receipt=receipt, continuation="repair")
        self.assertEqual(json.loads(next_stage.read_text())["stage"], 2)

    def test_controller_requires_observed_closure(self):
        stage = self.f.stage()
        report, _ = self.f.assemble(
            stage, reviews=[self.f.review(stage)], status="READY_TO_MERGE", outcome="passed"
        )
        target = self.f.root.parent / "root.json"
        self.f.call("final-deliver", "--dispatch", self.f.root, "--output", target)
        result = self.f.h.call(
            "accept",
            "--dispatch",
            self.f.root,
            "--report",
            target,
            "--receipt",
            target.with_name("root-receipt.json"),
            "--output",
            target.parent / "accept.json",
            ok=False,
        )
        self.assertIn("收尾", result["error"])

    def test_no_change_batch_still_requires_gates_and_review(self):
        # 新 root 固定 reviewed_main=HEAD；fixture 无前序 stage，不制造新 commit。
        self.f.h.h.git(self.f.h.primary, "merge", "--ff-only", self.f.h.h.head)
        self.f.h.h.base = self.f.h.h.head
        self.f.h.prepare("finalizer")
        self.f.root = self.f.h.dispatch
        stage = self.f.stage()
        evidence = stage.parent / "acceptance.json"
        self.f.put(evidence, [{"criterion": "全部已有行为", "evidence": "当前实现与实际验证"}])
        collection = self.f.review(stage, evidence=evidence)
        report, _ = self.f.assemble(
            stage, reviews=[collection], status="READY_TO_MERGE", outcome="passed"
        )
        result = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "existing.json",
        )
        self.assertEqual(result["status"], "READY_TO_MERGE")


if __name__ == "__main__":
    unittest.main()

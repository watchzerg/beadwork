"""交接契约负例：公开 CLI、临时 Git worktree 与真实验证采集。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import pytest

import draft_contracts
import evidence
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

    def historical_auxiliary(self, stage, failed=False, unknown=False):
        # 构造旧采集器允许的辅助记录，重算绑定；不改动真实执行证据。
        run = self.run_gate(stage, failed=failed)
        start = json.loads((run / "started.json").read_text())
        start["argv"][-1] = "gate-core"
        self.f.put(run / "started.json", start)
        result = json.loads((run / "result.json").read_text())
        result["started_sha256"] = evidence.digest(run / "started.json")
        self.f.put(run / "result.json", result)
        if unknown:
            (run / "result.json").unlink()
        return run

    def test_historical_auxiliary_and_full_survive_delivery(self):
        stage = self.f.stage()
        auxiliary = self.historical_auxiliary(stage)
        original = (auxiliary / "started.json").read_bytes()
        self.f.call("review-prepare", "--dispatch", stage, ok=False)
        self.gates(stage)
        review = self.original_review(stage)
        report, _ = self.f.assemble(
            stage, reviews=[review], status="READY_TO_MERGE", outcome="passed"
        )
        value = json.loads(report.read_text())
        self.assertEqual([v["gate"] for v in value["verification"]], ["gate-core", "gate-full"])
        self.assertEqual(len(value["verification_sources"]), 2)
        self.assertEqual((auxiliary / "started.json").read_bytes(), original)
        result = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "mixed.json",
        )
        self.assertEqual(result["status"], "READY_TO_MERGE")

    def test_later_auxiliary_failure_requires_new_full_run(self):
        stage = self.f.stage()
        self.gates(stage)
        self.historical_auxiliary(stage, failed=True)
        error = self.f.call("review-prepare", "--dispatch", stage, ok=False)
        self.assertIn("之后存在失败", error["error"])
        self.gates(stage)
        self.original_review(stage)

    def test_auxiliary_failure_cannot_authorize_repair_stage(self):
        stage = self.f.stage()
        self.historical_auxiliary(stage, failed=True)
        error = self.f.assemble(stage, outcome="code_failure", ok=False)
        self.assertIn("代码失败须有", error["error"])

    def test_unknown_auxiliary_requires_bound_recovery_note(self):
        stage = self.f.stage()
        run = self.historical_auxiliary(stage, unknown=True)
        self.gates(stage)
        error = self.f.call("review-prepare", "--dispatch", stage, ok=False)
        self.assertIn("收尾说明", error["error"])
        draft = self.f.draft("BLOCKED", "interrupted")
        draft["verification_notes"] = {str(run): "已确认历史辅助命令结束，完整门禁已重跑。"}
        path = stage.parent / "auxiliary-recovery.json"
        self.f.put(path, draft)
        self.f.call(
            "final-assemble",
            "--dispatch",
            stage,
            "--draft",
            path,
            "--output",
            stage.parent / "recovery.json",
        )
        self.original_review(stage)

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

    def test_controller_accepts_raw_closure_stdout_and_rejects_extra_fields(self):
        stage = self.f.stage()
        self.f.assemble(
            stage, reviews=[self.f.review(stage)], status="READY_TO_MERGE", outcome="passed"
        )
        target = self.f.root.parent / "root.json"
        self.f.call("final-deliver", "--dispatch", self.f.root, "--output", target)
        observation = target.parent / "observation.json"
        self.f.put(
            observation,
            {
                "task_id": "finalizer",
                "stopped": True,
                "observed_at": "2026-09-17T00:00:00Z",
                "evidence": "测试子进程已退出",
                "unresolved": [],
            },
        )
        raw = subprocess.run(
            [
                sys.executable,
                "-B",
                str(fixture.OPS),
                "executor",
                "handoff-close",
                "--dispatch",
                str(self.f.root),
                "--report",
                str(target),
                "--input",
                str(observation),
            ],
            env=self.f.h.env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(raw.returncode, 0, raw.stderr)
        cp = target.parent / "closure-stdout.json"
        cp.write_text(raw.stdout)
        output = target.parent / "accepted.json"
        args = (
            "accept",
            "--dispatch",
            self.f.root,
            "--report",
            target,
            "--receipt",
            target.with_name("root-receipt.json"),
            "--closure",
            cp,
            "--output",
            output,
        )
        valid = json.loads(raw.stdout)
        for invalid in (
            dict(valid, extra=True),
            {"closure_source": dict(valid["closure_source"], extra=True)},
            {"closure_source": None},
        ):
            self.f.put(cp, invalid)
            self.f.h.call(*args, ok=False)
            self.assertFalse(output.exists())
        cp.write_text(raw.stdout)
        self.f.h.call(*args)
        self.assertEqual(json.loads(output.read_text())["closure_source"], valid["closure_source"])

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

    def test_same_stage_cannot_open_second_review(self):
        stage = self.f.stage()
        self.f.review(stage, blocking=True)
        self.f.call("review-prepare", "--dispatch", stage, ok=False)

    def test_final_draft_cannot_inject_sources_or_git_identity(self):
        stage = self.f.stage()
        before = set(self.f.root.parent.glob("checkpoint-*"))
        draft = self.f.draft("BLOCKED", "blocked")
        draft["fix_sources"] = []
        path = stage.parent / "injected-draft.json"
        self.f.put(path, draft)
        output = stage.parent / "injected-report.json"
        error = self.f.call(
            "final-assemble", "--dispatch", stage, "--draft", path, "--output", output, ok=False
        )
        self.assertIn("fix_sources", error["error"])
        self.assertFalse(output.exists())
        self.assertEqual(set(self.f.root.parent.glob("checkpoint-*")), before)

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

    def test_unknown_final_uses_bound_recovery_notes(self):
        stage, _, recovery = self.recover_verification(unknown=True)
        original = recovery.read_bytes()
        recovery.write_text("{}")
        self.f.call("review-prepare", "--dispatch", stage, ok=False)
        recovery.write_bytes(original)
        self.assertTrue(self.f.call("review-prepare", "--dispatch", stage)["axes"])

    def test_final_assemble_uses_checkpoint_selected_sources(self):
        stage = self.f.stage()
        review = self.f.review(stage)
        report, _ = self.f.assemble(
            stage, reviews=[review], status="READY_TO_MERGE", outcome="passed", implicit=True
        )
        data = json.loads(report.read_text())
        self.assertEqual(data["review_sources"], [evidence.binding(review)])
        self.assertEqual(data["fix_sources"], [])

    def test_fixer_code_failure_requires_recorded_exhaustion(self):
        stage = self.f.stage()
        _, receipt = self.f.assemble(stage, outcome="code_failure", failed_gate="gate-full")
        stage = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        source = self.f.done_fixer(stage.parent / "fixer/dispatch.json")
        report = json.loads(Path(source["report"]["path"]).read_text())
        report.update(
            status="BLOCKED", outcome="code_failure", verification=[], blockers=["代码失败"]
        )
        path = stage.parent / "fixer/negative.json"
        self.f.put(path, report)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(fixture.OPS),
                "verify",
                "worker",
                "--check-report",
                "fixer",
                str(path),
                "--expected",
                str(stage.parent / "fixer/dispatch.json"),
            ],
            text=True,
            capture_output=True,
        )
        self.assertTrue(result.returncode != 0 or not json.loads(result.stdout)["ok"])

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

    def test_collected_blocking_review_cannot_be_omitted(self):
        stage = self.f.stage()
        self.f.review(stage, blocking=True)
        error = self.f.assemble(stage, outcome="interrupted", ok=False)
        self.assertIn("review", error["error"])

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

    def test_collect_before_assembly_survives_resume(self):
        stage = self.f.stage()
        collection = self.f.review(stage)
        source = self.f.h.root / "resume.json"
        self.f.put(source, {"previous_stage": str(stage), "continuation": "resume"})
        result = self.f.call("final-stage", "--dispatch", self.f.root, "--input", source)
        self.assertEqual(result["selected_review"], self.f.bind(collection))
        self.assertEqual(result["stage_path"], str(stage))
        self.assertIsNone(result["fixer_dispatch"])

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

    def test_missing_started_can_deliver_partial_blocked(self):
        stage = self.f.stage()
        run = self.run_gate(stage)
        (run / "started.json").unlink()
        report, _ = self.f.assemble(stage, outcome="blocked")
        value = json.loads(report.read_text())
        self.assertIsNone(value["verification_issues"][0]["verification_sources"][0]["started"])
        result = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "missing-started.json",
        )
        self.assertEqual(result["status"], "BLOCKED")

    def test_accepted_fixer_log_damage_can_deliver_partial_blocked(self):
        stage = self.f.stage()
        _, receipt = self.f.assemble(stage, outcome="code_failure", failed_gate="gate-full")
        following = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        fd = following.parent / "fixer/dispatch.json"
        source = self.f.done_fixer(fd)
        next(fd.parent.glob("verification-*/output.log")).write_text("损坏日志")
        report, receipt = self.f.assemble(following, fixes=[source], outcome="blocked")
        value = json.loads(report.read_text())
        self.assertTrue(
            any(i["dispatch"] == source["dispatch"] for i in value["verification_issues"])
        )
        self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "damaged.json",
        )
        self.f.stage(previous=following, receipt=receipt, continuation="repair", ok=False)

    def test_six_stage_models_and_success_reach_strict_root_acceptance(self):
        self.f.six_stage_pipeline_uses_exact_models_and_final_pass_reaches_root_acceptance()

    def test_fixer_upgrade_inherits_and_resume_preserves_model(self):
        stage = self.f.stage()
        self.f.assemble(
            stage, reviews=[self.f.review(stage, blocking=True)], outcome="code_failure"
        )

        def prepare(facts, ok=True):
            source = self.f.h.root / "model-facts.json"
            self.f.put(source, facts)
            return self.f.call("final-stage", "--dispatch", self.f.root, "--input", source, ok=ok)

        sm = {"model": "gpt-6-sol", "reasoning_effort": "high"}
        facts = {"continuation": "repair", "model_overrides": {"fixer": sm}}
        prepare(facts, ok=False)
        prepare(
            dict(
                facts,
                model_overrides={"fixer": {"model": "gpt-6-astra", "reasoning_effort": "medium"}},
                model_override_reason="不允许的档位",
            ),
            ok=False,
        )
        result = prepare(dict(facts, model_override_reason="跨模块修复提前升档"))
        stage = Path(result["stage_path"])
        self.assertEqual(result["models"]["fixer"], sm)
        resumed = prepare({"continuation": "resume"})
        self.assertEqual(resumed["stage_path"], str(stage))
        self.assertEqual(resumed["models"]["fixer"], sm)
        fix = self.f.done_fixer(stage.parent / "fixer/dispatch.json")
        self.f.assemble(
            stage,
            reviews=[self.f.review(stage, blocking=True)],
            fixes=[fix],
            outcome="code_failure",
        )
        prepare(
            dict(
                facts,
                model_overrides={"fixer": {"model": "gpt-6-sol", "reasoning_effort": "medium"}},
                model_override_reason="不应降档",
            ),
            ok=False,
        )
        result = prepare({"continuation": "repair"})
        self.assertEqual(result["stage"], 2)
        self.assertEqual(result["models"]["fixer"], sm)

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

    def test_fixer_stage_cannot_advance_on_unrelated_old_failure(self):
        stage = self.f.stage()
        _, receipt = self.f.assemble(stage, outcome="code_failure", failed_gate="gate-full")
        following = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        self.f.assemble(following, outcome="code_failure", ok=False)

    def test_context_is_append_only_and_survives_resume(self):
        stage = self.f.stage()
        source = stage.parent / "facts.txt"
        source.write_text("补充的可查询事实")
        request = self.f.root.parent / "context-add-input-000003.json"
        self.f.put(request, {"sources": [self.f.bind(source)], "reason": "补齐现有需求事实"})
        answer = self.f.call("context-add", "--dispatch", stage, "--input", request)
        facts = stage.parent / "resume.json"
        self.f.put(facts, {})
        restored = self.f.call("final-stage", "--dispatch", self.f.root, "--input", facts)
        self.assertEqual(restored["context_sources"], [answer["context_source"]])
        self.assertEqual(restored["stage"], 0)
        source.write_text("内容变化")
        self.f.call("final-stage", "--dispatch", self.f.root, "--input", facts, ok=False)

    def test_gate_full_rejects_boundary_parameters(self):
        stage = self.f.stage()
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(fixture.OPS),
                "run-verification",
                "--dispatch",
                str(stage),
                "--recipe",
                "gate-full",
                "--delivery",
                "--",
                "gate-core",
            ],
            cwd=self.f.h.root,
            env=self.f.h.env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("不接受筛选参数", result.stderr)
        self.gates(stage)
        self.original_review(stage)

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

    def test_review_dispatch_has_writer_and_only_own_prior_axis(self):
        stage = self.f.stage()
        initial = self.f.review(stage, blocking=True)
        _, receipt = self.f.assemble(stage, reviews=[initial], outcome="code_failure")
        following = self.f.stage(previous=stage, receipt=receipt, continuation="repair")
        fixer = self.f.done_fixer(following.parent / "fixer/dispatch.json")
        prepared = self.f.call("review-prepare", "--dispatch", following)
        previous = json.loads(initial.read_text())
        for axis, path in prepared["axes"].items():
            d = json.loads(Path(path).read_text())
            self.assertEqual(d["writer_source"], fixer)
            self.assertNotIn("verification_sources", d)
            view = json.loads(Path(d["verification_view_source"]["path"]).read_text())
            self.assertTrue(view["selected_sources"])
            self.assertEqual(d["prior_axis_source"], previous["sources"][axis])

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

    def test_review_prepare_interruption_reuses_reserved_round(self):
        stage = self.f.stage()
        self.gates(stage)
        code = """import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import review_operations
o = review_operations
original = review_operations.evidence.write
def fail(path, value):
    if Path(path).name == 'round.json': raise OSError('模拟 round 写出前中断')
    return original(path, value)
review_operations.evidence.write = fail
o.prepare_review(SimpleNamespace(dispatch=sys.argv[2], evidence=None, resume=False))
"""
        failed = subprocess.run(
            [sys.executable, "-B", "-c", code, str(fixture.OPS.parent), str(stage)],
            text=True,
            capture_output=True,
            env=self.f.h.env,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("模拟 round 写出前中断", failed.stderr)
        before = set(stage.parent.glob("review-*"))
        resumed = self.f.call("review-prepare", "--dispatch", stage, "--resume")
        self.assertEqual(set(stage.parent.glob("review-*")), before)
        self.assertEqual(Path(resumed["round_path"]).parent, next(iter(before)))

    def test_stage_zero_review_receives_shared_verification_view(self):
        stage = self.f.stage()
        self.gates(stage)
        prepared = self.f.call("review-prepare", "--dispatch", stage)
        sources = set()
        for path in prepared["axes"].values():
            d = json.loads(Path(path).read_text())
            self.assertIsNone(d["writer_source"])
            self.assertNotIn("verification_sources", d)
            sources.add(
                (d["verification_view_source"]["path"], d["verification_view_source"]["sha256"])
            )
            view = json.loads(Path(d["verification_view_source"]["path"]).read_text())
            self.assertEqual(len(view["entries"]), 1)
            self.assertEqual(len(view["selected_sources"]), 1)
        self.assertEqual(len(sources), 1)

    def test_same_round_correction_invalidates_old_stage(self):
        stage = self.f.stage()
        collection = self.f.review(stage, blocking=True)
        report, _ = self.f.assemble(stage, reviews=[collection], outcome="code_failure")
        original = report.read_bytes()
        data = json.loads(collection.read_text())
        selection = {}
        for axis, source in data["sources"].items():
            old = Path(source["report"]["path"])
            value = json.loads(old.read_text())
            value["findings"] = []
            new = old.with_name("corrected.json")
            self.f.put(new, value)
            receipt = old.with_name("corrected-receipt.json")
            self.f.put(
                receipt,
                {
                    "status": "COMPLETED",
                    "report_path": str(new),
                    "report_sha256": self.f.bind(new)["sha256"],
                },
            )
            cp = closure_source(old.parent / "dispatch.json", new)
            selection[axis] = {
                "report": str(new),
                "receipt": str(receipt),
                "closure": json.loads(cp.read_text())["path"],
            }
        request = collection.parent / "correction.json"
        self.f.put(request, selection)
        fixed = collection.parent / "corrected-collection.json"
        self.f.call(
            "review-collect",
            "--round",
            data["round"]["path"],
            "--input",
            request,
            "--output",
            fixed,
        )
        self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "stale.json",
            ok=False,
        )
        draft = stage.parent / "fixed-draft.json"
        self.f.put(draft, self.f.draft("READY_TO_MERGE", "passed"))
        fixes = stage.parent / "empty-fixes.json"
        self.f.put(fixes, [])
        self.f.call(
            "final-assemble",
            "--dispatch",
            stage,
            "--draft",
            draft,
            "--output",
            stage.parent / "corrected-report.json",
        )
        result = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "corrected-root.json",
        )
        self.assertEqual(result["status"], "READY_TO_MERGE")
        self.assertEqual(report.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()

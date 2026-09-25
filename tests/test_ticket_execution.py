"""通过公开 CLI 验证整票协调、implementer gate-fix、review 和恢复边界。"""

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

import evidence
import test_controller as fixture
import test_executor_operations as review_fixture
import workflow_policy
from fixture_support import closure_source

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts"

pytestmark = pytest.mark.workflow


class TicketExecutionTests(unittest.TestCase):
    def setUp(self):
        self.h: Any = fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.utility_fixture = False
        self.h.prepare(
            mode="new",
            test_mode="direct_verification",
            approved_seams=[],
        )
        self.root_dispatch = self.h.dispatch
        self.serial = 0
        fake = self.h.root / "bin/just"
        fake.write_text(
            "#!"
            + sys.executable
            + "\n"
            + "import os,sys\nif sys.argv[1:] == ['--summary']:\n    print('install test gate-core gate-full'); sys.exit(0)\nassert sys.argv[1:3] == ['--one','--']\nprint('验证结果')\nsys.exit(7 if os.environ.get('FAIL_GATE') == sys.argv[3] else 0)\n"
        )
        fake.chmod(0o755)
        self.stage()

    def cli(self, command, *args, ok=True, env=None):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "beadwork.py"),
                command,
                *map(str, args),
            ],
            cwd=self.h.root,
            env=env or self.h.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def file(self, name, data, folder=None):
        self.serial += 1
        path = (folder or self.h.root) / f"{name}-{self.serial}.json"
        self.h.put(path, data)
        return path

    def stage(self, continuation="resume", ok=True, **facts):
        result = self.cli(
            "executor",
            "ticket-stage",
            "--dispatch",
            self.root_dispatch,
            "--input",
            self.file("facts", dict(continuation=continuation, **facts)),
            ok=ok,
        )
        if ok:
            self.sd = Path(result["stage_dispatch"])
            self.wd = Path(result["implementer_dispatch"])
            self.stage_info = result
            self.assertEqual(
                result["active_stage_context_source"],
                json.loads(self.wd.read_text())["active_stage_context_source"],
            )
            launch = {"fork_turns": "none", "required": True}
            self.assertEqual(result["implementer_launch_context"], launch)
            self.assertEqual(json.loads(self.wd.read_text())["launch_context"], launch)
        return result

    def commit(self):
        self.serial += 1
        (self.h.wt / "ticket.txt").write_text(f"实现 {self.serial}")
        self.h.h.git(self.h.wt, "add", "ticket.txt")
        self.h.h.git(self.h.wt, "commit", "-m", f"test-1 实现 {self.serial}")

    def gate(self, recipe="gate-core", fail=False, delivery=True):
        argv = ["--dispatch", self.wd, "--recipe", recipe]
        if delivery:
            argv.append("--delivery")
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "beadwork.py"),
                "run-verification",
                *map(str, argv),
            ],
            cwd=self.h.root,
            env={
                **self.h.env,
                "FAIL_GATE": recipe if fail else "",
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1 if fail else 0, result.stdout + result.stderr)
        return Path(json.loads(result.stdout)["run_path"]) / "result.json"

    def draft(self, outcome="passed"):
        d = json.loads(self.wd.read_text())
        return {
            "status": "DONE" if outcome == "passed" else "BLOCKED",
            "outcome": outcome,
            "test_plan": {
                "decision_source": "ticket/spec",
                "red_evidence": "实际行为 red" if d["test_mode"] == "TDD" else None,
            },
            "acceptance": [{"criterion": "目标行为", "evidence": "实现与 gate 日志"}],
            "verification": [],
            "requested_context": [],
            "blockers": [] if outcome == "passed" else ["阶段未完成"],
            "concerns": [],
        }

    def implement(self, outcome="passed", ok=True, accept=True, **changes):
        draft = dict(
            self.draft(outcome),
            verification_notes={},
            stopped_tasks=True,
        )
        draft.update(changes)
        output = self.file("unused", {}, self.wd.parent)
        output.unlink()
        receipt = self.cli(
            "executor",
            "implementer-assemble",
            "--dispatch",
            self.wd,
            "--draft",
            self.file("writer-draft", draft),
            "--output",
            output,
            ok=ok,
        )
        if ok:
            rp = self.file("receipt", receipt, self.wd.parent)
            if accept:
                cp = closure_source(self.wd, output)
                self.cli(
                    "executor",
                    "implementer-accept",
                    "--dispatch",
                    self.sd,
                    "--report",
                    output,
                    "--receipt",
                    rp,
                    "--closure",
                    cp,
                )
            self.writer_report, self.writer_receipt = output, rp
        return receipt

    def review(self, blocking=False):
        e = review_fixture.ExecutorOperationsTests()
        e.h, e.dispatch, e.directory = self.h, self.sd, self.sd.parent
        evidence = None
        if (
            self.h.h.git(self.h.wt, "rev-parse", "HEAD")
            == json.loads(self.sd.read_text())["base_commit"]
        ):
            evidence = self.file(
                "acceptance", [{"criterion": "目标行为", "evidence": "现有行为与验证"}]
            )
        return e.collect(e.round(blocking=blocking, evidence=evidence))

    def assemble(self, reviews=(), outcome="passed", ok=True, **changes):
        draft = dict(self.draft(outcome), stopped_tasks=True, **changes)
        output = self.file("unused", {}, self.sd.parent)
        output.unlink()
        argv = [
            "ticket-assemble",
            "--dispatch",
            self.sd,
            "--draft",
            self.file("stage-draft", draft),
            "--output",
            output,
        ]
        result = self.cli("executor", *argv, ok=ok)
        if ok:
            self.stage_report = output
        return result

    def deliver(self, ok=True):
        output = self.file("unused", {}, self.root_dispatch.parent)
        output.unlink()
        receipt = self.cli(
            "executor",
            "ticket-deliver",
            "--dispatch",
            self.root_dispatch,
            "--output",
            output,
            ok=ok,
        )
        if ok:
            rp = self.file("receipt", receipt, output.parent)
            self.root_report, self.root_receipt = output, rp
            self.acceptance = output.parent / ("accepted-" + str(self.serial) + ".json")
            cp = closure_source(self.root_dispatch, output)
            self.cli(
                "controller",
                "accept",
                "--dispatch",
                self.root_dispatch,
                "--report",
                output,
                "--receipt",
                rp,
                "--output",
                self.acceptance,
                "--closure",
                cp,
            )
        return receipt

    def ready_writer(self):
        self.commit()
        self.gate()
        self.implement()

    def exhaust_default_stages(self):
        for stage in range(len(workflow_policy.STAGE_MODELS)):
            self.ready_writer()
            self.assemble([self.review(blocking=True)], "code_failure")
            if stage < len(workflow_policy.STAGE_MODELS) - 1:
                self.stage("repair")

    def evidence_snapshot(self):
        return {
            str(p): evidence.digest(p) for p in self.root_dispatch.parent.rglob("*") if p.is_file()
        }

    def test_full_ticket_and_controller_accept(self):
        self.ready_writer()
        self.assemble([self.review()])
        self.deliver()
        self.stage(ok=False)

    def test_repair_uses_compact_active_stage_context_and_resume_reuses_it(self):
        self.assertIsNone(self.stage_info["active_stage_context_source"])
        self.ready_writer()
        selected = self.review(blocking=True)
        self.assemble([selected], "code_failure")
        self.stage("repair")

        source = self.stage_info["active_stage_context_source"]
        context = json.loads(Path(source["path"]).read_text())
        self.assertEqual(context["continuation"], "repair")
        self.assertEqual(context["from_stage"], 0)
        self.assertEqual(context["stage"], 1)
        self.assertEqual(context["selected_review_source"], evidence.binding(selected))
        self.assertEqual(
            context["blocking_findings"],
            [
                {
                    "axis": "standards",
                    "kind": "defect",
                    "blocking": True,
                    "title": "需处理",
                    "evidence": "原始证据，不改写",
                }
            ],
        )
        self.assertNotIn("review", context)
        self.assertNotIn("verification", context)
        self.assertNotIn("prior_stages", context)
        resumed = self.stage()
        self.assertEqual(resumed["active_stage_context_source"], source)

    def test_no_commit_existing_behavior(self):
        self.gate()
        self.implement()
        self.assemble([self.review()])
        self.deliver()
        self.assertEqual(
            json.loads(self.stage_report.read_text())["delivery_kind"], "already_satisfied"
        )

    def test_same_head_review_failure_can_continue_and_deliver(self):
        base = json.loads(self.sd.read_text())["base_commit"]
        for _ in range(2):
            self.gate()
            self.gate("gate-core")
            self.implement()
            self.assemble([self.review(blocking=True)], "code_failure")
            report = json.loads(self.stage_report.read_text())
            self.assertEqual(report["head_commit"], base)
            self.assertIsNone(report["delivery_kind"])
            self.stage("repair")
        self.gate()
        self.implement()
        self.assemble([self.review()])
        self.deliver()
        report = json.loads(self.root_report.read_text())
        self.assertEqual(report["delivery_kind"], "already_satisfied")
        self.assertEqual(report["review"]["attempts"], 3)

    def test_missing_core_and_stale_head_rejected(self):
        self.commit()
        self.gate("test", delivery=False)
        self.implement(ok=False)
        self.gate()
        self.commit()
        self.implement(ok=False)
        self.gate()
        self.implement()

    def test_ticket_full_rejected_before_execution(self):
        self.commit()
        before = set(self.wd.parent.iterdir())
        for flags in ([], ["--delivery"]):
            rejected = self.cli(
                "run-verification",
                "--dispatch",
                self.wd,
                "--recipe",
                "gate-full",
                *flags,
                ok=False,
            )
            self.assertIn("单票不接受 gate-full", rejected["error"])
        self.assertEqual(set(self.wd.parent.iterdir()), before)

    def test_unfinished_later_delivery_invalidates_prior_success(self):
        self.commit()
        self.gate()
        result = self.gate()
        result.rename(result.with_name("simulated-unpersisted-result.json"))
        notes = {str(result.parent): "已确认旧进程结束；需重新运行。"}
        rejected = self.implement(ok=False, verification_notes=notes)
        self.assertIn("gate-core", rejected["error"])

    def test_six_review_stages_and_models(self):
        reviews = []
        for number in range(6):
            self.assertEqual(self.stage_info["stage"], number)
            expected = [
                ("gpt-6-luna", "high"),
                ("gpt-6-luna", "high"),
                ("gpt-6-sol", "medium"),
                ("gpt-6-sol", "medium"),
                ("gpt-6-sol", "high"),
                ("gpt-6-sol", "high"),
            ][number]
            model = self.stage_info["models"]["implementer"]
            self.assertEqual((model["model"], model["reasoning_effort"]), expected)
            for axis, effort in (
                ("standards", "medium" if number < 3 else "high"),
                ("spec", "medium" if number == 0 else "high"),
            ):
                self.assertEqual(
                    self.stage_info["models"][axis],
                    {"model": "gpt-6-sol", "reasoning_effort": effort},
                )
            self.ready_writer()
            reviews.append(self.review(blocking=number < 5))
            self.assemble(reviews, "code_failure" if number < 5 else "passed")
            if number < 5:
                self.deliver(ok=False)
                self.stage("repair")
        self.deliver()
        self.stage("repair", ok=False)
        self.assertEqual(self.stage_info["models"]["implementer"]["model"], "gpt-6-sol")

    def test_gate_exhaustion_advances_only_after_three_repairs(self):
        self.commit()
        failure = self.gate(fail=True)
        self.implement("code_failure", ok=False)
        for number in range(3):
            result = self.cli(
                "executor",
                "begin-gate-repair",
                "--dispatch",
                self.wd,
                "--failure",
                failure,
            )
            self.assertEqual(result["repair_number"], number + 1)
            self.stage()
            self.commit()
            failure = self.gate(fail=True)
        self.implement("code_failure")
        self.assemble(outcome="code_failure")
        self.stage(ok=False)
        self.stage("repair")
        self.assertEqual(self.stage_info["stage"], 1)
        context = json.loads(
            Path(self.stage_info["active_stage_context_source"]["path"]).read_text()
        )
        self.assertEqual(context["continuation"], "repair")
        self.assertEqual(context["blocking_findings"], [])
        self.assertEqual(
            context["previous_implementer_source"]["report"]["path"],
            str(self.writer_report),
        )
        failure = self.gate(fail=True)
        result = self.cli(
            "executor",
            "begin-gate-repair",
            "--dispatch",
            self.wd,
            "--failure",
            failure,
        )
        self.assertEqual(result["repair_number"], 1)

    def test_unregistered_gate_repair_recovery_advances_with_append_only_record(self):
        self.commit()
        failure = self.gate(fail=True)
        self.cli(
            "executor",
            "begin-gate-repair",
            "--dispatch",
            self.wd,
            "--failure",
            failure,
        )
        self.gate()
        candidate = self.h.h.git(self.h.wt, "rev-parse", "HEAD")
        self.commit()
        recovered = self.h.h.git(self.h.wt, "rev-parse", "HEAD")
        self.implement("blocked")
        self.assemble(outcome="blocked")

        result = self.stage("recover", recovery_reason="修正提交早于第二次 begin-gate-repair 登记")

        self.assertEqual(result["stage"], 1)
        dispatch = json.loads(self.sd.read_text())
        context = json.loads(Path(result["active_stage_context_source"]["path"]).read_text())
        self.assertEqual(context["continuation"], "recover")
        self.assertEqual(context["transition_evidence"]["recovery"], dispatch["stage_recovery"])
        self.assertEqual(dispatch["stage_base"], recovered)
        recovery_path = Path(dispatch["stage_recovery"]["path"])
        recovery = json.loads(recovery_path.read_text())
        self.assertEqual(
            recovery["previous_candidate"]["path"],
            str(recovery_path.parent / "gate-repair-candidate.json"),
        )
        self.assertEqual(
            json.loads(Path(recovery["previous_candidate"]["path"]).read_text())["head"], candidate
        )
        self.assertEqual(recovery["recovered_head"], recovered)
        checkpoint = sorted(self.root_dispatch.parent.glob("checkpoint-*.json"))[-1]
        self.assertEqual(len(json.loads(checkpoint.read_text())["state"]["stage_sources"]), 1)

        self.ready_writer()
        self.assemble([self.review(blocking=True)], "code_failure")
        self.stage("repair")
        self.assertEqual(self.stage_info["stage"], 2)
        self.ready_writer()
        self.assemble([self.review()])
        self.deliver()

    def test_interruption_and_executor_resume_preserve_stage_and_dirty_work(self):
        (self.h.wt / "unfinished.txt").write_text("保留")
        self.implement("interrupted")
        self.assemble(outcome="interrupted")
        self.deliver()
        d = json.loads(self.root_dispatch.read_text())
        d.update(mode="resume", previous_dispatch=str(self.root_dispatch))
        result = self.cli("controller", "prepare", "executor", "--input", self.file("resume", d))
        self.assertEqual(result["dispatch_path"], str(self.root_dispatch))
        old = self.wd
        self.stage()
        self.assertEqual(old, self.wd)
        self.assertEqual((self.h.wt / "unfinished.txt").read_text(), "保留")
        self.stage("repair", ok=False)

    def test_baseline_adaptation_stays_in_stage_and_preserves_writer_history(self):
        # 从 direct verification 恢复 TDD 必须有已批准 seam，因此使用新的原始 TDD ticket。
        self.h.prepare(
            mode="new",
            test_mode="TDD",
            approved_seams=["S1"],
        )
        self.root_dispatch = self.h.dispatch
        self.stage()
        self.gate("test", delivery=False)
        original = self.wd
        result = self.cli(
            "executor",
            "ticket-adapt-plan",
            "--dispatch",
            self.sd,
            "--input",
            self.file(
                "adapt",
                {
                    "mode": "direct_verification",
                    "reason": "BASE 已满足行为",
                    "acceptance": [{"criterion": "目标行为", "evidence": "BASE 实现"}],
                    "verification": [{"command": "just test", "result": "BASE 通过"}],
                },
            ),
        )
        self.sd, self.wd = Path(result["stage_dispatch"]), Path(result["implementer_dispatch"])
        self.assertIn(str(original), json.loads(self.wd.read_text())["verification_dispatches"])
        self.gate()
        self.implement()
        self.assemble([self.review()])
        self.deliver()

    def test_latest_failed_gate_cannot_be_hidden_by_earlier_pass(self):
        self.commit()
        self.gate()
        self.gate(fail=True)
        self.implement(ok=False)

    def test_selected_blocking_review_cannot_be_omitted_after_assembly(self):
        self.ready_writer()
        review = self.review(blocking=True)
        self.assemble([review], "code_failure")
        original = self.stage_report.read_bytes()
        self.assemble(outcome="interrupted", ok=False)
        self.assertEqual(self.stage_report.read_bytes(), original)
        self.stage("repair")

    def test_collected_review_survives_resume_before_stage_assembly(self):
        self.ready_writer()
        review = self.review(blocking=True)
        self.stage()
        self.assertEqual(self.stage_info["selected_review"]["path"], str(review))
        self.assemble(outcome="interrupted", ok=False)
        self.assemble([review], "code_failure")
        self.stage("repair")

    def test_missing_log_can_deliver_partial_blocked_implementation(self):
        self.commit()
        self.gate()
        log = next(self.wd.parent.glob("verification-*/output.log"))
        log.unlink()
        self.implement("blocked")
        report = json.loads(self.writer_report.read_text())
        self.assertEqual(report["outcome"], "blocked")
        self.assertTrue(report["verification_issues"])
        self.assemble(outcome="blocked")
        self.deliver()

    def test_historical_implementation_coverage_uses_bound_snapshot(self):
        import implementer_reports

        self.commit()
        self.gate()
        self.implement(accept=False)
        # 同 HEAD 后续失败只进入新报告；原报告的固定来源仍可独立验收。
        original = evidence.read(self.writer_report)
        self.gate(fail=True)
        d = evidence.read(self.wd)
        with patch.dict(os.environ, self.h.env):
            implementer_reports.check_implementation(d, original)
            with self.assertRaisesRegex(ValueError, "全部验证来源"):
                implementer_reports.check_implementation(d, original, live=True)

    def test_same_head_review_correction_keeps_stage_and_original(self):
        self.ready_writer()
        first = self.review(blocking=True)
        self.assemble([first], "code_failure")
        original = self.stage_report.read_bytes()
        collection = json.loads(first.read_text())
        selection = {}
        for axis, fields in collection["sources"].items():
            path = Path(fields["report"]["path"])
            report = json.loads(path.read_text())
            report["findings"] = []
            target = self.file("corrected", report, path.parent)
            receipt = self.file(
                "receipt",
                {
                    "status": "COMPLETED",
                    "report_path": str(target),
                    "report_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                },
                path.parent,
            )
            cp = closure_source(path.parent / "dispatch.json", target)
            selection[axis] = {
                "report": str(target),
                "receipt": str(receipt),
                "closure": json.loads(cp.read_text())["path"],
            }
        selected = self.file("selection", selection)
        target = first.parent / "collection-corrected.json"
        self.cli(
            "executor",
            "review-collect",
            "--round",
            collection["round"]["path"],
            "--input",
            selected,
            "--output",
            target,
        )
        old_report = self.stage_report
        self.deliver(ok=False)
        self.stage("repair", ok=False)
        self.assemble([first], "code_failure", ok=False)
        self.assemble([target])
        self.deliver()
        self.assertEqual(old_report.read_bytes(), original)
        self.assertEqual(json.loads(self.stage_report.read_text())["stage"], 0)

    def test_model_upgrade_inherits_and_downgrade_is_rejected(self):
        self.ready_writer()
        self.assemble([self.review(blocking=True)], "code_failure")
        upgraded = {"model": "gpt-6-sol", "reasoning_effort": "high"}
        self.stage(
            "repair", model_overrides={"implementer": upgraded}, model_override_reason="契约分歧"
        )
        self.ready_writer()
        reviews = json.loads(self.sd.read_text())["prior_reviews"]
        current = self.review(blocking=True)
        self.assemble([Path(item["path"]) for item in reviews] + [current], "code_failure")
        self.stage(
            "repair",
            ok=False,
            model_overrides={"implementer": {"model": "gpt-6-luna", "reasoning_effort": "high"}},
            model_override_reason="不应降档",
        )
        self.stage("repair")
        self.assertEqual(self.stage_info["models"]["implementer"], upgraded)

    def test_sealed_gate_failure_cannot_be_replaced_with_interruption(self):
        self.commit()
        failure = self.gate(fail=True)
        for _ in range(3):
            self.cli(
                "executor",
                "begin-gate-repair",
                "--dispatch",
                self.wd,
                "--failure",
                failure,
            )
            failure = self.gate(fail=True)
        self.implement("code_failure")
        self.assemble(outcome="code_failure")
        self.implement("interrupted", accept=False)
        self.cli(
            "executor",
            "implementer-accept",
            "--dispatch",
            self.sd,
            "--report",
            self.writer_report,
            "--receipt",
            self.writer_receipt,
            ok=False,
        )
        self.assemble(outcome="interrupted", ok=False)
        self.stage(ok=False)
        self.stage("repair")

    def test_completion_distinguishes_ticket_core_from_final_full(self):
        self.commit()
        self.gate()
        self.implement()
        self.assemble([self.review()])
        self.deliver()
        path = self.root_dispatch.parent / "completion.md"
        self.cli(
            "controller",
            "comment",
            "--acceptance",
            self.acceptance,
            "--summary",
            "完成",
            "--output",
            path,
        )
        text = path.read_text()
        self.assertIn("交付阶段：0", text)
        self.assertNotIn("本阶段模型：", text)
        self.assertNotIn("阶段与实现来源：", text)
        self.assertNotIn("验证记录：", text)
        self.assertIn('本票完整 gate 义务与实测：[{"gate": "gate-core", "result": "通过"}]', text)
        self.assertIn("完整项目回归由 parent finalize 的 gate-full 验收。", text)

    def test_six_gate_failure_stages_stop_at_limit(self):
        for stage in range(6):
            self.commit()
            failure = self.gate(fail=True)
            for _ in range(3):
                self.cli(
                    "executor",
                    "begin-gate-repair",
                    "--dispatch",
                    self.wd,
                    "--failure",
                    failure,
                )
                self.commit()
                failure = self.gate(fail=True)
            self.implement("code_failure")
            self.assemble(outcome="code_failure")
            if stage < 5:
                self.stage("repair")
        self.deliver()
        self.stage("repair", ok=False)
        extended = self.stage(
            "extend", additional_stages=5, extension_reason="用户明确授权最多五个新修复 stage"
        )
        self.assertEqual(extended["stage"], 6)
        dispatch = json.loads(self.sd.read_text())
        self.assertEqual(dispatch["stage_limit"], 10)
        self.assertEqual(
            dispatch["models"]["implementer"],
            {"model": "gpt-6-astra", "reasoning_effort": "medium"},
        )
        extension = json.loads(Path(dispatch["stage_extension"]["path"]).read_text())
        self.assertEqual(extension["additional_stages"], 5)
        self.assertEqual(extension["models"], dispatch["models"])
        self.assertEqual(
            list(dispatch["models"].values()),
            [{"model": "gpt-6-astra", "reasoning_effort": "medium"}] * 3,
        )
        self.ready_writer()
        self.assemble([self.review(blocking=True)], "code_failure")
        self.deliver(ok=False)
        self.stage("repair")
        continued = evidence.read(self.sd)
        self.assertEqual(continued["stage_limit"], dispatch["stage_limit"])
        self.assertEqual(continued["stage_extension"], dispatch["stage_extension"])
        self.assertEqual(continued["models"], dispatch["models"])
        stage_dispatch = self.sd
        before = self.evidence_snapshot()
        self.stage()
        self.assertEqual(self.sd, stage_dispatch)
        self.assertEqual(self.evidence_snapshot(), before)
        self.ready_writer()
        self.assemble([self.review()])
        self.deliver()

    def test_extension_rejects_invalid_inputs_before_writing_and_stops_after_one(self):
        self.exhaust_default_stages()
        before = self.evidence_snapshot()
        cases = [{"additional_stages": n, "extension_reason": "明确授权"} for n in (0, 6, True)] + [
            {"additional_stages": 1},
            {"additional_stages": 1, "extension_reason": " "},
            {
                "additional_stages": 1,
                "extension_reason": "明确授权",
                "model_overrides": {"unknown": {}},
            },
            {"additional_stages": 1, "extension_reason": "明确授权", "recovery_reason": "错误字段"},
        ]
        for facts in cases:
            with self.subTest(facts=facts):
                self.stage("extend", ok=False, **facts)
                self.assertEqual(self.evidence_snapshot(), before)
        self.stage("extend", additional_stages=1, extension_reason="用户明确追加一个 stage")
        context = json.loads(
            Path(self.stage_info["active_stage_context_source"]["path"]).read_text()
        )
        self.assertEqual(context["continuation"], "extend")
        self.assertEqual(
            context["transition_evidence"]["extension"],
            json.loads(self.sd.read_text())["stage_extension"],
        )
        self.ready_writer()
        self.assemble([self.review(blocking=True)], "code_failure")
        self.deliver()
        before = self.evidence_snapshot()
        self.stage("repair", ok=False)
        error = self.stage("extend", additional_stages=1, extension_reason="再次申请", ok=False)
        self.assertIn("仅允许追加一次", error["error"])
        self.assertEqual(self.evidence_snapshot(), before)

    def test_extension_model_override_is_bound_and_survives_repair_and_resume(self):
        self.exhaust_default_stages()
        overrides = {
            "implementer": {"model": "gpt-6-astra", "reasoning_effort": "high"},
            "standards": {"model": "gpt-6-sol", "reasoning_effort": "high"},
        }
        before = self.evidence_snapshot()
        self.stage(
            "extend",
            additional_stages=2,
            extension_reason="用户授权",
            model_overrides={"implementer": workflow_policy.MODEL_LEVELS[1]},
            model_override_reason="不允许低于此前档位",
            ok=False,
        )
        self.assertEqual(self.evidence_snapshot(), before)
        self.stage(
            "extend",
            additional_stages=2,
            extension_reason="用户授权追加两阶段",
            model_overrides=overrides,
            model_override_reason="用户指定实现与审查配置",
        )
        selected = self.stage_info["models"]
        self.assertEqual(
            selected, {**overrides, "spec": {"model": "gpt-6-astra", "reasoning_effort": "medium"}}
        )
        dispatch = evidence.read(self.sd)
        record = evidence.read(evidence.bound(dispatch["stage_extension"]))
        self.assertEqual(record["models"], selected)
        self.assertEqual(record["model_overrides"], overrides)
        self.assertEqual(record["model_override_reason"], "用户指定实现与审查配置")
        self.stage()
        self.assertEqual(self.stage_info["models"], selected)
        self.ready_writer()
        self.assemble([self.review(blocking=True)], "code_failure")
        self.stage("repair")
        self.assertEqual(self.stage_info["models"], selected)
        self.stage()
        self.assertEqual(self.stage_info["models"], selected)
        self.ready_writer()
        self.assemble([self.review()])
        self.deliver()

    def test_existing_behavior_review_failure_restores_tdd_in_next_stage(self):
        self.h.prepare(
            mode="new",
            test_mode="TDD",
            approved_seams=["S1"],
        )
        self.root_dispatch = self.h.dispatch
        self.stage()

        def adapt(mode):
            result = self.cli(
                "executor",
                "ticket-adapt-plan",
                "--dispatch",
                self.sd,
                "--input",
                self.file(
                    "adapt",
                    {
                        "mode": mode,
                        "reason": "按已核实行为调整验证策略",
                        "acceptance": [{"criterion": "目标行为", "evidence": "BASE 与审查事实"}],
                        "verification": [{"command": "just test", "result": "实际结果与判断依据"}],
                    },
                ),
            )
            self.sd, self.wd = Path(result["stage_dispatch"]), Path(result["implementer_dispatch"])

        adapt("direct_verification")
        for _ in range(2):
            self.gate()
            self.gate("gate-core")
            self.implement()
            self.assemble([self.review(blocking=True)], "code_failure")
            self.stage("repair")
        adapt("TDD")
        self.assertEqual(json.loads(self.wd.read_text())["approved_seams"], ["S1"])
        self.ready_writer()
        self.assemble([self.review()])
        self.deliver()
        self.assertEqual(json.loads(self.root_report.read_text())["test_plan"]["mode"], "TDD")
        self.assertEqual(json.loads(self.root_report.read_text())["review"]["attempts"], 3)

    def test_root_cannot_use_plan_adapter_to_create_another_stage_budget(self):
        self.h.prepare(
            mode="new",
            test_mode="TDD",
            approved_seams=["S1"],
        )
        self.root_dispatch = self.h.dispatch
        self.stage()
        facts = self.file(
            "adapt-root",
            {
                "mode": "direct_verification",
                "reason": "BASE 已满足",
                "acceptance": [{"criterion": "目标行为", "evidence": "BASE 验证"}],
                "verification": [{"command": "just test", "result": "通过"}],
            },
        )
        self.cli(
            "controller",
            "adapt-plan",
            "--dispatch",
            self.root_dispatch,
            "--input",
            facts,
            ok=False,
        )
        self.assertEqual(self.stage()["stage"], 0)


if __name__ == "__main__":
    unittest.main()

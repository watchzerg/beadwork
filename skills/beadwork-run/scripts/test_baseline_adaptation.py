"""基线适配、零提交交付及原始证据保留的真实 Git 行为回归。"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_executor_operations as executor_fixture
import test_finalization as final_fixture
import test_verify_worker as worker_fixture
import test_verify_phase as phase_fixture


class BaselineAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.e = executor_fixture.ExecutorOperationsTests()
        self.e.setUp()
        self.addCleanup(self.e.doCleanups)
        self.h = self.e.h
        self.h.prepare(mode="new")
        self.select(self.h.d)

    def select(self, d):
        self.h.d = d
        self.h.dispatch = self.e.dispatch = Path(d["dispatch_path"])
        self.e.directory = self.e.dispatch.parent

    def adapt(self, mode="direct_verification", **changes):
        facts = {"mode": mode, "reason": "开工 BASE 已满足要求，复用既有行为验证", "acceptance": [{"criterion": "交付行为", "evidence": "BASE 的现有实现与测试"}],
                 "verification": [{"command": "just test", "result": "目标断言通过"}], "boundary_gates": ["gate-browser"], **changes}
        source = self.h.root / "adapt.json"
        self.h.put(source, facts)
        return self.h.call("adapt-plan", "--dispatch", self.e.dispatch, "--input", source)

    def evidence(self):
        p = self.e.directory / "acceptance.json"
        self.h.put(p, [{"criterion": "交付行为", "evidence": "现有生产入口与实际验证日志"}])
        return p

    def deliver(self, review, status="DONE", outcome="passed"):
        draft = {"status": status, "outcome": outcome,
                 "test_plan": {"decision_source": "controller 适配记录", "red_evidence": None},
                 "acceptance": [{"criterion": "交付行为", "evidence": "现有实现和验证"}],
                 "verification": [{"command": "just gate-unit", "result": "通过"}],
                 "requested_context": [], "blockers": [] if status == "DONE" else ["缺陷"], "concerns": []}
        self.h.put(self.e.directory / "draft.json", draft)
        receipt = self.e.call("assemble", "--dispatch", self.e.dispatch, "--draft", self.e.directory / "draft.json",
                              "--output", self.e.directory / "report.json", "--review", review)
        self.h.report = self.e.directory / "report.json"
        self.h.receipt = self.e.directory / "receipt.json"
        self.h.put(self.h.receipt, receipt)
        self.h.accept()
        return json.loads(self.h.report.read_text())

    def test_no_commit_full_delivery_and_comment(self):
        old = self.e.dispatch; raw = old.read_bytes()
        old_state = json.loads(raw)
        self.select(self.adapt())
        self.assertEqual(raw, old.read_bytes())
        for key in ("base_commit", "stage", "models", "prior_reviews"):
            self.assertEqual(self.h.d[key], old_state[key])
        self.assertEqual(self.h.d["approved_seams"], ["S1"])
        data = self.e.round(evidence=self.evidence())
        report = self.deliver(self.e.collect(data))
        self.assertEqual(report["delivery_kind"], "already_satisfied")
        self.assertEqual(report["implementation_commits"], [])
        self.assertEqual(report["base_commit"], report["head_commit"])
        comment = self.e.directory / "completion.md"
        self.h.call("comment", "--acceptance", self.h.acceptance, "--summary", "已有行为验收完成", "--output", comment)
        self.assertIn("无新增提交", comment.read_text())

    def test_review_scope_draft_allows_adaptation(self):
        draft = self.e.directory / "review-scope.md"
        draft.write_text("待审范围草稿")
        self.select(self.adapt())
        self.assertEqual(self.h.d["test_mode"], "direct_verification")
        self.assertEqual(draft.read_text(), "待审范围草稿")

    def test_review_marker_or_partial_directory_blocks_adaptation(self):
        for name in ("gate-review-started.json", "review-partial"):
            with self.subTest(name=name):
                path = self.e.directory / name
                if name.endswith('.json'):
                    path.write_text('{}')
                else:
                    path.mkdir()
                with self.assertRaisesRegex(AssertionError, "计划适配须"):
                    self.adapt()
                if path.is_dir():
                    path.rmdir()
                else:
                    path.unlink()

    def test_test_only_commit_is_changed_direct_verification(self):
        self.select(self.adapt())
        (self.h.wt / "regression.txt").write_text("既有行为回归覆盖\n")
        self.h.h.git(self.h.wt, "add", "regression.txt")
        self.h.h.git(self.h.wt, "commit", "-m", "test-1 补充覆盖")
        report = self.deliver(self.e.collect(self.e.round()))
        self.assertEqual(report["delivery_kind"], "changed")
        self.assertEqual(len(report["implementation_commits"]), 1)

    def test_empty_diff_requires_mode_and_evidence(self):
        self.e.call("review-prepare", "--dispatch", self.e.dispatch, ok=False)
        self.select(self.adapt())
        error = self.e.call("review-prepare", "--dispatch", self.e.dispatch, ok=False)
        self.assertIn("acceptance", error["error"])
        (self.h.wt / "dirty.txt").write_text("未完成")
        self.e.call("review-prepare", "--dispatch", self.e.dispatch, "--evidence", self.evidence(), ok=False)

    def test_evidence_tamper_and_plan_tamper_rejected(self):
        self.select(self.adapt())
        evidence = self.evidence()
        data = self.e.round(evidence=evidence)
        evidence.write_text("[]")
        self.e.collect(data, ok=False)
        Path(self.h.d["expected_plan_path"]).write_text('{"mode":"TDD","approved_seams":["S1"]}')
        self.e.call("review-prepare", "--dispatch", self.e.dispatch, ok=False)

    def test_blocking_existing_review_repairs_without_reset(self):
        self.select(self.adapt())
        self.deliver(self.e.collect(self.e.round(blocking=True, evidence=self.evidence())), "BLOCKED", "code_failure")
        previous = self.h.d.copy()
        self.h.prepare(mode="resume", test_mode="direct_verification", approved_seams=["S1"],
                       base_commit=previous["base_commit"], previous_dispatch=str(self.e.dispatch),
                       previous_report=str(self.h.report), previous_receipt=str(self.h.receipt), continuation="repair")
        self.select(self.h.d)
        self.assertEqual(self.h.d["stage"], 1)
        self.select(self.adapt(mode="TDD", reason="review 证明仍需修改生产行为"))
        self.assertEqual(self.h.d["stage"], 1)
        self.assertEqual(self.h.d["base_commit"], previous["base_commit"])
        self.assertEqual(self.h.d["test_mode"], "TDD")

    def test_resume_preserves_selected_plan(self):
        self.select(self.adapt())
        old = self.h.d.copy()
        self.h.prepare(mode="resume", test_mode="direct_verification", approved_seams=["S1"],
                       base_commit=old["base_commit"], previous_dispatch=old["dispatch_path"], continuation="resume")
        self.assertEqual(self.h.d["plan_adjustment"], old["plan_adjustment"])
        self.assertEqual(self.h.d["stage"], old["stage"])

    def test_reject_gate_loss_and_cross_ticket_record(self):
        with self.assertRaises(AssertionError):
            self.adapt(boundary_gates=[])
        self.select(self.adapt())
        raw = copy.deepcopy(self.h.d)
        raw["ticket_id"] = "other"
        self.h.put(self.e.dispatch, raw)
        self.e.call("review-prepare", "--dispatch", self.e.dispatch, ok=False)

    def test_legacy_dispatch_cannot_accept_no_commit_report(self):
        self.select(self.adapt())
        report = self.deliver(self.e.collect(self.e.round(evidence=self.evidence())))
        d = self.h.d.copy(); d.pop("execution_contract")
        self.h.put(self.e.dispatch, d)
        self.h.accept(ok=False)


class ReceiptOutputTests(unittest.TestCase):
    def test_worker_success_blocked_and_failure(self):
        h = worker_fixture.WorkerDeliveryTests(); h.setUp(); self.addCleanup(h.doCleanups)
        for role, report in [("reviewer", h.axis(True)), ("reviewer", {**h.expected("reviewer"), "status": "BLOCKED", "blockers": ["缺少 spec"]}), ("fixer", h.fixer())]:
            p = h.root / "report.json"; d = h.root / "dispatch.json"
            p.write_text(json.dumps(report)); d.write_text(json.dumps(h.expected(role)))
            cmd = [sys.executable, "-B", str(worker_fixture.VERIFIER), "--check-report", role, str(p), "--expected", str(d), "--emit-receipt"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), {"status": report.get("status", "COMPLETED"), "report_path": str(p), "report_sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
            p.write_text('{}')
            bad = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertEqual(bad.stdout, "")

    def test_phase_and_executor_receipt_outputs(self):
        h = phase_fixture.PhaseValidatorTests(); h.setUp(); self.addCleanup(h.doCleanups)
        import test_verify_ticket as ticket_fixture
        t = ticket_fixture.TicketAcceptanceTests(); t.setUp(); self.addCleanup(t.doCleanups)
        cases = [("preflight", h.preflight(), h.dispatch("preflight")),
                 ("finalizer", h.finalizer(), h.dispatch("finalizer")),
                 ("executor", t.report, None)]
        for role, report, dispatch in cases:
            with self.subTest(role=role):
                path = h.root / "report.json"; path.write_text(json.dumps(report))
                if role == "executor":
                    cmd = [sys.executable, "-B", str(ticket_fixture.VERIFIER), "--check-report", str(path)]
                else:
                    d = h.root / "dispatch.json"; d.write_text(json.dumps(dispatch))
                    cmd = [sys.executable, "-B", str(phase_fixture.VERIFIER), "--check-report", role, str(path), "--expected", str(d)]
                result = subprocess.run(cmd + ["--emit-receipt"], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), {"status": report["status"], "report_path": str(path), "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                diagnostic = subprocess.run(cmd, capture_output=True, text=True)
                self.assertTrue(json.loads(diagnostic.stdout)["ok"])
                path.write_text('{}')
                failed = subprocess.run(cmd + ["--emit-receipt"], capture_output=True, text=True)
                self.assertNotEqual(failed.returncode, 0)
                self.assertEqual(failed.stdout, "")


class EmptyBatchTests(unittest.TestCase):
    def test_final_review_accept_merge_and_cleanup_without_new_commits(self):
        f = final_fixture.FinalizationTests(); f.setUp(); self.addCleanup(f.doCleanups)
        # Fast-forward primary to existing code before beginning a fresh batch.
        f.h.h.git(f.h.primary, "merge", "--ff-only", f.h.h.head)
        f.h.h.base = f.h.h.head
        f.h.prepare("finalizer"); f.root = f.h.dispatch
        stage = f.stage()
        evidence = Path(stage).parent / "acceptance.json"
        f.put(evidence, [{"criterion": "parent 全部要求", "evidence": "当前实现与完整验证"}])
        review = f.review(stage, evidence=evidence)
        report, receipt = f.assemble(stage, reviews=[review], status="READY_TO_MERGE", outcome="passed")
        root_report = Path(f.h.d["report_path"])
        root_report.write_bytes(report.read_bytes())
        r = json.loads(receipt.read_text()); r["report_path"] = str(root_report)
        f.h.report = root_report; f.h.receipt = root_report.with_name("receipt.json"); f.put(f.h.receipt, r)
        f.h.accept()
        comment = root_report.with_name("integration.md")
        f.h.call("comment", "--acceptance", f.h.acceptance, "--summary", "已有批次验收", "--output", comment)
        f.h.put(f.h.root / "comments.json", [{"id": 7, "text": comment.read_text()}])
        f.h.merge_record = root_report.with_name("merge.json")
        self.assertTrue(f.h.merge()["merged"])
        self.assertTrue(f.h.call("cleanup", "--merge-record", f.h.merge_record)["cleaned"])


if __name__ == "__main__":
    unittest.main()

"""文档 writer 在最终阶段的真实 CLI、Git、恢复与验收闭环。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

import document_sync
import finalization
import test_finalization as final_fixture

pytestmark = pytest.mark.workflow


class DocumentSyncTests(unittest.TestCase):
    def setUp(self):
        self.f = final_fixture.FinalizationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.stage = self.f.stage()
        self.dispatch = Path(self.f.stage_info["document_dispatch"])

    def commit_document(self):
        (self.f.h.wt / "README.md").write_text("本批新增行为的使用说明。\n")
        self.f.h.h.git(self.f.h.wt, "add", "README.md")
        self.f.h.h.git(self.f.h.wt, "commit", "-m", "同步本批文档")
        return self.f.h.h.git(self.f.h.wt, "rev-parse", "HEAD")

    def test_missing_document_result_blocks_gate_review_and_ready(self):
        self.assertIsNone(self.f.stage_info["fixer_dispatch"])
        self.assertEqual(
            self.f.stage_info["document_launch_context"], {"fork_turns": "none", "required": True}
        )
        answer = self.f.call("review-prepare", "--dispatch", self.stage, ok=False)
        self.assertIn("文档同步", answer["error"])
        from types import SimpleNamespace

        import run_verification

        with pytest.raises(ValueError, match="文档同步"):
            run_verification.run(
                SimpleNamespace(
                    dispatch=str(self.stage), recipe="gate-full", delivery=True, parameters=[]
                )
            )
        self.f.assemble(self.stage, status="READY_TO_MERGE", outcome="passed", ok=False)

    def test_updated_document_is_in_final_delivery_and_review_writer(self):
        head = self.commit_document()
        self.f.done_document(self.stage, result="updated")
        self.f.gate(self.stage)
        collection = self.f.review(self.stage)
        selected = json.loads(collection.read_text())
        for path in Path(selected["round"]["path"]).parent.glob("*/dispatch.json"):
            reviewer = json.loads(path.read_text())
            self.assertEqual(reviewer["writer_source"]["dispatch"]["path"], str(self.dispatch))
            self.assertEqual(reviewer["reviewed_head"], head)
        report, _ = self.f.assemble(self.stage, status="READY_TO_MERGE", outcome="passed")
        value = json.loads(report.read_text())
        self.assertEqual(value["document_commits"], [head])
        self.assertEqual(value["fix"]["commits"], [])
        self.assertEqual(value["head_commit"], head)
        delivered = self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "delivered.json",
        )
        self.f.h.deliver(json.loads(Path(delivered["report_path"]).read_text()))
        self.f.h.accept()

    def test_no_change_completion_is_reused_and_writer_cannot_reopen(self):
        report = self.f.done_document(self.stage)
        self.assertEqual(json.loads(report.read_text())["commits"], [])
        resumed = self.f.stage()
        self.assertEqual(resumed, self.stage)
        self.assertIsNone(self.f.stage_info["document_dispatch"])
        with pytest.raises(ValueError, match="已完成"):
            import final_state

            final_state.require_writer(json.loads(self.dispatch.read_text()))
        self.f.gate(self.stage)
        self.f.review(self.stage)
        with pytest.raises(ValueError, match="review"):
            final_state.require_writer(json.loads(self.dispatch.read_text()))

    def test_interruption_preserves_dirty_work_and_resumes_same_writer(self):
        (self.f.h.wt / "README.md").write_text("尚未提交的文档。\n")
        self.f.done_document(self.stage, status="BLOCKED")
        self.f.assemble(self.stage)
        original = json.loads(self.dispatch.read_text())
        root = dict(
            json.loads(self.f.root.read_text()), prior_finalization={"stage_path": str(self.stage)}
        )
        finalization.prepare_attempt(root, original["base_commit"])
        self.assertEqual(root["attempt_id"], original["attempt_id"])
        self.assertEqual(self.f.stage(), self.stage)
        self.assertEqual(Path(self.f.stage_info["document_dispatch"]), self.dispatch)
        self.assertIn("尚未提交", (self.f.h.wt / "README.md").read_text())
        self.commit_document()
        report = self.f.done_document(self.stage, result="updated")
        self.assertEqual(json.loads(report.read_text())["status"], "DONE")

    def test_unknown_stop_does_not_grant_replacement_writer(self):
        self.f.done_document(self.stage, status="BLOCKED", stopped=False)
        self.f.stage()
        self.assertIsNone(self.f.stage_info["document_dispatch"])
        import final_state

        with pytest.raises(ValueError, match="未确认停止"):
            final_state.require_writer(json.loads(self.dispatch.read_text()))
        # 派发者确认旧任务已结束后，只补交收尾事实，不改原证据。
        self.f.done_document(self.stage, status="BLOCKED", stopped=True)
        self.f.stage()
        self.assertEqual(Path(self.f.stage_info["document_dispatch"]), self.dispatch)
        self.f.done_document(self.stage)

    def test_no_change_claim_rejected_when_document_changed(self):
        self.commit_document()
        result = self.f.done_document(self.stage, ok=False)
        self.assertIn("结论与实际变更不符", result["error"])

    def test_accepted_report_tampering_is_rejected(self):
        report = self.f.done_document(self.stage)
        report.write_text(report.read_text().replace("文档已与本批行为一致", "被改写的结论"))
        result = self.f.call("review-prepare", "--dispatch", self.stage, ok=False)
        self.assertIn("变化", result["error"])

    def test_repair_inherits_document_evidence_and_does_not_dispatch_syncer(self):
        document_head = self.commit_document()
        self.f.done_document(self.stage, result="updated")
        self.f.gate(self.stage)
        self.f.review(self.stage, blocking=True)
        _, receipt = self.f.assemble(self.stage, outcome="code_failure")
        repair = self.f.stage(previous=self.stage, receipt=receipt, continuation="repair")
        self.assertIsNone(self.f.stage_info["document_dispatch"])
        self.assertIsNotNone(self.f.stage_info["fixer_dispatch"])
        self.f.done_fixer(self.f.stage_info["fixer_dispatch"])
        self.f.review(repair)
        report, _ = self.f.assemble(repair, status="READY_TO_MERGE", outcome="passed")
        value = json.loads(report.read_text())
        self.assertEqual(value["document_commits"], [document_head])
        self.assertEqual(len(value["fix"]["commits"]), 1)
        self.assertEqual(len(value["document_sources"]), 1)
        self.f.call(
            "final-deliver",
            "--dispatch",
            self.f.root,
            "--output",
            self.f.root.parent / "delivered.json",
        )

    def test_new_commit_after_sync_requires_new_evidence(self):
        self.f.done_document(self.stage)
        self.commit_document()
        result = self.f.call("review-prepare", "--dispatch", self.stage, ok=False)
        self.assertIn("未覆盖", result["error"])

    def test_check_rejects_receipt_for_other_report(self):
        report = self.f.done_document(self.stage)
        receipt = self.dispatch.parent / "wrong-receipt.json"
        receipt.write_text("{}")
        with pytest.raises(ValueError, match="回执"):
            document_sync.check(str(self.dispatch), str(report), str(receipt))

    def run_document_check(self, recipe="test", *, exit_code=0, delivery=False, parameters=()):
        binary = self.f.h.root / "bin/just"
        binary.write_text(
            "#!" + sys.executable + "\nimport sys\n"
            "if sys.argv[1:]==['--summary']: print('install test gate-core gate-full')\n"
            f"else: print('文档检查'); sys.exit({exit_code})\n"
        )
        binary.chmod(0o755)
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(final_fixture.OPS),
                "run-verification",
                "--dispatch",
                str(self.dispatch),
                "--recipe",
                recipe,
                *(["--delivery"] if delivery else []),
                *(["--", *parameters] if parameters else []),
            ],
            cwd=self.f.h.root,
            env=self.f.h.env,
            capture_output=True,
            text=True,
        )

    def test_failed_document_check_requires_correction_before_done(self):
        failed = self.run_document_check(exit_code=1)
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        result = self.f.done_document(self.stage, ok=False)
        self.assertIn("定向检查仍失败", result["error"])
        passed = self.run_document_check()
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        report = self.f.done_document(self.stage)
        self.assertEqual(len(json.loads(report.read_text())["verification_sources"]), 2)
        self.f.gate(self.stage)
        self.f.review(self.stage)
        report, _ = self.f.assemble(self.stage, status="READY_TO_MERGE", outcome="passed")
        self.assertEqual(len(json.loads(report.read_text())["verification_sources"]), 3)

    def test_document_writer_cannot_run_full_delivery_gate(self):
        result = self.run_document_check("gate-full", delivery=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("完整 gate-full 由 finalizer", result.stderr)
        self.assertFalse(list(self.dispatch.parent.glob("verification-*")))

    def test_different_targeted_check_cannot_hide_document_failure(self):
        failed = self.run_document_check(exit_code=1, parameters=("links",))
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        passed = self.run_document_check(parameters=("examples",))
        self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
        result = self.f.done_document(self.stage, ok=False)
        self.assertIn("定向检查仍失败", result["error"])
        rerun = self.run_document_check(parameters=("links",))
        self.assertEqual(rerun.returncode, 0, rerun.stdout + rerun.stderr)
        self.f.done_document(self.stage)

    def test_dispatcher_must_confirm_stop_before_replacement(self):
        import final_state

        self.f.done_document(self.stage, status="BLOCKED", stopped=True, observed_stopped=False)
        self.f.stage()
        self.assertIsNone(self.f.stage_info["document_dispatch"])
        with pytest.raises(ValueError, match="未确认停止"):
            final_state.require_writer(json.loads(self.dispatch.read_text()))
        self.f.done_document(self.stage, status="BLOCKED", stopped=True, observed_stopped=True)
        self.f.stage()
        self.assertEqual(Path(self.f.stage_info["document_dispatch"]), self.dispatch)
        self.f.done_document(self.stage)

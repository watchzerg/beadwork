"""最终集成六阶段的行为回归；使用 controller 的真实临时 Git fixture。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

import final_state
import test_controller as controller_fixture
from fixture_support import stop_observation

OPS = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"

pytestmark = pytest.mark.workflow


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.h = controller_fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.prepare("finalizer")
        self.root = self.h.dispatch
        self.serial = 0

    def call(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, "-B", str(OPS), "executor", *map(str, args)],
            cwd=self.h.root,
            env=self.h.env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0 if ok else 1, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def put(self, path, value):
        Path(path).write_text(json.dumps(value, ensure_ascii=False))
        return str(path)

    def bind(self, path):
        path = Path(path)
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def stage(self, *, previous=None, receipt=None, continuation="resume", ok=True):
        facts = {"continuation": continuation}
        if previous:
            facts.update(
                previous_stage=str(previous),
                previous_report=str(previous.with_name("report.json")),
                previous_receipt=str(receipt),
            )
        self.serial += 1
        source = self.h.root / f"final-stage-{self.serial}.json"
        self.put(source, facts)
        result = self.call("final-stage", "--dispatch", self.root, "--input", source, ok=ok)
        if not ok:
            return result
        self.stage_info = result
        launch = {"fork_turns": "none", "required": True}
        if result["fixer_dispatch"]:
            self.assertEqual(result["fixer_launch_context"], launch)
            self.assertEqual(
                json.loads(Path(result["fixer_dispatch"]).read_text())["launch_context"], launch
            )
        else:
            self.assertIsNone(result["fixer_launch_context"])
        return Path(result["stage_path"])

    def done_document(
        self,
        stage,
        *,
        result="no_change_needed",
        status="DONE",
        stopped=True,
        ok=True,
        observed_stopped=None,
    ):
        d = json.loads(Path(stage).read_text())
        dispatch = Path(stage).parent / "document-syncer/dispatch.json"
        self.serial += 1
        draft = {
            "status": status,
            "outcome": "passed" if status == "DONE" else "interrupted",
            "result": result if status == "DONE" else "incomplete",
            "inspected": [{"source": "README.md 与 linked spec", "assessment": "已核对本批行为"}],
            "summary": "文档已与本批行为一致",
            "verification_notes": {},
            "stopped_tasks": stopped,
            "blockers": [] if status == "DONE" else ["同步中断"],
            "remaining_work": [] if status == "DONE" else ["继续文档同步"],
        }
        folder = dispatch.parent
        output = folder / f"report-{self.serial}.json"
        answer = self.call(
            "document-assemble",
            "--dispatch",
            dispatch,
            "--draft",
            self.put(folder / f"draft-{self.serial}.json", draft),
            "--output",
            output,
            ok=ok,
        )
        if not ok:
            return answer
        receipt = self.put(folder / f"receipt-{self.serial}.json", answer)
        observation = self.put(
            folder / f"observation-{self.serial}.json",
            stop_observation(output, observed_stopped=observed_stopped),
        )
        self.call(
            "document-accept",
            "--dispatch",
            stage,
            "--report",
            output,
            "--receipt",
            receipt,
            "--observation",
            observation,
        )
        self.assertEqual(d["stage"], 0)
        return output

    def review(self, dispatch, blocking=False, evidence=None):
        prepared = self.call(
            "review-prepare",
            "--dispatch",
            dispatch,
            *(["--evidence", evidence] if evidence else []),
        )
        launch = {"fork_turns": "none", "required": True}
        self.assertEqual(prepared["reviewer_launch_context"], launch)
        sources = json.loads(Path(prepared["selection_draft_path"]).read_text())
        for axis, raw in prepared["axes"].items():
            identity = json.loads(Path(raw).read_text())
            self.assertEqual(identity["launch_context"], launch)
            report = {
                "axis": axis,
                "reviewed_base": identity["reviewed_base"],
                "reviewed_head": identity["reviewed_head"],
                "notes": [],
                "findings": [],
            }
            if blocking and axis == "standards":
                report["findings"] = [
                    {
                        "axis": axis,
                        "kind": "defect",
                        "blocking": True,
                        "title": "需要修复",
                        "evidence": "真实 review 证据",
                    }
                ]
            report_path = Path(identity["report_path"])
            self.put(report_path, report)
            receipt = report_path.parent / "receipt.json"
            self.put(
                receipt,
                {
                    "status": "COMPLETED",
                    "report_path": str(report_path),
                    "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                },
            )
            sources[axis].update(
                report=str(report_path),
                receipt=str(receipt),
                observation=stop_observation(report_path),
            )
        round_path = Path(prepared["round_path"])
        selection = round_path.parent / "selection.json"
        self.put(selection, sources)
        answer = self.call(
            "review-collect",
            "--round",
            round_path,
            "--input",
            selection,
            "--output",
            round_path.parent / "collection.json",
        )
        return Path(answer["collection_path"])

    def draft(self, status, outcome, failed_gate=None):
        return {
            "status": status,
            "outcome": outcome,
            "verification_notes": {},
            "stopped_tasks": True,
            "sources": [],
            "verification": [],
            "blockers": [] if status == "READY_TO_MERGE" else ["需要后续处理"],
            "remaining_work": [] if status == "READY_TO_MERGE" else ["继续当前阶段"],
        }

    def assemble(
        self,
        stage,
        *,
        reviews=(),
        fixes=(),
        status="BLOCKED",
        outcome="interrupted",
        failed_gate=None,
        implicit=False,
        ok=True,
    ):
        self.serial += 1
        folder = Path(stage).parent
        draft = folder / f"draft-{self.serial}.json"
        output = folder / "report.json"
        self.put(draft, self.draft(status, outcome, failed_gate))
        args = ["final-assemble", "--dispatch", stage, "--draft", draft, "--output", output]
        answer = self.call(*args, ok=ok)
        if not ok:
            return answer
        receipt = folder / "receipt.json"
        self.put(
            receipt,
            {
                "status": answer["status"],
                "report_path": answer["report_path"],
                "report_sha256": answer["report_sha256"],
            },
        )
        return Path(answer["report_path"]), receipt

    def done_fixer(self, fixer_dispatch, messages=("修复一",)):
        d = json.loads(Path(fixer_dispatch).read_text())
        for index, message in enumerate(messages):
            self.serial += 1
            (self.h.wt / f"fix-{self.serial}-{index}.txt").write_text(message)
            self.h.h.git(self.h.wt, "add", ".")
            self.h.h.git(self.h.wt, "commit", "-m", message)
        self.gate(fixer_dispatch)
        folder = Path(fixer_dispatch).parent
        draft = {
            "status": "DONE",
            "outcome": "passed",
            "verification_notes": {},
            "stopped_tasks": True,
            "blockers": [],
            "remaining_work": [],
            "dispositions": [{"source": "review", "action": "已修复并检查文档影响"}],
            "uncommitted_files": [],
        }
        report = folder / "report.json"
        answer = self.call(
            "fixer-assemble",
            "--dispatch",
            fixer_dispatch,
            "--draft",
            self.put(folder / "draft.json", draft),
            "--output",
            report,
        )
        receipt = self.put(folder / "receipt.json", answer)
        observation = self.put(folder / "observation.json", stop_observation(report))
        stage = d["stage_dispatch"]["path"]
        self.call(
            "fixer-accept",
            "--dispatch",
            stage,
            "--report",
            report,
            "--receipt",
            receipt,
            "--observation",
            observation,
        )
        return {
            "dispatch": self.bind(fixer_dispatch),
            "report": self.bind(report),
            "receipt": self.bind(receipt),
        }

    def gate(self, dispatch, exit_code=0):
        binary = self.h.root / "bin/just"
        binary.write_text(
            "#!"
            + sys.executable
            + '\nimport sys\nif sys.argv[1:]==["--summary"]: print(\'install test gate-core gate-full\')\nelse: print("collected 1 check")\n'
            + f"sys.exit(0 if sys.argv[1:]==['--summary'] else {exit_code})\n"
        )
        binary.chmod(0o755)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(OPS),
                "run-verification",
                "--dispatch",
                str(dispatch),
                "--recipe",
                "gate-full",
                "--delivery",
            ],
            cwd=self.h.root,
            env=self.h.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, exit_code, result.stdout + result.stderr)

    def assert_finalizer_verification_blocked(self, stage):
        before = list(stage.parent.glob("verification-*"))
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(OPS),
                "run-verification",
                "--dispatch",
                str(stage),
                "--recipe",
                "gate-full",
                "--delivery",
            ],
            cwd=self.h.root,
            env=self.h.env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("收尾", result.stderr)
        self.assertEqual(list(stage.parent.glob("verification-*")), before)

    def test_final_repair_context_contains_only_current_failure_and_reuses_binding(self):
        stage = self.stage()
        self.done_document(stage)
        self.gate(stage)
        self.review(stage, blocking=True)
        _, receipt = self.assemble(stage, outcome="code_failure")
        repair = self.stage(previous=stage, receipt=receipt, continuation="repair")
        source = self.stage_info["active_stage_context_source"]
        context = json.loads(Path(source["path"]).read_text())
        self.assertEqual(len(context["blocking_findings"]), 1)
        fixer = json.loads(Path(self.stage_info["fixer_dispatch"]).read_text())
        self.assertNotIn("prior_verification", fixer)
        self.assertNotIn("prior_reviews", fixer)
        self.assertEqual(fixer["active_stage_context_source"], source)
        self.assertEqual(self.stage(), repair)
        self.assertEqual(self.stage_info["active_stage_context_source"], source)
        self.done_fixer(self.stage_info["fixer_dispatch"])
        self.review(repair, blocking=True)
        _, receipt = self.assemble(repair, outcome="code_failure")
        next_stage = self.stage(previous=repair, receipt=receipt, continuation="repair")
        self.assert_finalizer_verification_blocked(next_stage)
        context = json.loads(
            Path(self.stage_info["active_stage_context_source"]["path"]).read_text()
        )
        view = json.loads(Path(context["verification_view_source"]["path"]).read_text())
        self.assertEqual(len(context["blocking_findings"]), 1)
        self.assertEqual(len(view["entries"]), 1)
        self.assertNotIn(str(stage.parent), view["entries"][0]["run_path"])
        Path(context["verification_view_source"]["path"]).write_text("{}")
        error = self.stage(ok=False)
        self.assertIn("error", error)

    def test_review_findings_survive_a_gate_failure_without_new_review(self):
        stage0 = self.stage()
        self.done_document(stage0)
        self.gate(stage0)
        original = self.review(stage0, blocking=True)
        _, receipt = self.assemble(stage0, outcome="code_failure")
        stage1 = self.stage(previous=stage0, receipt=receipt, continuation="repair")
        writer = Path(self.stage_info["fixer_dispatch"])
        self.gate(writer, exit_code=1)

        def last_failure():
            files = list(writer.parent.glob("verification-*/result.json"))
            return max(
                files,
                key=lambda p: json.loads((p.parent / "started.json").read_text())["started_ns"],
            )

        for n in range(3):
            self.call("begin-gate-repair", "--dispatch", writer, "--failure", last_failure())
            (self.h.wt / "gate-repair.txt").write_text(str(n))
            self.h.h.git(self.h.wt, "add", "gate-repair.txt")
            self.h.h.git(self.h.wt, "commit", "-m", f"修正 gate {n}")
            self.gate(writer, exit_code=1)
        report = writer.parent / "report.json"
        draft = {
            "status": "BLOCKED",
            "outcome": "code_failure",
            "verification_notes": {},
            "stopped_tasks": True,
            "blockers": ["完整 gate 仍失败"],
            "remaining_work": ["继续修复 gate"],
            "dispositions": [{"source": "gate-full", "action": "修正三次仍失败；未完成其他处置"}],
            "uncommitted_files": [],
        }
        result = self.call(
            "fixer-assemble",
            "--dispatch",
            writer,
            "--draft",
            self.put(writer.parent / "draft.json", draft),
            "--output",
            report,
        )
        self.call(
            "fixer-accept",
            "--dispatch",
            stage1,
            "--report",
            report,
            "--receipt",
            self.put(writer.parent / "receipt.json", result),
            "--observation",
            self.put(writer.parent / "observation.json", stop_observation(report)),
        )
        self.stage()
        self.assertIsNone(self.stage_info["fixer_dispatch"])
        with self.assertRaisesRegex(ValueError, "终态"):
            final_state.require_writer(json.loads(writer.read_text()))
        _, receipt = self.assemble(stage1, outcome="code_failure")
        self.stage(previous=stage1, receipt=receipt, continuation="repair")
        context = json.loads(
            Path(self.stage_info["active_stage_context_source"]["path"]).read_text()
        )
        original_findings = json.loads(original.read_text())["pair"]["standards"]["findings"]
        self.assertEqual(context["blocking_findings"], original_findings)
        self.assertEqual(context["selected_review_source"], self.bind(original))
        self.assertEqual(context["previous_dispositions"], draft["dispositions"])
        view = json.loads(Path(context["verification_view_source"]["path"]).read_text())
        self.assertTrue(view["entries"])
        self.assertTrue(all(str(writer.parent) in entry["run_path"] for entry in view["entries"]))
        source = self.stage_info["active_stage_context_source"]
        self.stage()
        self.assertEqual(self.stage_info["active_stage_context_source"], source)

    def test_stage_zero_gate_failure_has_current_verification_without_review(self):
        stage = self.stage()
        self.done_document(stage)
        self.gate(stage, exit_code=1)
        _, receipt = self.assemble(stage, outcome="code_failure")
        self.stage(previous=stage, receipt=receipt, continuation="repair")
        context = json.loads(
            Path(self.stage_info["active_stage_context_source"]["path"]).read_text()
        )
        self.assertEqual(context["blocking_findings"], [])
        self.assertIsNone(context["selected_review_source"])
        view = json.loads(Path(context["verification_view_source"]["path"]).read_text())
        self.assertEqual(view["entries"][0]["exit_code"], 1)

    def test_supplemental_failure_after_fixer_done_can_enter_next_stage(self):
        stage0 = self.stage()
        self.done_document(stage0)
        self.gate(stage0, exit_code=1)
        _, receipt = self.assemble(stage0, outcome="code_failure")
        stage1 = self.stage(previous=stage0, receipt=receipt, continuation="repair")
        self.done_fixer(self.stage_info["fixer_dispatch"])
        self.gate(stage1, exit_code=1)
        _, receipt = self.assemble(stage1, outcome="code_failure")
        stage2 = self.stage(previous=stage1, receipt=receipt, continuation="repair")
        self.assertEqual(self.stage_info["stage"], 2)
        self.assertIsNotNone(self.stage_info["fixer_dispatch"])
        context = json.loads(
            Path(self.stage_info["active_stage_context_source"]["path"]).read_text()
        )
        view = json.loads(Path(context["verification_view_source"]["path"]).read_text())
        self.assertTrue(
            any(
                row["exit_code"] == 1 and Path(row["run_path"]).parent == stage1.parent
                for row in view["entries"]
            )
        )
        self.done_fixer(self.stage_info["fixer_dispatch"])
        self.review(stage2)
        self.assemble(stage2, status="READY_TO_MERGE", outcome="passed")
        delivered = self.call(
            "final-deliver",
            "--dispatch",
            self.root,
            "--output",
            self.root.parent / "supplemental-recovery.json",
        )
        self.h.deliver(json.loads(Path(delivered["report_path"]).read_text()))
        self.h.accept()

    def test_fixer_resume_requires_dispatcher_stop_confirmation(self):
        stage = self.stage()
        self.done_document(stage)
        self.gate(stage, exit_code=1)
        _, receipt = self.assemble(stage, outcome="code_failure")
        repair = self.stage(previous=stage, receipt=receipt, continuation="repair")
        writer = Path(self.stage_info["fixer_dispatch"])

        self.assert_finalizer_verification_blocked(repair)
        draft = {
            "status": "BLOCKED",
            "outcome": "interrupted",
            "verification_notes": {},
            "stopped_tasks": True,
            "blockers": ["会话中断"],
            "remaining_work": ["继续当前修复"],
            "dispositions": [],
            "uncommitted_files": [],
        }
        for number, observed in enumerate((False, True)):
            report = writer.parent / f"blocked-{number}.json"
            result = self.call(
                "fixer-assemble",
                "--dispatch",
                writer,
                "--draft",
                self.put(writer.parent / f"draft-{number}.json", draft),
                "--output",
                report,
            )
            self.call(
                "fixer-accept",
                "--dispatch",
                repair,
                "--report",
                report,
                "--receipt",
                self.put(writer.parent / f"receipt-{number}.json", result),
                "--observation",
                self.put(
                    writer.parent / f"observation-{number}.json",
                    stop_observation(report, observed_stopped=observed),
                ),
            )
            self.stage()
            if observed:
                self.assertEqual(self.stage_info["fixer_dispatch"], str(writer))
                final_state.require_writer(json.loads(writer.read_text()))
                self.gate(repair)
            else:
                with self.assertRaisesRegex(ValueError, "停止"):
                    final_state.require_writer(json.loads(writer.read_text()))
                self.assertIsNone(self.stage_info["fixer_dispatch"])
                self.assert_finalizer_verification_blocked(repair)

    def test_review_observation_cannot_advance_unstopped_axis(self):
        stage = self.stage()
        self.done_document(stage)
        self.gate(stage)
        collection_path = self.review(stage)
        collection = json.loads(collection_path.read_text())
        selection = {
            axis: {
                "report": source["report"]["path"],
                "receipt": source["receipt"]["path"],
                "observation": stop_observation(source["report"]["path"], observed_stopped=False),
            }
            for axis, source in collection["sources"].items()
        }
        checkpoints = list(self.root.parent.glob("checkpoint-*.json"))
        output = collection_path.parent / "unaccepted.json"
        error = self.call(
            "review-collect",
            "--round",
            collection["round"]["path"],
            "--input",
            self.put(collection_path.parent / "unstopped.json", selection),
            "--output",
            output,
            ok=False,
        )
        self.assertIn("停止", error["error"])
        self.assertFalse(output.exists())
        self.assertEqual(list(self.root.parent.glob("checkpoint-*.json")), checkpoints)

    def test_current_passing_stage_reaches_root_acceptance(self):
        stage = self.stage()
        self.done_document(stage)
        self.gate(stage)
        self.review(stage)
        self.assemble(stage, status="READY_TO_MERGE", outcome="passed")
        delivered = self.call(
            "final-deliver",
            "--dispatch",
            self.root,
            "--output",
            self.root.parent / "delivered.json",
        )
        self.h.deliver(json.loads(Path(delivered["report_path"]).read_text()))
        self.h.accept()

        comment = self.h.dispatch.parent / "integration.md"
        self.h.call(
            "comment",
            "--acceptance",
            self.h.acceptance,
            "--summary",
            "批次已完成",
            "--output",
            comment,
        )
        self.h.put(self.h.root / "comments.json", [{"id": 7, "text": comment.read_text()}])
        merge_record = self.h.dispatch.parent / "merge.json"
        self.h.call(
            "merge",
            "--acceptance",
            self.h.acceptance,
            "--comment-id",
            "7",
            "--output",
            merge_record,
        )
        self.assertEqual(self.h.h.git(self.h.primary, "rev-parse", "HEAD"), self.h.h.head)


if __name__ == "__main__":
    unittest.main()

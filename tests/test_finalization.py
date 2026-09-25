"""最终集成六阶段的行为回归；使用 controller 的真实临时 Git fixture。"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

import test_controller as controller_fixture
from fixture_support import closure_source

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
        closure = closure_source(dispatch, output, observed_stopped=observed_stopped)
        self.call(
            "document-accept",
            "--dispatch",
            stage,
            "--report",
            output,
            "--receipt",
            receipt,
            "--closure",
            closure,
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
        sources = {}
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
            sources[axis] = {"report": str(report_path), "receipt": str(receipt)}
            if identity.get("handoff_required"):
                cp = closure_source(raw, report_path)
                sources[axis]["closure"] = json.loads(cp.read_text())["path"]
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
        closure = closure_source(fixer_dispatch, report)
        stage = d["stage_dispatch"]["path"]
        self.call(
            "fixer-accept",
            "--dispatch",
            stage,
            "--report",
            report,
            "--receipt",
            receipt,
            "--closure",
            closure,
        )
        return {
            "dispatch": self.bind(fixer_dispatch),
            "report": self.bind(report),
            "receipt": self.bind(receipt),
        }

    def gate(self, dispatch):
        binary = self.h.root / "bin/just"
        binary.write_text(
            "#!"
            + sys.executable
            + '\nimport sys\nif sys.argv[1:]==["--summary"]: print(\'install test gate-core gate-full\')\nelse: print("collected 1 check")\n'
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
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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

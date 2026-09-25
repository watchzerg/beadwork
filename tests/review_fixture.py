"""单票主流程复用的 review 报告 fixture。"""

import copy
import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

import test_controller as controller_fixture
from fixture_support import closure_source

SCRIPT = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"


class ReviewFixture(unittest.TestCase):
    def setUp(self):
        self.h = controller_fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.prepare()
        self.dispatch = self.h.dispatch
        self.directory = self.dispatch.parent
        self.serial = 0

    def call(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "executor", *map(str, args)],
            cwd=self.h.root,
            env=self.h.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def round(self, blocking=False, evidence=None):
        prepared = self.call(
            "review-prepare",
            "--dispatch",
            self.dispatch,
            *(["--evidence", evidence] if evidence else []),
        )
        launch = {"fork_turns": "none", "required": True}
        self.assertEqual(prepared["reviewer_launch_context"], launch)
        sources = {}
        for axis, path in prepared["axes"].items():
            d = json.loads(Path(path).read_text())
            self.assertEqual(d["launch_context"], launch)
            report = {
                "axis": axis,
                "reviewed_base": d["reviewed_base"],
                "reviewed_head": d["reviewed_head"],
                "notes": [],
                "findings": [],
            }
            if axis == "standards":
                report["findings"] = [
                    {
                        "axis": axis,
                        "kind": "defect" if blocking else "smell",
                        "blocking": blocking,
                        "title": "需处理" if blocking else "命名建议",
                        "evidence": "原始证据，不改写",
                    }
                ]
            report_path = Path(d["report_path"])
            self.h.put(report_path, report)
            receipt = report_path.parent / "receipt.json"
            self.h.put(
                receipt,
                {
                    "status": "COMPLETED",
                    "report_path": str(report_path),
                    "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                },
            )
            sources[axis] = {"report": str(report_path), "receipt": str(receipt)}
            if d.get("handoff_required"):
                cp = closure_source(d["dispatch_path"], report_path)
                sources[axis]["closure"] = json.loads(cp.read_text())["path"]
        path = Path(prepared["round_path"])
        selection = path.parent / "selection.json"
        self.h.put(selection, sources)
        return path, selection, sources

    def collect(self, round_data, ok=True):
        path, selection, _ = round_data
        result = self.call(
            "review-collect",
            "--round",
            path,
            "--input",
            selection,
            "--output",
            path.parent / "collection.json",
            ok=ok,
        )
        return Path(result["collection_path"]) if ok else result

    def assemble(self, reviews=(), status="DONE", ok=True, outcome=None):
        draft = copy.deepcopy(self.h.h.report)
        for key in (
            "base_commit",
            "head_commit",
            "implementation_commits",
            "review",
            "delivery_kind",
        ):
            del draft[key]
        draft["test_plan"] = {"decision_source": "ticket/spec", "red_evidence": "实测行为断言失败"}
        draft["status"] = status
        draft["outcome"] = outcome or ("passed" if status == "DONE" else "interrupted")
        if status != "DONE":
            draft["test_plan"] = None
            draft["acceptance"] = []
            draft["verification"] = []
            draft["blockers" if status == "BLOCKED" else "requested_context"] = ["缺少必需事实"]
        self.serial += 1
        path = self.directory / f"draft-{self.serial}.json"
        output = self.directory / f"report-{self.serial}.json"
        self.h.put(path, draft)
        args = ["assemble", "--dispatch", self.dispatch, "--draft", path, "--output", output]
        for review in reviews:
            args.extend(("--review", review))
        result = self.call(*args, ok=ok)
        return result, output


if __name__ == "__main__":
    unittest.main()

"""真实临时 worktree 中验证开工、提交前检查、review 搬运及报告组装。"""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import pytest

import test_controller as controller_fixture

SCRIPT = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/executor-operations.py"

pytestmark = pytest.mark.workflow


class ExecutorOperationsTests(unittest.TestCase):
    def setUp(self):
        self.h = controller_fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.prepare()
        self.dispatch = self.h.dispatch
        self.directory = self.dispatch.parent
        self.serial = 0

    def call(self, *args, ok=True):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), *map(str, args)],
            cwd=self.h.root, env=self.h.env, capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def round(self, blocking=False, evidence=None):
        prepared = self.call("review-prepare", "--dispatch", self.dispatch, *(["--evidence", evidence] if evidence else []))
        sources = {}
        for axis, path in prepared["axes"].items():
            d = json.loads(Path(path).read_text())
            report = {"axis": axis, "reviewed_base": d["reviewed_base"],
                      "reviewed_head": d["reviewed_head"], "notes": [], "findings": []}
            if axis == "standards":
                report["findings"] = [{"axis": axis, "kind": "defect" if blocking else "smell",
                    "blocking": blocking, "title": "需处理" if blocking else "命名建议", "evidence": "原始证据，不改写"}]
            report_path = Path(d["report_path"])
            self.h.put(report_path, report)
            receipt = report_path.parent / "receipt.json"
            self.h.put(receipt, {"status": "COMPLETED", "report_path": str(report_path),
                "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()})
            sources[axis] = {"report": str(report_path), "receipt": str(receipt)}
            if d.get('handoff_required'):
                cp = controller_fixture.closure_source(d['dispatch_path'], report_path)
                sources[axis]['closure'] = json.loads(cp.read_text())['path']
        path = Path(prepared["round_path"])
        selection = path.parent / "selection.json"
        self.h.put(selection, sources)
        return path, selection, sources

    def collect(self, round_data, ok=True):
        path, selection, _ = round_data
        result = self.call("review-collect", "--round", path, "--input", selection,
                           "--output", path.parent / "collection.json", ok=ok)
        return Path(result["collection_path"]) if ok else result

    def assemble(self, reviews=(), status="DONE", ok=True, outcome=None):
        draft = copy.deepcopy(self.h.h.report)
        for key in ("base_commit", "head_commit", "implementation_commits", "review", "delivery_kind"):
            del draft[key]
        draft["test_plan"] = {"decision_source": "ticket/spec", "red_evidence": "实测行为断言失败"}
        draft["status"] = status
        draft["outcome"] = outcome or ("passed" if status == "DONE" else "interrupted")
        if status != "DONE":
            draft["test_plan"] = None
            draft["acceptance"] = []; draft["verification"] = []
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

    def test_smell_round_assembles_real_commits_and_controller_accepts(self):
        data = self.round()
        original = {a: Path(p["report"]).read_bytes() for a, p in data[2].items()}
        collected = self.collect(data)
        receipt, path = self.assemble([collected])
        report = json.loads(path.read_text())
        self.assertEqual(report["implementation_commits"], self.h.h.commits)
        self.assertEqual(report["review"]["gate"], "PASS")
        self.assertNotIn("initial", report["review"])
        for axis in original:
            self.assertEqual(report["review"]["final"][axis], json.loads(original[axis]))
            self.assertEqual(Path(data[2][axis]["report"]).read_bytes(), original[axis])
        self.h.report = path
        self.h.receipt = self.directory / "receipt.json"
        self.h.put(self.h.receipt, receipt)
        self.h.accept()

    def test_missing_axis_does_not_create_collection(self):
        data = self.round()
        self.h.put(data[1], {"standards": data[2]["standards"]})
        self.collect(data, ok=False)
        self.assertFalse((data[0].parent / "collection.json").exists())

    def test_bad_axis_sha_and_receipt_are_rejected(self):
        for kind in ("axis", "sha", "receipt"):
            with self.subTest(kind=kind):
                data = self.round()
                target = Path(data[2]["spec"]["receipt" if kind == "receipt" else "report"])
                value = json.loads(target.read_text())
                if kind == "receipt": value["report_sha256"] = "0" * 64
                elif kind == "axis": value["axis"] = "standards"
                else: value["reviewed_head"] = self.h.h.base
                self.h.put(target, value)
                if kind != "receipt":
                    receipt = Path(data[2]["spec"]["receipt"])
                    r = json.loads(receipt.read_text()); r["report_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
                    self.h.put(receipt, r)
                self.collect(data, ok=False)

    def test_dirty_or_moved_head_blocks_review(self):
        data = self.round()
        changed = self.h.wt / "behavior.txt"
        changed.write_text("新的修改")
        self.collect(data, ok=False)
        self.call("review-prepare", "--dispatch", self.dispatch, ok=False)
        self.h.h.git(self.h.wt, "add", ".")
        self.h.h.git(self.h.wt, "commit", "-m", "test-1 新增修改")
        self.collect(data, ok=False)
        self.assertEqual(changed.read_text(), "新的修改")

    def test_partial_states_preserve_dirty_work_and_need_no_review(self):
        changed = self.h.wt / "unfinished.txt"
        changed.write_text("保留现场")
        for status in ("BLOCKED", "NEEDS_CONTEXT"):
            result, path = self.assemble(status=status)
            self.assertEqual(result["status"], status)
            self.assertIsNone(json.loads(path.read_text())["review"])
        self.assertEqual(changed.read_text(), "保留现场")

    def test_primary_change_allows_full_check_without_overwrite(self):
        collected = self.collect(self.round())
        receipt, path = self.assemble([collected])
        before = path.read_bytes()
        (self.h.primary / "behavior.txt").write_text("意外修改")
        self.call("check", "--dispatch", self.dispatch, "--report", path)
        self.assertEqual(path.read_bytes(), before)

    def test_collection_tamper_and_stale_review_fail_assembly(self):
        collected = self.collect(self.round())
        value = json.loads(collected.read_text())
        value["pair"]["standards"]["findings"] = []
        self.h.put(collected, value)
        self.assemble([collected], ok=False)
        fresh = self.collect(self.round())
        (self.h.wt / "behavior.txt").write_text("新 HEAD")
        self.h.h.git(self.h.wt, "add", ".")
        self.h.h.git(self.h.wt, "commit", "-m", "test-1 后续修改")
        self.assemble([fresh], ok=False)

    def test_two_rounds_preserve_initial_and_cover_fix(self):
        initial = self.collect(self.round(blocking=True))
        (self.h.wt / "behavior.txt").write_text("完成修复")
        self.h.h.git(self.h.wt, "add", ".")
        self.h.h.git(self.h.wt, "commit", "-m", "test-1 修复")
        # 跨阶段旧 review 来源由 controller 固定；模拟已核验的阶段派发。
        d = json.loads(self.dispatch.read_text())
        d.update(stage=1, prior_reviews=[{"path": str(initial), "sha256": hashlib.sha256(initial.read_bytes()).hexdigest()}])
        # dispatch 已被 round hash 绑定，下一阶段必须使用新证据目录。
        self.h.prepare(previous_dispatch=str(self.dispatch))
        self.dispatch = self.h.dispatch
        self.directory = self.dispatch.parent
        next_d = json.loads(self.dispatch.read_text())
        next_d.update(stage=1, prior_reviews=d["prior_reviews"], gate_repair_root=str(self.directory))
        self.h.put(self.dispatch, next_d)
        final = self.collect(self.round())
        _, path = self.assemble([initial, final])
        review = json.loads(path.read_text())["review"]
        self.assertEqual(review["attempts"], 2)
        self.assertTrue(review["initial"]["standards"]["findings"][0]["blocking"])
        self.assertEqual(review["gate"], "PASS")
        self.assemble([initial, final, final], ok=False)

    def test_finalizer_uses_reviewed_main(self):
        import test_finalization
        f = test_finalization.FinalizationTests(); f.setUp(); self.addCleanup(f.doCleanups)
        stage = f.stage(); f.gate(stage)
        collected = f.review(stage)
        self.assertEqual(json.loads(collected.read_text())["pair"]["spec"]["reviewed_base"], f.h.h.base)

    def test_existing_output_is_not_overwritten(self):
        data = self.round()
        path = self.collect(data)
        before = path.read_bytes()
        self.collect(data, ok=False)
        self.assertEqual(path.read_bytes(), before)

    def test_resume_accepts_explicit_same_ticket_history_only(self):
        collected = self.collect(self.round())
        self.h.prepare()
        self.dispatch = self.h.dispatch
        self.directory = self.dispatch.parent
        self.assemble([collected])
        self.h.prepare(ticket_id="test-other")
        self.dispatch = self.h.dispatch
        self.directory = self.dispatch.parent
        self.assemble([collected], ok=False)

    def test_blocked_reviewer_and_changed_source_remain_evidence(self):
        data = self.round()
        target = Path(data[2]["spec"]["report"])
        original = json.loads(target.read_text())
        report = {key: original[key] for key in ("axis", "reviewed_base", "reviewed_head")}
        report.update(status="BLOCKED", blockers=["来源缺失"])
        self.h.put(target, report)
        self.h.put(data[2]["spec"]["receipt"], {"status": "BLOCKED", "report_path": str(target),
            "report_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
        self.collect(data, ok=False)
        self.assertEqual(json.loads(target.read_text()), report)
        data = self.round()
        collected = self.collect(data)
        target = Path(data[2]["spec"]["report"])
        target.write_text(target.read_text() + "\n")
        self.assemble([collected], ok=False)

    def test_no_commit_partial_report_and_direct_verification(self):
        self.h.prepare(mode="new", test_mode="direct_verification", approved_seams=[])
        self.dispatch = self.h.dispatch
        self.directory = self.dispatch.parent
        _, path = self.assemble(status="NEEDS_CONTEXT")
        self.assertEqual(json.loads(path.read_text())["implementation_commits"], [])
        self.h.prepare(test_mode="direct_verification", approved_seams=[])
        self.dispatch = self.h.dispatch
        self.directory = self.dispatch.parent
        collected = self.collect(self.round())
        draft = {"status": "DONE", "outcome": "passed", "test_plan": {"decision_source": "ticket", "red_evidence": None},
            "acceptance": [{"criterion": "行为保持", "evidence": "现有测试"}],
            "verification": [{"command": "just gate-core", "result": "通过"}],
            "requested_context": [], "blockers": [], "concerns": []}
        draft_path = self.directory / "direct-draft.json"
        self.h.put(draft_path, draft)
        output = self.directory / "direct-report.json"
        self.call("assemble", "--dispatch", self.dispatch, "--draft", draft_path,
            "--output", output, "--review", collected)
        self.assertEqual(json.loads(output.read_text())["test_plan"]["approved_seams"], [])






    def test_blocked_review_cannot_be_disguised_as_interruption(self):
        review = self.collect(self.round(blocking=True))
        self.assemble([review], status="BLOCKED", outcome="interrupted", ok=False)



    def test_same_head_report_correction_does_not_consume_stage(self):
        data = self.round(blocking=True)
        original = self.collect(data)
        receipt, report = self.assemble([original], status="BLOCKED", outcome="code_failure")
        original_bytes = report.read_bytes()
        selected = {}
        for axis, paths in data[2].items():
            original_report = Path(paths["report"])
            corrected = json.loads(original_report.read_text())
            corrected["findings"] = []
            report_path = original_report.parent / "report-2.json"
            receipt_path = original_report.parent / "receipt-2.json"
            self.h.put(report_path, corrected)
            self.h.put(receipt_path, {"status": "COMPLETED", "report_path": str(report_path),
                                     "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()})
            selected[axis] = {"report": str(report_path), "receipt": str(receipt_path)}
        selection = data[0].parent / "selection-2.json"
        self.h.put(selection, selected)
        collection = data[0].parent / "collection-2.json"
        self.call("review-collect", "--round", data[0], "--input", selection, "--output", collection)
        receipt, corrected = self.assemble([collection])
        value = json.loads(corrected.read_text())
        self.assertEqual((value["stage"], value["review"]["attempts"]), (0, 1))
        self.assertEqual(report.read_bytes(), original_bytes)


    def context_fixture(self):
        self.h.put(self.h.root / "ticket.json", [{"id": "test-1", "status": "in_progress",
                                                "description": "完整需求\n" * 10000}])
        self.h.put(self.h.root / "parent.json", [{"id": "test", "description": "父票约束"}])
        (self.h.root / "bin/bd").write_text(
            "#!" + sys.executable + "\nimport os,sys\nfrom pathlib import Path\n"
            "a=sys.argv[1:]\nassert a[0] in ('show','comments')\n"
            "root=Path(os.environ['BD_FIXTURE_SHOW']).parent\n"
            "name='comments' if a[0]=='comments' else ('ticket' if a[1]=='test-1' else 'parent')\n"
            "print((root/(name+'.json')).read_text())\n")

    def layer(self, files, message="test-1 本层完成，验证通过", ok=True):
        path = self.directory / "layer.json"
        self.h.put(path, {"files": files, "message": message})
        return self.call("check-layer", "--dispatch", self.dispatch, "--input", path, ok=ok)

    def test_inspect_resume_preserves_work_baseline_and_full_description(self):
        self.context_fixture()
        file = self.h.wt / "待完成\n文件.txt"
        file.write_text("保留")
        original = self.dispatch.read_bytes()
        result = self.call("inspect", "--dispatch", self.dispatch)
        self.assertIn(file.name, result["workspace"]["untracked"])
        self.assertEqual(Path(result["sources"]["ticket_description"]).read_text(), "完整需求\n" * 10000)
        self.assertTrue(result["commits"])
        self.assertEqual(file.read_text(), "保留")
        self.assertEqual(self.dispatch.read_bytes(), original)

    def test_inspect_new_rejects_dirty_and_moved_head(self):
        self.context_fixture()
        self.h.prepare(mode="new")
        self.dispatch = self.h.dispatch
        self.call("inspect", "--dispatch", self.dispatch)
        file = self.h.wt / "new.txt"
        file.write_text("变化")
        self.call("inspect", "--dispatch", self.dispatch, ok=False)
        self.h.h.git(self.h.wt, "add", "new.txt")
        self.h.h.git(self.h.wt, "commit", "-m", "test-1 新提交")
        self.call("inspect", "--dispatch", self.dispatch, ok=False)

    def test_inspect_failed_queries_preserve_sources(self):
        self.context_fixture()
        for value in ([], [{"id": "wrong"}], [{"id": "test-1", "status": "closed"}],
                      [{"id": "test-1", "status": "in_progress"}]):
            self.h.put(self.h.root / "ticket.json", value)
            error = self.call("inspect", "--dispatch", self.dispatch, ok=False)
            record = json.loads(error["error"])
            self.assertFalse(record["ok"])
            self.assertEqual(json.loads(Path(record["sources"]["ticket"]).read_text()), value)
        (self.h.root / "ticket.json").unlink()
        self.call("inspect", "--dispatch", self.dispatch, ok=False)

    def test_layer_special_paths_and_remaining_work_are_read_only(self):
        names = ["a b.txt", "换行\n文件.txt", "[literal]*.txt", "回车\r文件.txt"]
        for name in names:
            (self.h.wt / name).write_text("本层")
        self.h.h.git(self.h.wt, "add", "--", *names)
        (self.h.wt / "remaining.txt").write_text("后续工作")
        before = self.h.h.git(self.h.wt, "diff", "--cached")
        head = self.h.h.git(self.h.wt, "rev-parse", "HEAD")
        result = self.layer(names)
        self.assertEqual(result["remaining"], ["remaining.txt"])
        self.assertEqual(self.h.h.git(self.h.wt, "diff", "--cached"), before)
        self.assertEqual(self.h.h.git(self.h.wt, "rev-parse", "HEAD"), head)
        self.assertEqual((self.h.wt / "remaining.txt").read_text(), "后续工作")
        self.layer(names[:-1], ok=False)
        self.layer(names + ["missing.txt"], ok=False)
        self.layer(names, message="test-10 验证通过", ok=False)
        (self.h.wt / names[0]).write_text("暂存后又修改")
        self.layer(names, ok=False)

    def test_layer_rename_delete_and_beads(self):
        self.h.h.git(self.h.wt, "mv", "behavior.txt", "renamed file.txt")
        self.layer(["behavior.txt", "renamed file.txt"])
        self.h.h.git(self.h.wt, "commit", "-m", "test-1 重命名")
        self.h.h.git(self.h.wt, "rm", "renamed file.txt")
        self.layer(["renamed file.txt"])
        self.h.h.git(self.h.wt, "commit", "-m", "test-1 删除")
        self.layer(["missing"], ok=False)
        (self.h.wt / ".beads").mkdir(exist_ok=True)
        (self.h.wt / ".beads/data.json").write_text("{}")
        self.h.h.git(self.h.wt, "add", "-f", ".beads/data.json")
        self.layer([".beads/data.json"], ok=False)

    def test_inspect_and_layer_allow_primary_change(self):
        self.context_fixture()
        (self.h.wt / "new.txt").write_text("本层")
        self.h.h.git(self.h.wt, "add", "new.txt")
        (self.h.primary / "unexpected.txt").write_text("意外变化")
        self.call("inspect", "--dispatch", self.dispatch)
        self.layer(["new.txt"])
        self.assertEqual((self.h.primary / "unexpected.txt").read_text(), "意外变化")


if __name__ == "__main__":
    unittest.main()

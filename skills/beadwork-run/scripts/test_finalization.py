"""最终集成四阶段的行为回归；使用 controller 的真实临时 Git fixture。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_controller as controller_fixture


OPS = Path(__file__).with_name("executor-operations.py")


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.h = controller_fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.prepare("finalizer")
        self.root = self.h.dispatch
        if not getattr(self, 'strict_contract', False):
            # 保留 v1 历史文件验收用例；新派发 v2 由 test_handoff 覆盖。
            self.h.d['finalization_version'] = 1
            self.h.put(self.root, self.h.d)
        self.serial = 0

    def call(self, *args, ok=True):
        result = subprocess.run([sys.executable, "-B", str(OPS), *map(str, args)], cwd=self.h.root,
                                env=self.h.env, text=True, capture_output=True)
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
            facts.update(previous_stage=str(previous), previous_report=str(previous.with_name("report.json")),
                         previous_receipt=str(receipt))
        self.serial += 1
        source = self.h.root / f"final-stage-{self.serial}.json"
        self.put(source, facts)
        result = self.call("final-stage", "--dispatch", self.root, "--input", source, ok=ok)
        return Path(result["stage_path"]) if ok else result

    def review(self, dispatch, blocking=False, evidence=None):
        prepared = self.call("review-prepare", "--dispatch", dispatch, *(["--evidence", evidence] if evidence else []))
        sources = {}
        for axis, raw in prepared["axes"].items():
            identity = json.loads(Path(raw).read_text())
            report = {"axis": axis, "reviewed_base": identity["reviewed_base"],
                      "reviewed_head": identity["reviewed_head"], "notes": [], "findings": []}
            if blocking and axis == "standards":
                report["findings"] = [{"axis": axis, "kind": "defect", "blocking": True,
                                       "title": "需要修复", "evidence": "真实 review 证据"}]
            report_path = Path(identity["report_path"])
            self.put(report_path, report)
            receipt = report_path.parent / "receipt.json"
            self.put(receipt, {"status": "COMPLETED", "report_path": str(report_path),
                               "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()})
            sources[axis] = {"report": str(report_path), "receipt": str(receipt)}
            if identity.get('handoff_required'):
                cp = controller_fixture.closure_source(raw, report_path)
                sources[axis]['closure'] = json.loads(cp.read_text())['path']
        round_path = Path(prepared["round_path"])
        selection = round_path.parent / "selection.json"
        self.put(selection, sources)
        answer = self.call("review-collect", "--round", round_path, "--input", selection,
                           "--output", round_path.parent / "collection.json")
        return Path(answer["collection_path"])

    def draft(self, status, outcome, failed_gate=None):
        value = self.h.final_report()
        value.update(status=status, outcome=outcome)
        if status == "BLOCKED":
            value.update(blockers=["需要后续处理"], remaining_work=["继续当前阶段"], stopped_tasks=True)
        else:
            value.update(blockers=[], remaining_work=[], stopped_tasks=True)
        if failed_gate:
            value["verification"].append({"gate": failed_gate, "command": "just final " + failed_gate,
                                          "result": "失败", "log_path": "/evidence/failed.log",
                                          "head_commit": self.h.h.git(self.h.wt, "rev-parse", "HEAD"), "passed": False})
        return value

    def assemble(self, stage, *, reviews=(), fixes=(), status="BLOCKED", outcome="interrupted", failed_gate=None, ok=True):
        self.serial += 1
        folder = Path(stage).parent
        draft = folder / f"draft-{self.serial}.json"
        output = folder / "report.json"
        self.put(draft, self.draft(status, outcome, failed_gate))
        source = folder / f"fixers-{self.serial}.json"
        inherited_fixes = json.loads(Path(stage).read_text())["prior_fixes"]
        self.put(source, [*inherited_fixes, *fixes])
        args = ["final-assemble", "--dispatch", stage, "--draft", draft, "--output", output,
                "--fixers", source]
        inherited_reviews = [item["path"] for item in json.loads(Path(stage).read_text())["prior_reviews"]]
        for review in [*inherited_reviews, *reviews]:
            args.extend(("--review", review))
        answer = self.call(*args, ok=ok)
        if not ok:
            return answer
        receipt = folder / "receipt.json"
        self.put(receipt, {"status": answer["status"], "report_path": answer["report_path"],
                           "report_sha256": answer["report_sha256"]})
        return Path(answer["report_path"]), receipt

    def done_fixer(self, fixer_dispatch, messages=("修复一",)):
        d = json.loads(Path(fixer_dispatch).read_text())
        for index, message in enumerate(messages):
            self.serial += 1
            (self.h.wt / f"fix-{self.serial}-{index}.txt").write_text(message)
            self.h.h.git(self.h.wt, "add", ".")
            self.h.h.git(self.h.wt, "commit", "-m", message)
        head = self.h.h.git(self.h.wt, "rev-parse", "HEAD")
        commits = self.h.h.git(self.h.wt, "rev-list", "--reverse", d["base_commit"] + ".." + head).splitlines()
        verification = [{"gate": gate, "command": "just final " + gate, "result": "通过",
                         "log_path": "/evidence/" + gate + ".log", "head_commit": head, "passed": True}
                        for gate in ["final", *d["required_boundary_gates"]]]
        report = {"stage": d["stage"], "attempt_id": d["attempt_id"], "outcome": "passed",
                  "fix_commits": commits, "fix_commit": commits[-1], "status": "DONE",
                  "parent_id": d["parent_id"], "branch": d["branch"], "base_commit": d["base_commit"],
                  "head_commit": head, "dispositions": [{"source": "review", "action": "已修复"}],
                  "boundary_gates": d["required_boundary_gates"],
                  "gate_sources": [{"gate": gate, "source": "fixer"} for gate in d["required_boundary_gates"]],
                  "verification": verification, "worktree_clean": True, "stopped_tasks": True,
                  "uncommitted_files": [], "blockers": [], "remaining_work": []}
        report_path = Path(d["report_path"])
        self.put(report_path, report)
        receipt = report_path.parent / "receipt.json"
        self.put(receipt, {"status": "DONE", "report_path": str(report_path),
                           "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest()})
        return {"dispatch": self.bind(fixer_dispatch), "report": self.bind(report_path), "receipt": self.bind(receipt)}

    def test_external_blocking_review_delivers_but_cannot_enter_repair(self):
        stage = self.stage()
        report, receipt = self.assemble(stage, reviews=[self.review(stage, blocking=True)], outcome="blocked")
        self.h.deliver(json.loads(report.read_text()))
        self.h.accept()
        rejected = self.stage(previous=stage, receipt=receipt, continuation="repair", ok=False)
        self.assertIn("code_failure", rejected["error"])

    def test_complete_blocking_review_cannot_be_reported_as_interrupted(self):
        stage = self.stage()
        rejected = self.assemble(stage, reviews=[self.review(stage, blocking=True)], ok=False)
        self.assertIn("完整 BLOCKED review", rejected["error"])

    def test_stage_zero_matrix_and_reset_are_explicit(self):
        stage = self.stage()
        data = json.loads(stage.read_text())
        self.assertEqual(data["stage"], 0)
        self.assertEqual(data["models"], {"fixer": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
                                            "standards": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
                                            "spec": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"}})
        self.stage(ok=False)

    def test_four_code_failures_consume_the_fixed_four_stage_budget(self):
        stage = self.stage()
        report, receipt = self.assemble(stage, reviews=[self.review(stage, blocking=True)], outcome="code_failure")
        for expected in (1, 2, 3):
            stage = self.stage(previous=stage, receipt=receipt, continuation="repair")
            self.assertEqual(json.loads(stage.read_text())["stage"], expected)
            # final-stage 的返回值不写入 dispatch；本 fixture 从阶段目录取得唯一的 writer dispatch。
            fixer_dispatch = next(Path(stage).parent.joinpath("fixer").glob("dispatch.json"))
            fix = self.done_fixer(fixer_dispatch)
            review = self.review(stage, blocking=True)
            report, receipt = self.assemble(stage, reviews=[review], fixes=[fix], outcome="code_failure")
        self.stage(previous=stage, receipt=receipt, continuation="repair", ok=False)

    def test_done_fixer_reconstructs_stage_report_then_resume_skips_new_writer(self):
        initial = self.stage()
        report, receipt = self.assemble(initial, reviews=[self.review(initial, blocking=True)], outcome="code_failure")
        stage = self.stage(previous=initial, receipt=receipt, continuation="repair")
        fixer_dispatch = next(Path(stage).parent.joinpath("fixer").glob("dispatch.json"))
        fix = self.done_fixer(fixer_dispatch, ("修复一", "修复二"))
        # 此时还没有 stage report：final-assemble 以 DONE fixer 的 hash 绑定重建它，
        # 随后的 resume 才能明确知道同阶段 writer 已完成。
        report, receipt = self.assemble(stage, fixes=[fix])
        resumed = self.stage(previous=stage, receipt=receipt)
        resumed_data = json.loads(resumed.read_text())
        self.assertEqual(resumed_data["stage"], 1)
        self.assertFalse((Path(resumed).parent / "fixer").exists())
        self.assertEqual(resumed_data["prior_fixes"], [fix])
        tampered = json.loads(report.read_text())
        tampered["stage_sources"] = tampered["stage_sources"][:-1]
        report.write_text(json.dumps(tampered))
        self.stage(previous=stage, receipt=receipt, ok=False)

    def test_gate_failure_advances_without_a_review_round(self):
        stage = self.stage()
        report, receipt = self.assemble(stage, outcome="code_failure", failed_gate="gate-browser")
        next_stage = self.stage(previous=stage, receipt=receipt, continuation="repair")
        next_data = json.loads(next_stage.read_text())
        self.assertEqual(next_data["stage"], 1)
        self.assertEqual(next_data["prior_reviews"], [])

    def test_stale_stage_cannot_be_replayed_after_a_child_stage_exists(self):
        initial = self.stage()
        report, receipt = self.assemble(initial, reviews=[self.review(initial, blocking=True)], outcome="code_failure")
        self.stage(previous=initial, receipt=receipt, continuation="repair")
        # 只能从最新叶子接续；再次提交 stage 0 不能制造并行或重置的 stage 1。
        self.stage(previous=initial, receipt=receipt, continuation="repair", ok=False)

    def test_gate_failures_without_commits_exhaust_all_four_stages(self):
        stage = self.stage()
        for expected in range(4):
            self.assertEqual(json.loads(stage.read_text())["stage"], expected)
            report, receipt = self.assemble(stage, outcome="code_failure", failed_gate="gate-browser")
            if expected < 3:
                stage = self.stage(previous=stage, receipt=receipt, continuation="repair")
        self.stage(previous=stage, receipt=receipt, continuation="repair", ok=False)

    def test_four_stage_pipeline_uses_exact_models_and_final_pass_reaches_root_acceptance(self):
        expected_models = [
            {"fixer": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
             "standards": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
             "spec": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"}},
            {"fixer": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
             "standards": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
             "spec": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"}},
            {"fixer": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
             "standards": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
             "spec": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"}},
            {"fixer": {"model": "gpt-6-astra", "reasoning_effort": "medium"},
             "standards": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
             "spec": {"model": "gpt-6-astra", "reasoning_effort": "medium"}},
        ]
        stage = self.stage()
        for number in range(4):
            data = json.loads(stage.read_text())
            self.assertEqual(data["stage"], number)
            self.assertEqual(data["models"], expected_models[number])
            if number:
                fixer_dispatch = next((Path(stage).parent / "fixer").glob("dispatch.json"))
                fixes = [self.done_fixer(fixer_dispatch)]
            else:
                fixes = []
            review = self.review(stage, blocking=number < 3)
            report, receipt = self.assemble(stage, reviews=[review], fixes=fixes,
                                            status="BLOCKED" if number < 3 else "READY_TO_MERGE",
                                            outcome="code_failure" if number < 3 else "passed")
            if number < 3:
                stage = self.stage(previous=stage, receipt=receipt, continuation="repair")
        self.h.deliver(json.loads(report.read_text()))
        self.h.accept()

    def test_dirty_interruption_resumes_the_same_stage_and_base(self):
        initial = self.stage()
        report, receipt = self.assemble(initial, reviews=[self.review(initial, blocking=True)], outcome="code_failure")
        stage = self.stage(previous=initial, receipt=receipt, continuation="repair")
        before = json.loads(stage.read_text())
        (self.h.wt / "unfinished-fixer.txt").write_text("保留未提交修复")
        (self.h.primary / "manual.txt").write_text("手工编辑")
        # 没有阶段报告的中断恢复必须保留同一 BASE 和现场，而不是开始新额度。
        facts = {"previous_stage": str(stage), "continuation": "resume"}
        source = self.h.root / "dirty-resume.json"; self.put(source, facts)
        answer = self.call("final-stage", "--dispatch", self.root, "--input", source)
        resumed = Path(answer["stage_path"])
        after = json.loads(resumed.read_text())
        self.assertEqual(after["stage"], 1)
        self.assertEqual(after["stage_base"], before["stage_base"])
        self.assertTrue((self.h.wt / "unfinished-fixer.txt").exists())
        fixer = json.loads(next((resumed.parent / "fixer").glob("dispatch.json")).read_text())
        self.assertTrue(fixer["resume"])

    def test_modern_passing_stage_can_be_delivered_through_root_acceptance(self):
        stage = self.stage()
        report, _ = self.assemble(stage, reviews=[self.review(stage)], status="READY_TO_MERGE", outcome="passed")
        # controller 接收的交付位置仍是 root；阶段报告的不可变来源链保持原样。
        delivered = json.loads(report.read_text())
        self.h.deliver(delivered)
        self.h.accept()

    def test_legacy_done_import_retains_review_and_does_not_spawn_a_second_fixer(self):
        """旧的一修复格式只可带齐原始证据导入，且 DONE 不会重派 writer。"""
        old_dir = self.h.root / "legacy-final"; old_dir.mkdir()
        old_dispatch = dict(json.loads(self.root.read_text()))
        for key in ("finalization_version", "attempt_id", "attempt_path", "resume_stage", "stage", "models"):
            old_dispatch.pop(key, None)
        old_dispatch.update(dispatch_path=str(old_dir / "dispatch.json"), report_path=str(old_dir / "report.json"))
        self.put(old_dispatch["dispatch_path"], old_dispatch)
        # 旧 fixer 的 BASE 是旧报告 start_head，实际交付只有一个新 commit。
        (self.h.wt / "legacy-fix.txt").write_text("旧修复")
        self.h.h.git(self.h.wt, "add", "."); self.h.h.git(self.h.wt, "commit", "-m", "旧修复")
        head = self.h.h.git(self.h.wt, "rev-parse", "HEAD")
        fixer_dir = old_dir / "fixer"; fixer_dir.mkdir()
        fixer_dispatch = {"role": "fixer", "parent_id": "test", "branch": "implement/test",
                          "base_commit": old_dispatch["start_head"], "required_boundary_gates": ["gate-browser"],
                          "dispatch_path": str(fixer_dir / "dispatch.json"), "report_path": str(fixer_dir / "report.json")}
        self.put(fixer_dispatch["dispatch_path"], fixer_dispatch)
        fixer_report = {"status": "DONE", "parent_id": "test", "branch": "implement/test",
                        "base_commit": fixer_dispatch["base_commit"], "head_commit": head, "fix_commit": head,
                        "dispositions": [{"source": "review", "action": "已修复"}],
                        "boundary_gates": ["gate-browser"], "gate_sources": [{"gate": "gate-browser", "source": "fixer"}],
                        "verification": [{"gate": gate, "command": "just final " + gate, "result": "通过",
                                          "log_path": "/evidence/legacy.log", "head_commit": head, "passed": True}
                                         for gate in ("final", "gate-browser")],
                        "worktree_clean": True, "stopped_tasks": True, "uncommitted_files": [], "blockers": [], "remaining_work": []}
        self.put(fixer_dispatch["report_path"], fixer_report)
        fixer_receipt = fixer_dir / "receipt.json"
        self.put(fixer_receipt, {"status": "DONE", "report_path": fixer_dispatch["report_path"],
                                 "report_sha256": hashlib.sha256(Path(fixer_dispatch["report_path"]).read_bytes()).hexdigest()})
        # review 的 dispatch 本身也必须保持旧格式，避免借新版 attempt 身份偷渡旧证据。
        saved_root = self.root
        self.root = Path(old_dispatch["dispatch_path"])
        review = self.review(self.root)
        self.root = saved_root
        pair = json.loads(review.read_text())["pair"]
        legacy = self.h.final_report()
        legacy.update(status="BLOCKED", head_commit=head, review_rounds=[pair],
                      fix={"used": True, "commits": [head], "dispositions": ["review：已修复"]},
                      blockers=["等待下一次最终审阅"], remaining_work=["恢复 review"], stopped_tasks=True)
        for item in legacy["verification"]: item["head_commit"] = head
        self.put(old_dispatch["report_path"], legacy)
        legacy_receipt = old_dir / "receipt.json"
        self.put(legacy_receipt, {"status": "BLOCKED", "report_path": old_dispatch["report_path"],
                                  "report_sha256": hashlib.sha256(Path(old_dispatch["report_path"]).read_bytes()).hexdigest()})
        self.h.prepare("finalizer", prior_finalization={"fix_used": True, "review_rounds_used": 1,
                                                         "report_path": old_dispatch["report_path"]})
        self.root = self.h.dispatch
        # 历史格式导入能力仍按 v1 检验；缺少实测来源的新 v2 导入应阻塞。
        self.h.d['finalization_version'] = 1
        self.h.put(self.root, self.h.d)
        facts = {"legacy_dispatch": str(old_dispatch["dispatch_path"]), "legacy_receipt": str(legacy_receipt),
                 "legacy_reviews": [str(review)], "legacy_fixes": [{"dispatch": self.bind(fixer_dispatch["dispatch_path"]),
                 "report": self.bind(fixer_dispatch["report_path"]), "receipt": self.bind(fixer_receipt)}],
                 "legacy_fixer_dispatch": str(fixer_dispatch["dispatch_path"]), "continuation": "resume"}
        source = self.h.root / "legacy-import.json"; self.put(source, facts)
        answer = self.call("final-stage", "--dispatch", self.root, "--input", source)
        imported = Path(answer["stage_path"])
        data = json.loads(imported.read_text())
        self.assertEqual(data["stage"], 1)
        self.assertEqual(len(data["prior_reviews"]), 1)
        self.assertFalse((imported.parent / "fixer").exists())


    def test_primary_edit_allows_stage_review_assembly_and_acceptance(self):
        (self.h.primary / "manual.txt").write_text("手工修改")
        stage = self.stage()
        review = self.review(stage)
        report, receipt = self.assemble(stage, status="READY_TO_MERGE", outcome="passed", reviews=[review])
        self.assertNotIn("primary_clean", json.loads(report.read_text())["workspace"])
        self.h.deliver(json.loads(report.read_text()))
        self.h.accept()
        self.assertEqual((self.h.primary / "manual.txt").read_text(), "手工修改")


if __name__ == "__main__":
    unittest.main()

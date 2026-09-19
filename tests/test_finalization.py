"""最终集成六阶段的行为回归；使用 controller 的真实临时 Git fixture。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_controller as controller_fixture


OPS = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/executor-operations.py"


class FinalizationTests(unittest.TestCase):
    def setUp(self):
        self.h = controller_fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.prepare("finalizer")
        self.root = self.h.dispatch
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
        return {'status': status, 'outcome': outcome, 'boundary_gates': ['gate-browser'],
                'gate_sources': [{'gate': 'gate-browser', 'source': 'ticket'}],
                'verification_notes': {}, 'stopped_tasks': True, 'sources': [], 'verification': [],
                'blockers': [] if status == 'READY_TO_MERGE' else ['需要后续处理'],
                'remaining_work': [] if status == 'READY_TO_MERGE' else ['继续当前阶段']}

    def assemble(self, stage, *, reviews=(), fixes=(), status="BLOCKED", outcome="interrupted", failed_gate=None,
                 implicit=False, ok=True):
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
        verification = [{"gate": gate, "command": "just " + gate, "result": "通过",
                         "log_path": "/evidence/" + gate + ".log", "head_commit": head, "passed": True}
                        for gate in ["gate-full"]]
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

    def gate(self, dispatch):
        binary = self.h.root / 'bin/just'
        binary.write_text('#!' + sys.executable + '\nimport sys\nif sys.argv[1:]==["--summary"]: print("check-toolchain install typecheck test gate-plan gate-core gate-full gate-browser env-facts fmt")\nelif sys.argv[3]=="gate-plan": print(\'{"core":"gate-core","full":["gate-core","gate-browser"]}\')\nelse: print("collected 1 check")\n')
        binary.chmod(0o755)
        result = subprocess.run([sys.executable, '-B', str(OPS.with_name('run-verification.py')),
            '--dispatch', str(dispatch), '--recipe', 'gate-full', '--delivery'],
            cwd=self.h.root, env=self.h.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stage_zero_matrix_and_resume_use_same_checkpoint(self):
        stage = self.stage()
        data = json.loads(stage.read_text())
        self.assertEqual(data['stage'], 0)
        self.assertEqual(data['models']['fixer'], {'model': 'gpt-5.6-terra', 'reasoning_effort': 'medium'})
        self.assertEqual(self.stage(), stage)

    def test_external_blocking_review_delivers_but_cannot_enter_repair(self):
        stage = self.stage(); self.gate(stage)
        self.review(stage, blocking=True)
        report, receipt = self.assemble(stage, outcome='blocked')
        self.h.deliver(json.loads(report.read_text())); self.h.accept()
        rejected = self.stage(previous=stage, receipt=receipt, continuation='repair', ok=False)
        self.assertIn('code_failure', rejected['error'])

    def test_complete_blocking_review_cannot_be_reported_as_interrupted(self):
        stage = self.stage(); self.gate(stage); self.review(stage, blocking=True)
        rejected = self.assemble(stage, ok=False)
        self.assertIn('review', rejected['error'])

    def test_current_passing_stage_reaches_root_acceptance(self):
        stage = self.stage(); self.gate(stage); self.review(stage)
        self.assemble(stage, status='READY_TO_MERGE', outcome='passed')
        delivered = self.call('final-deliver', '--dispatch', self.root, '--output', self.root.parent / 'delivered.json')
        self.h.deliver(json.loads(Path(delivered['report_path']).read_text())); self.h.accept()

        comment = self.h.dispatch.parent / 'integration.md'
        self.h.call('comment', '--acceptance', self.h.acceptance, '--summary', '批次已完成', '--output', comment)
        self.h.put(self.h.root / 'comments.json', [{'id': 7, 'text': comment.read_text()}])
        merge_record = self.h.dispatch.parent / 'merge.json'
        self.h.call('merge', '--acceptance', self.h.acceptance, '--comment-id', '7', '--output', merge_record)
        self.assertEqual(self.h.h.git(self.h.primary, 'rev-parse', 'HEAD'), self.h.h.head)

    def test_primary_edit_allows_stage_review_assembly_and_acceptance(self):
        (self.h.primary / 'manual.txt').write_text('手工修改')
        stage = self.stage(); self.gate(stage); self.review(stage)
        self.assemble(stage, status='READY_TO_MERGE', outcome='passed')
        delivered = self.call('final-deliver', '--dispatch', self.root, '--output', self.root.parent / 'delivered.json')
        self.h.deliver(json.loads(Path(delivered['report_path']).read_text())); self.h.accept()
        self.assertEqual((self.h.primary / 'manual.txt').read_text(), '手工修改')

    def six_stage_pipeline_uses_exact_models_and_final_pass_reaches_root_acceptance(self):
        tm = {"model": "gpt-5.6-terra", "reasoning_effort": "medium"}
        th = {"model": "gpt-5.6-terra", "reasoning_effort": "high"}
        sm = {"model": "gpt-5.6-sol", "reasoning_effort": "medium"}
        expected_models = [
            {"fixer": tm, "standards": th, "spec": sm},
            {"fixer": tm, "standards": th, "spec": sm},
            {"fixer": tm, "standards": sm, "spec": sm},
            {"fixer": th, "standards": sm, "spec": sm},
            {"fixer": th, "standards": sm, "spec": sm},
            {"fixer": sm, "standards": sm, "spec": sm},
        ]
        stage = self.stage()
        for number in range(6):
            data = json.loads(stage.read_text())
            self.assertEqual(data["stage"], number)
            self.assertEqual(data["models"], expected_models[number])
            if number:
                fixer_dispatch = next((Path(stage).parent / "fixer").glob("dispatch.json"))
                fixes = [self.done_fixer(fixer_dispatch)]
            else:
                fixes = []
            review = self.review(stage, blocking=number < 5)
            report, receipt = self.assemble(stage, reviews=[review], fixes=fixes,
                                            status="BLOCKED" if number < 5 else "READY_TO_MERGE",
                                            outcome="code_failure" if number < 5 else "passed")
            if number < 5:
                stage = self.stage(previous=stage, receipt=receipt, continuation="repair")
        self.h.deliver(json.loads(report.read_text()))
        self.h.accept()


if __name__ == '__main__':
    unittest.main()

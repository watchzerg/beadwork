"""批次初始化、恢复事实、manifest 与摘要的公开事实边界。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import batch_evidence
import batch_initialize
import evidence


class BatchOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"; self.root.mkdir()
        self.git("init", "-b", "main"); self.git("config", "user.email", "test@example.com"); self.git("config", "user.name", "Test")
        (self.root / "base.txt").write_text("base"); self.git("add", "."); self.git("commit", "-m", "base")
        (self.root / ".git/info/exclude").write_text(".worktrees/\n")
        self.bin = self.root / "bin"; self.bin.mkdir(); self.state = self.root / "tracker.json"
        self.state.write_text(json.dumps({"issue": {"id": "demo", "status": "open", "assignee": None}, "comments": []}))
        bd = self.bin / "bd"; bd.write_text("#!" + sys.executable + "\n" + '''import json,os,sys
from pathlib import Path
p=Path(os.environ['TRACKER_STATE']);s=json.loads(p.read_text());a=sys.argv[1:]
if a[0]=='show': print(json.dumps([s['issue']]))
elif a[:2]==['update','demo']: s['issue'].update(status='in_progress',assignee='fixture');p.write_text(json.dumps(s));print('{}')
else: print('[]')
'''); bd.chmod(0o755)
        just = self.bin / "just"; just.write_text("#!/bin/sh\necho $@\n"); just.chmod(0o755)
        old = os.environ.get("PATH", ""); os.environ["PATH"] = str(self.bin) + os.pathsep + old
        os.environ["TRACKER_STATE"] = str(self.state); self.addCleanup(lambda: os.environ.__setitem__("PATH", old))

    def git(self, *args):
        p = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr); return p.stdout.strip()

    def acceptance(self, role, ticket=None):
        folder = self.root / (role + ("-" + ticket if ticket else "")); folder.mkdir()
        gate_plan_path = folder / 'gate-plan.json'
        evidence.write(gate_plan_path, {"core": "gate-core", "full": ["gate-core", "gate-demo"]})
        dispatch = {"role": role, "parent_id": "demo", "ticket_id": ticket,
                    "dispatch_path": str(folder / "dispatch.json")}
        report = ({"status": "READY", "expected_children": ["demo-1"],
                   "gate_plan": {"core": "gate-core", "full": ["gate-core", "gate-demo"]},
                   "gate_plan_source": evidence.binding(gate_plan_path)} if role == "preflight" else
                  {"status": "DONE", "base_commit": self.git("rev-parse", "HEAD"),
                   "head_commit": self.git("rev-parse", "HEAD"), "implementation_commits": [],
                   "required_boundary_gates": ["gate-demo"]})
        receipt = {"status": report["status"]}
        for name, value in (("dispatch", dispatch), ("report", report), ("receipt", receipt)):
            evidence.write(folder / (name + ".json"), value)
        accepted = {"kind": "mechanical_acceptance", "role": role, "status": report["status"]}
        for name in ("dispatch", "report", "receipt"):
            path = folder / (name + ".json"); accepted[name + "_path"] = str(path); accepted[name + "_sha256"] = evidence.digest(path)
        path = folder / "accepted.json"; evidence.write(path, accepted); return path

    def test_initialization_is_resumable(self):
        accepted = self.acceptance("preflight")
        source = self.root / "init-input.json"; evidence.write(source, {
            "repository_root": str(self.root), "parent_id": "demo", "expected_children": ["demo-1"],
            "preflight_acceptance": evidence.binding(accepted), "install_inputs": ["package.json"],
            "expected_assignee": "fixture"})
        folder = self.root / ".worktrees/.evidence/demo/initialize"; folder.mkdir(parents=True)
        intent = folder / "intent.json"; batch_initialize.prepare(source, intent)
        first = batch_initialize.execute(intent)
        (folder / "ready.json").unlink()  # 模拟全部步骤完成、最终记录写出前中断。
        second = batch_initialize.execute(intent)
        self.assertEqual(first, second); self.assertTrue(Path(first["worktree"]).exists())
        self.assertEqual(json.loads(self.state.read_text())["issue"]["status"], "in_progress")

    def test_manifest_and_summary(self):
        accepted = self.acceptance("executor", "demo-1")
        source = self.root / "manifest-input.json"; evidence.write(source, {
            "parent_id": "demo", "expected_children": ["demo-1"], "acceptances": [evidence.binding(accepted)]})
        manifest = batch_evidence.manifest(source); self.assertEqual(manifest["required_boundary_gates"], ["gate-demo"])
        manifest_path = self.root / "manifest.json"; evidence.write(manifest_path, manifest)
        facts = batch_evidence.inspect(self.root, "demo"); facts_path = self.root / "facts.json"; evidence.write(facts_path, facts)
        summary_input = self.root / "summary-input.json"; evidence.write(summary_input, {
            "facts": evidence.binding(facts_path), "manifest": evidence.binding(manifest_path),
            "status": "BLOCKED", "cause": "等待外部确认", "uncertainties": ["宿主任务状态"], "recommendation": "核对后恢复"})
        result = batch_evidence.summary(summary_input)
        self.assertIn("demo-1", result["text"]); self.assertTrue(result["facts"]["external_stop_observation_required"])

        bad = self.root / "bad-manifest.json"; evidence.write(bad, {
            "parent_id": "demo", "expected_children": ["demo-2"], "acceptances": [evidence.binding(accepted)]})
        with self.assertRaises(ValueError): batch_evidence.manifest(bad)
        Path(json.loads(accepted.read_text())["report_path"]).write_text("{}")
        with self.assertRaises(ValueError): batch_evidence.manifest(source)

    def test_inspect_reports_ambiguous_pending_operations(self):
        for name in ("a", "b"):
            folder = self.root / ".worktrees/.evidence/demo" / name; folder.mkdir(parents=True, exist_ok=True)
            evidence.write(folder / "intent.json", {"name": name})
        before = self.git("status", "--porcelain=v1", "--untracked-files=all")
        facts = batch_evidence.inspect(self.root, "demo")
        self.assertEqual(self.git("status", "--porcelain=v1", "--untracked-files=all"), before)
        self.assertEqual(len(facts["pending_operations"]), 2)
        self.assertTrue(facts["conflicts"])


if __name__ == "__main__": unittest.main()

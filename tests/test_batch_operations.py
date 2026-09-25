"""批次初始化、恢复事实、manifest 与摘要的公开事实边界。"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

import batch_evidence
import batch_initialize
import evidence
import execution_plan
import operation_commands
import repository
import test_controller as controller_fixture
import test_finalization as final_fixture
import test_ticket_execution as ticket_fixture
import test_verify_phase as phase_fixture
import test_verify_ticket as git_fixture

pytestmark = pytest.mark.workflow


BD_FIXTURE = r"""import json,os,sys,subprocess
from pathlib import Path
p=Path(os.environ['TRACKER_STATE']);s=json.loads(p.read_text());a=sys.argv[1:];root=p.parent
if a[0]=='show': print(json.dumps([s['issue']]))
elif a[0] in ('list','ready'): print(json.dumps(s['children']))
elif a[0]=='dep': print('[]')
elif a[:2]==['worktree','create']:
 subprocess.run(['git','-C',str(root),'worktree','add','-b',a[a.index('--branch')+1],a[2]],check=True)
elif a[:2]==['worktree','info']: print(json.dumps({'is_worktree':Path.cwd()!=root}))
elif a[0]=='where':
 place=root/'.beads' if not s.get('wrong_workspace') or Path.cwd()==root else root/'wrong'
 print(json.dumps({'path':str(place),'database_path':str(place/'db')}))
elif a[:2]==['update','demo']:
 s['issue'].update(status='in_progress',assignee='fixture');p.write_text(json.dumps(s));print('{}')
elif a[:2]==['comments','add']:
 body=Path(a[a.index('-f')+1]).read_text();s['comments'].append({'id':len(s['comments'])+1,'text':body});p.write_text(json.dumps(s));print('{}')
elif a[0]=='comments': print(json.dumps(s['comments']))
else: sys.exit(2)
"""
JUST_FIXTURE = r"""import json,os,sys
from pathlib import Path
p=Path(os.environ['TRACKER_STATE']);s=json.loads(p.read_text())
if sys.argv[1:]==['--summary']:
 print('install test gate-core gate-full');sys.exit(0)
recipe=sys.argv[3]
assert recipe in ('install','test','gate-core','gate-full'), recipe
s.setdefault('runs',[]).append(recipe);p.write_text(json.dumps(s))
print('执行 '+recipe)
if recipe=='gate-full':
 s=json.loads(p.read_text());s['runs'] += ['gate-core','database-suite','browser-suite'];p.write_text(json.dumps(s))
sys.exit(1 if s.get('fail')==recipe else 0)
"""


class BatchOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "repo"
        self.root.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "Test")
        (self.root / "base.txt").write_text("base")
        self.git("add", ".")
        self.git("commit", "-m", "base")
        (self.root / ".git/info/exclude").write_text("*\n")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.state = self.root / "tracker.json"
        self.state.write_text(
            json.dumps(
                {
                    "issue": {
                        "id": "demo",
                        "status": "open",
                        "assignee": None,
                        "description": execution_plan.replace("", {"ticket_order": ["demo-1"]}),
                    },
                    "children": [{"id": "demo-1", "status": "open"}],
                    "comments": [],
                }
            )
        )
        bd = self.bin / "bd"
        bd.write_text("#!" + sys.executable + "\n" + BD_FIXTURE)
        bd.chmod(0o755)
        just = self.bin / "just"
        just.write_text("#!" + sys.executable + "\n" + JUST_FIXTURE)
        just.chmod(0o755)
        environment = patch.dict(
            os.environ,
            {
                "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
                "TRACKER_STATE": str(self.state),
            },
        )
        environment.start()
        self.addCleanup(environment.stop)

    def git(self, *args):
        p = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def acceptance(self, role, ticket=None):
        folder = self.root / (role + ("-" + ticket if ticket else ""))
        folder.mkdir()
        dispatch = {
            "role": role,
            "parent_id": "demo",
            "ticket_id": ticket,
            "dispatch_path": str(folder / "dispatch.json"),
            "repository_root": str(self.root),
        }
        report = (
            {
                "status": "READY",
                "expected_children": ["demo-1"],
                "suggested_route": "new_batch",
                "execution_plan": {"ticket_order": ["demo-1"]},
            }
            if role == "preflight"
            else {
                "status": "DONE",
                "base_commit": self.git("rev-parse", "HEAD"),
                "head_commit": self.git("rev-parse", "HEAD"),
                "implementation_commits": [],
            }
        )
        receipt = {"status": report["status"]}
        for name, value in (("dispatch", dispatch), ("report", report), ("receipt", receipt)):
            evidence.write(folder / (name + ".json"), value)
        accepted = {"kind": "mechanical_acceptance", "role": role, "status": report["status"]}
        for name in ("dispatch", "report", "receipt"):
            path = folder / (name + ".json")
            accepted[name + "_path"] = str(path)
            accepted[name + "_sha256"] = evidence.digest(path)
        path = folder / "accepted.json"
        evidence.write(path, accepted)
        return path

    def initialize(self, accepted=None):
        accepted = accepted or self.acceptance("preflight")
        report_path = accepted.parent / "report.json"
        report = evidence.read(report_path)
        children = evidence.read(self.state)["children"]
        selected = execution_plan.adopt(
            str(self.root),
            "demo",
            report["execution_plan"],
            children,
            [evidence.binding(report_path)],
            "测试批准",
        )
        value = evidence.read(accepted)
        value["execution_plan_source"] = selected
        accepted.write_text(json.dumps(value))
        update = self.root / "update-main.json"
        evidence.write(
            update,
            {
                "repository_root": str(self.root),
                "main_commit": self.git("rev-parse", "HEAD"),
                "fetch_failed": False,
                "note": "",
            },
        )
        source = self.root / "init-input.json"
        evidence.write(
            source,
            {
                "repository_root": str(self.root),
                "parent_id": "demo",
                "expected_children": report["expected_children"],
                "preflight_acceptance": evidence.binding(accepted),
                "update_main_result": evidence.binding(update),
                "expected_assignee": "fixture",
            },
        )
        folder = self.root / ".worktrees/.evidence/demo/initialize/first"
        folder.mkdir(parents=True)
        intent = folder / "intent.json"
        self.cli("prepare", "--input", source, "--output", intent)
        return intent

    def cli(self, *args, ok=True):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(batch_initialize.__file__).with_name("beadwork.py")),
                "batch-initialize",
                *map(str, args),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def change_state(self, **fields):
        value = json.loads(self.state.read_text())
        value.update(fields)
        self.state.write_text(json.dumps(value))

    def test_initialization_uses_four_recipe_project_and_binds_logs(self):
        real_just = shutil.which(
            "just", path=os.pathsep.join(os.environ["PATH"].split(os.pathsep)[1:])
        )
        self.assertIsNotNone(real_just)
        justfile = self.root / "justfile"
        justfile.write_text(
            "install:\n    @echo '准备完成'\n"
            "test *ARGS:\n    @echo 'collected 1 test'\n"
            "gate-core:\n    @echo '基础检查通过'\n    @echo '检查诊断' >&2\n"
            "gate-full:\n    @echo '完整检查通过'\n"
        )
        (self.bin / "just").write_text(
            "#!"
            + sys.executable
            + "\nimport os,sys\n"
            + f"os.execv({real_just!r}, [{real_just!r}, '--justfile', {str(justfile)!r}, *sys.argv[1:]])\n"
        )
        ready = self.cli("execute", "--intent", self.initialize())
        source = next(
            entry
            for entry in ready["commands"]
            if operation_commands.read(entry)[1]["argv"][-1] == "gate-core"
        )
        _, _, log = operation_commands.read(source)
        self.assertIn("基础检查通过", log.read_text())
        self.assertIn("检查诊断", log.read_text())
        log.write_text("tampered")
        with self.assertRaises(ValueError):
            operation_commands.read(source)

    def test_failed_core_retries_without_reinstall_or_early_claim(self):
        intent = self.initialize()
        self.change_state(fail="gate-core")
        self.cli("execute", "--intent", intent, ok=False)
        state = evidence.read(self.state)
        self.assertEqual(state["runs"], ["install", "gate-core"])
        self.assertEqual(state["issue"]["status"], "open")
        self.assertEqual(state["comments"], [])
        first = next((intent.parent / "gate-core").glob("attempt-*"))
        preserved = {path: path.read_bytes() for path in first.iterdir()}
        self.change_state(fail=None)
        self.cli("execute", "--intent", intent)
        self.assertEqual(evidence.read(self.state)["runs"], ["install", "gate-core", "gate-core"])
        self.assertEqual({path: path.read_bytes() for path in first.iterdir()}, preserved)

    def test_default_two_ticket_trace_runs_full_only_at_finalize(self):
        order = ["demo-1", "demo-2"]
        state = evidence.read(self.state)
        state["issue"]["description"] = execution_plan.replace("", {"ticket_order": order})
        self.change_state(
            issue=state["issue"],
            children=[
                {"id": ticket, "status": "open", "labels": ["ready-for-agent"]} for ticket in order
            ],
        )
        # 复用现有 CLI/review helper；所有阶段共用本次初始化产生的 worktree。
        h = controller_fixture.ControllerTests()
        h.root = h.primary = self.root
        h.wt = self.root / ".worktrees/demo"
        h.env = dict(os.environ)
        h.h = git_fixture.TicketAcceptanceTests()
        h.h.env = h.env
        h.utility_fixture = False
        h.counter = 0
        prepared = h.call(
            "prepare",
            "preflight",
            "--input",
            h.put(
                self.root / "preflight-input.json",
                {
                    "repository_root": str(self.root),
                    "parent_id": "demo",
                    "rules_paths": [],
                },
            ),
        )
        pd = Path(prepared["dispatch_path"])
        report = phase_fixture.PhaseValidatorTests().preflight()
        report.update(
            parent={"id": "demo", "status": "open"},
            expected_children=order,
            execution_plan={"ticket_order": order},
            tickets=[
                {
                    "id": ticket,
                    "status": "open",
                    "test_plan": {
                        **phase_fixture.PhaseValidatorTests().plan("direct_verification"),
                        "verification": "just test 相关场景",
                    },
                }
                for ticket in order
            ],
            workspace={
                "primary_worktree": str(self.root),
                "implementation_worktree": str(h.wt),
                "branch": "implement/demo",
                "observed_head": self.git("rev-parse", "HEAD"),
                "clean": True,
            },
        )
        rp = Path(h.put(pd.parent / "report.json", report))
        rr = h.put(
            pd.parent / "receipt.json",
            {"status": "READY", "report_path": str(rp), "report_sha256": evidence.digest(rp)},
        )
        accepted = pd.parent / "accepted.json"
        h.call("accept", "--dispatch", pd, "--report", rp, "--receipt", rr, "--output", accepted)
        initialized = self.cli("execute", "--intent", self.initialize(accepted))
        self.assertEqual(initialized["worktree"], str(h.wt))
        common = {
            "repository_root": str(self.root),
            "parent_id": "demo",
            "expected_children": order,
            "install_inputs": ["justfile"],
        }
        acceptances = []
        for ticket in order:
            sync = h.call(
                "sync-main",
                "--input",
                h.put(
                    self.root / f"sync-{ticket}.json",
                    {
                        **common,
                    },
                ),
            )
            self.assertFalse(sync["changed"])
            prepared = h.call(
                "prepare",
                "executor",
                "--input",
                h.put(
                    self.root / f"input-{ticket}.json",
                    {
                        "repository_root": str(self.root),
                        "parent_id": "demo",
                        "ticket_id": ticket,
                        "mode": "new",
                        "test_mode": "direct_verification",
                        "approved_seams": [],
                        "rules_paths": [],
                        "testing_seams_doc": "/rules/testing-seams.md",
                        "linked_spec": "spec",
                        "sync_result": sync["sync_result"],
                        "preflight_acceptance": evidence.binding(accepted),
                    },
                ),
            )
            worker = ticket_fixture.TicketExecutionTests()
            worker.h, worker.serial = h, 0
            worker.root_dispatch = Path(prepared["dispatch_path"])
            worker.stage()
            (h.wt / "base.txt").write_text(ticket)
            repository.git(h.wt, "add", "base.txt")
            repository.git(h.wt, "commit", "-m", ticket + " 实现")
            worker.gate("test", delivery=False)
            worker.gate()
            worker.implement()
            worker.assemble([worker.review()])
            worker.deliver()
            acceptances.append(evidence.binding(worker.acceptance))
            completion = worker.root_dispatch.parent / "completion.md"
            h.call(
                "comment",
                "--acceptance",
                worker.acceptance,
                "--summary",
                "本票完成",
                "--output",
                completion,
            )
            self.assertIn(
                "完整项目回归由 parent finalize 的 gate-full 验收。", completion.read_text()
            )
            state = evidence.read(self.state)
            next(child for child in state["children"] if child["id"] == ticket)["status"] = "closed"
            self.change_state(children=state["children"])
        manifest = batch_evidence.manifest(
            h.put(
                self.root / "manifest-input.json",
                {
                    "parent_id": "demo",
                    "expected_children": order,
                    "acceptances": acceptances,
                },
            )
        )
        self.assertEqual([row["ticket_id"] for row in manifest["tickets"]], order)
        boundaries = ["database-suite", "browser-suite"]
        before_final = evidence.read(self.state)["runs"]
        self.assertEqual(before_final.count("gate-core"), 3)
        self.assertNotIn("gate-full", before_final)
        self.assertTrue(all(gate not in before_final for gate in boundaries))
        sync = h.call(
            "sync-final",
            "--input",
            h.put(
                self.root / "sync-final.json",
                {
                    **common,
                    "reviewed_main": self.git("rev-parse", "HEAD"),
                },
            ),
        )
        prepared = h.call(
            "prepare",
            "finalizer",
            "--input",
            h.put(
                self.root / "final-input.json",
                {
                    **common,
                    "rules_paths": [],
                    "linked_spec": "spec",
                    "ticket_evidence": acceptances,
                    "prior_finalization": None,
                    "reviewed_main": self.git("rev-parse", "HEAD"),
                    "final_sync_result": sync["sync_result"],
                },
            ),
        )
        final = final_fixture.FinalizationTests()
        final.h, final.serial = h, 0
        final.root = Path(prepared["dispatch_path"])
        stage = final.stage()
        worker.cli("run-verification", "--dispatch", stage, "--recipe", "gate-full", "--delivery")
        final.review(stage)
        draft = final.draft("READY_TO_MERGE", "passed")
        final.call(
            "final-assemble",
            "--dispatch",
            stage,
            "--draft",
            h.put(stage.parent / "draft.json", draft),
            "--output",
            stage.parent / "report.json",
        )
        delivered = final.call(
            "final-deliver",
            "--dispatch",
            final.root,
            "--output",
            final.root.parent / "delivered.json",
        )
        h.dispatch, h.d = final.root, evidence.read(final.root)
        h.deliver(evidence.read(delivered["report_path"]))
        h.accept()
        runs = evidence.read(self.state)["runs"]
        self.assertEqual(runs.count("gate-full"), 1)
        self.assertEqual(runs.count("gate-core"), 4)
        self.assertTrue(all(runs.count(gate) == 1 for gate in boundaries))
        # manifest 只读已绑定的历史报告；来源损坏仍须拒绝。
        worker.writer_report.write_text("{}")
        with self.assertRaisesRegex(ValueError, "证据文件已变化"):
            batch_evidence.manifest(self.root / "manifest-input.json")

    def test_install_failure_and_gate_failure_resume_without_claiming_early(self):
        intent = self.initialize()
        self.change_state(fail="install")
        self.cli("execute", "--intent", intent, ok=False)
        self.assertEqual(json.loads(self.state.read_text())["issue"]["status"], "open")
        self.change_state(fail="gate-core")
        self.cli("execute", "--intent", intent, ok=False)
        self.assertEqual(json.loads(self.state.read_text())["comments"], [])
        self.change_state(fail="")
        self.cli("execute", "--intent", intent)
        self.assertEqual(
            json.loads(self.state.read_text())["runs"],
            [
                "install",
                "install",
                "gate-core",
                "gate-core",
            ],
        )
        self.assertEqual(len(list((intent.parent / "install").glob("attempt-*"))), 2)

    def test_unknown_command_requires_bound_stop_observation(self):
        intent = self.initialize()
        self.change_state(fail="install")
        self.cli("execute", "--intent", intent, ok=False)
        run = next((intent.parent / "install").glob("attempt-*"))
        (run / "result.json").unlink()
        self.change_state(fail="")
        error = self.cli("execute", "--intent", intent, ok=False)
        self.assertIn("收尾", error["error"])
        recovery = self.root / "recovery.json"
        evidence.write(
            recovery,
            [
                {
                    "run_path": str(run),
                    "task_id": "fixture",
                    "stopped": True,
                    "observed_at": "2026-09-17T00:00:00Z",
                    "evidence": "测试进程已退出",
                    "unresolved": [],
                }
            ],
        )
        self.cli("execute", "--intent", intent, "--recovery", recovery)
        self.assertTrue((run / "closure.json").exists())

    def test_lost_claim_and_comment_results_are_read_back_without_duplication(self):
        intent = self.initialize()
        first = self.cli("execute", "--intent", intent)
        self.assertEqual(first, self.cli("execute", "--intent", intent))
        for name in ("ready.json", "claim-intent-result.json", "comment-intent-result.json"):
            (intent.parent / name).unlink()
        again = self.cli("execute", "--intent", intent)
        self.assertEqual(first["comment_id"], again["comment_id"])
        self.assertEqual(len(json.loads(self.state.read_text())["comments"]), 1)
        self.assertEqual(evidence.read(self.state)["runs"], ["install", "gate-core"])

    def test_manifest_and_summary(self):
        accepted = self.acceptance("executor", "demo-1")
        source = self.root / "manifest-input.json"
        evidence.write(
            source,
            {
                "parent_id": "demo",
                "expected_children": ["demo-1"],
                "acceptances": [evidence.binding(accepted)],
            },
        )
        manifest = batch_evidence.manifest(source)
        self.assertEqual([row["ticket_id"] for row in manifest["tickets"]], ["demo-1"])
        manifest_path = self.root / "manifest.json"
        evidence.write(manifest_path, manifest)
        facts = batch_evidence.inspect(self.root, "demo")
        facts_path = self.root / "facts.json"
        evidence.write(facts_path, facts)
        summary_input = self.root / "summary-input.json"
        evidence.write(
            summary_input,
            {
                "facts": evidence.binding(facts_path),
                "manifest": evidence.binding(manifest_path),
                "status": "BLOCKED",
                "cause": "等待外部确认",
                "uncertainties": ["宿主任务状态"],
                "recommendation": "核对后恢复",
            },
        )
        result = batch_evidence.summary(summary_input)
        self.assertIn("demo-1", result["text"])
        self.assertTrue(result["facts"]["external_stop_observation_required"])

        bad = self.root / "bad-manifest.json"
        evidence.write(
            bad,
            {
                "parent_id": "demo",
                "expected_children": ["demo-2"],
                "acceptances": [evidence.binding(accepted)],
            },
        )
        with self.assertRaises(ValueError):
            batch_evidence.manifest(bad)
        Path(json.loads(accepted.read_text())["report_path"]).write_text("{}")
        with self.assertRaises(ValueError):
            batch_evidence.manifest(source)


if __name__ == "__main__":
    unittest.main()

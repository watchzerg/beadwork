"""真实 Git worktree 同步；只读 Beads 与 just 采用外部命令 fixture。"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

import evidence
import execution_plan
import main_sync

SCRIPT = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts/beadwork.py"

pytestmark = pytest.mark.workflow


class MainSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.primary = self.root / "repo"
        self.primary.mkdir()
        self.env = dict(
            os.environ,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_NAME="Test",
            GIT_AUTHOR_EMAIL="test@example.com",
            GIT_COMMITTER_NAME="Test",
            GIT_COMMITTER_EMAIL="test@example.com",
        )
        self.git(self.primary, "init", "-b", "main")
        (self.primary / ".gitignore").write_text(".worktrees/\n")
        (self.primary / "code").write_text("base\n")
        self.commit(self.primary, "base")
        self.wt = self.primary / ".worktrees" / "demo-1"
        self.git(self.primary, "worktree", "add", "-b", "implement/demo-1", str(self.wt))
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.env.update(PATH=str(self.bin) + os.pathsep + self.env["PATH"], FIXTURE=str(self.root))
        (self.root / "status").write_text("open")
        plan = {"ticket_order": ["demo-1.1"]}
        (self.root / "parent-description").write_text(execution_plan.replace("", plan))
        approved = self.root / "approved-plan.json"
        evidence.write(approved, plan)
        execution_plan.adopt(
            self.primary,
            "demo-1",
            plan,
            [{"id": "demo-1.1", "status": "open"}],
            [evidence.binding(approved)],
            "测试批准",
        )
        self.executable(
            "bd",
            """import json,os,sys
from pathlib import Path
p=Path(os.environ['FIXTURE']); a=sys.argv[1:]
assert '--readonly' in a and '--json' in a
child={'id':'demo-1.1','status':(p/'status').read_text(),'labels':['ready-for-agent']}
if a[0]=='show': print(json.dumps([{'id':'demo-1','status':'in_progress','description':(p/'parent-description').read_text()}]))
elif a[0] in ('list','ready'): print(json.dumps([child]))
elif a[0]=='dep': print('[]')
else: raise AssertionError(a)
""",
        )
        self.executable(
            "just",
            """import os,sys,subprocess,signal
from pathlib import Path
p=Path(os.environ['FIXTURE']); a=sys.argv[1:]
if a==['--summary']:
 print('check-toolchain install typecheck test gate-plan gate-core gate-full env-facts fmt gate-browser');sys.exit(0)
assert a[:2]==['--one','--']
with (p/'commands').open('a') as f: f.write(' '.join(a[2:])+'\\n')
if a[2]=='gate-plan': print('{"core":"gate-core","full":["gate-core","gate-browser"],"defer_to_final":[]}')
if a[2]=='gate-plan': print('计划诊断，不属于 JSON 输出',file=sys.stderr)
if (p/'signal').exists(): os.kill(os.getppid(),signal.SIGTERM); __import__('time').sleep(5)
if (p/'fail').exists() and a[2]=='gate-core': sys.exit(1)
""",
        )
        self.data = {
            "repository_root": str(self.primary),
            "parent_id": "demo-1",
            "expected_children": ["demo-1.1"],
            "required_boundary_gates": ["gate-browser", "gate-browser"],
            "install_inputs": ["package.json", "bun.lock", "mise.toml", "mise.lock"],
        }

    def executable(self, name, body):
        p = self.bin / name
        p.write_text("#!" + sys.executable + "\n" + body)
        p.chmod(0o755)

    def git(self, wt, *args):
        p = subprocess.run(
            ["git", "-C", str(wt), *args], env=self.env, capture_output=True, text=True
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def commit(self, wt, message):
        self.git(wt, "add", ".")
        self.git(wt, "commit", "-m", message)
        return self.git(wt, "rev-parse", "HEAD")

    def change(self, wt, name="other", value="change\n"):
        (wt / name).write_text(value)
        return self.commit(wt, "change")

    def sync(self, ok=True, final=False):
        p = self.root / "input.json"
        p.write_text(json.dumps(self.data))
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "controller",
                "sync-final" if final else "sync-main",
                "--input",
                str(p),
            ],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout) if ok else result.stderr

    def commands(self):
        p = self.root / "commands"
        return p.read_text().splitlines() if p.exists() else []

    def test_plan_stdout_is_separate_and_bound_during_ready_validation(self):
        result = self.sync()
        entry = result["commands"][0]
        source = evidence.read(evidence.bound(entry))["stdout"]
        stdout = evidence.bound(source)
        self.assertEqual(json.loads(stdout.read_text()), result["gate_plan"])
        self.assertIn("计划诊断", stdout.with_name("output.log").read_text())
        dispatch = {
            **self.data,
            "worktree": str(self.wt),
            "branch": "implement/demo-1",
            "ticket_id": "demo-1.1",
        }
        with patch.dict(os.environ, self.env):
            main_sync.check_result(dispatch, result["sync_result"])
            stdout.write_text("{}")
            with self.assertRaisesRegex(ValueError, "证据文件已变化"):
                main_sync.check_result(dispatch, result["sync_result"])

    def final_input(self, name="package.json"):
        (self.root / "status").write_text("closed")
        target = self.change(self.primary, name)
        self.data["reviewed_main"] = target
        self.data.pop("required_boundary_gates")
        return target

    def test_final_sync_installs_changed_inputs_without_running_gates(self):
        target = self.final_input()
        result = self.sync(final=True)
        self.assertEqual(result["target_main"], target)
        self.assertEqual(self.git(self.wt, "rev-parse", "HEAD"), target)
        self.assertEqual(self.commands(), ["install", "env-facts"])
        self.assertEqual(result["frontier"], {"next": "done"})
        self.assertIn("/final-sync/", result["sync_result"])
        self.sync(final=True)
        self.assertEqual(self.commands(), ["install", "env-facts"])

    def test_final_sync_skips_install_for_code_only_and_rejects_open_children(self):
        self.final_input("code")
        (self.root / "status").write_text("open")
        self.sync(final=True, ok=False)
        self.assertEqual(self.commands(), [])
        (self.root / "status").write_text("closed")
        self.sync(final=True)
        self.assertEqual(self.commands(), ["env-facts"])

    def test_final_install_failure_resumes_original_target_after_merge(self):
        target = self.final_input()
        original = (self.bin / "just").read_text()
        with (self.bin / "just").open("a") as stream:
            stream.write("\nif (p/'fail-install').exists() and a[2]=='install': sys.exit(1)\n")
        (self.root / "fail-install").touch()
        self.sync(final=True, ok=False)
        self.assertEqual(self.git(self.wt, "rev-parse", "HEAD"), target)
        folder = next((self.primary / ".worktrees/.evidence/demo-1/final-sync").iterdir())
        self.assertFalse((folder / "ready.json").exists())
        intent = (folder / "intent.json").read_bytes()
        self.change(self.primary, "later")
        (self.bin / "just").write_text(original)
        result = self.sync(final=True)
        self.assertEqual(result["target_main"], target)
        self.assertEqual(result["head"], target)
        self.assertEqual((folder / "intent.json").read_bytes(), intent)
        self.assertEqual(self.commands(), ["install", "install", "env-facts"])

    def test_final_sync_interruption_preserves_target_and_requires_original_input(self):
        target = self.final_input()
        (self.root / "signal").touch()
        self.sync(final=True, ok=False)
        (self.root / "signal").unlink()
        newer = self.change(self.primary, "later")
        self.data["reviewed_main"] = newer
        self.assertIn("原 reviewed_main", self.sync(final=True, ok=False))
        self.data["reviewed_main"] = target
        result = self.sync(final=True)
        self.assertEqual(result["head"], target)
        self.assertEqual(self.commands(), ["install", "install", "env-facts"])

    def test_final_prepare_checks_sync_head_and_install_evidence(self):
        self.final_input()
        synced = self.sync(final=True)
        data = dict(
            self.data,
            rules_paths=[],
            linked_spec="demo-1",
            ticket_evidence=[],
            required_boundary_gates=[],
            prior_finalization=None,
            final_sync_result=synced["sync_result"],
        )
        source = self.root / "final-input.json"
        source.write_text(json.dumps(data))

        def prepare(ok=True):
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(SCRIPT),
                    "controller",
                    "prepare",
                    "finalizer",
                    "--input",
                    str(source),
                ],
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
            return json.loads(result.stdout) if ok else result.stderr

        prepared = prepare()
        dispatch = evidence.read(prepared["dispatch_path"])
        self.assertIn(evidence.binding(synced["sync_result"]), dispatch["environment_evidence"])
        log = Path(synced["commands"][0]["path"]).parent / "output.log"
        original = log.read_bytes()
        log.write_bytes(b"changed")
        self.assertIn("同步日志已变化", prepare(ok=False))
        log.write_bytes(original)
        self.change(self.wt, "unexpected")
        self.assertIn("同步验证 HEAD 已变化", prepare(ok=False))

    def prepare_input(self, data):
        """同步测试仍通过真实 prepare/accept 交接准入计划。"""
        import test_verify_phase

        request = self.root / "preflight-input.json"
        request.write_text(
            json.dumps(dict(repository_root=str(self.primary), parent_id="demo-1", rules_paths=[]))
        )

        def call(*args):
            result = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), "controller", *map(str, args)],
                env=self.env,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)

        d = call("prepare", "preflight", "--input", request)
        folder = Path(d["dispatch_path"]).parent
        r = test_verify_phase.PhaseValidatorTests().preflight()
        plan = test_verify_phase.PhaseValidatorTests().plan("direct_verification")
        r.update(
            parent={"id": "demo-1", "status": "open"},
            expected_children=["demo-1.1"],
            execution_plan={"ticket_order": ["demo-1.1"]},
            tickets=[{"id": "demo-1.1", "status": "open", "test_plan": plan}],
            boundary_gates=["gate-browser"],
            linked_spec="demo-1",
            workspace={
                "primary_worktree": str(self.primary),
                "implementation_worktree": str(self.wt),
                "branch": "implement/demo-1",
                "observed_head": self.git(self.wt, "rev-parse", "HEAD"),
                "clean": True,
            },
        )
        gate_plan_path = folder / "gate-plan.json"
        evidence.write(gate_plan_path, r["gate_plan"])
        r["gate_plan_source"] = evidence.binding(gate_plan_path)
        report = folder / "report.json"
        report.write_text(json.dumps(r))
        receipt = folder / "receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "status": "READY",
                    "report_path": str(report),
                    "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
                }
            )
        )
        accepted = folder / "accepted.json"
        call(
            "accept",
            "--dispatch",
            d["dispatch_path"],
            "--report",
            report,
            "--receipt",
            receipt,
            "--output",
            accepted,
        )
        return dict(
            data,
            linked_spec="demo-1",
            preflight_acceptance={
                "path": str(accepted),
                "sha256": hashlib.sha256(accepted.read_bytes()).hexdigest(),
            },
        )

    def test_plan_changed_during_sync_cannot_start_next_ticket(self):
        self.change(self.primary)
        self.executable(
            "just",
            """import os,sys
from pathlib import Path
p=Path(os.environ['FIXTURE'])
if sys.argv[1:]==['--summary']:
 print('check-toolchain install typecheck test gate-plan gate-core gate-full env-facts fmt gate-browser');sys.exit(0)
with (p/'commands').open('a') as f: f.write(' '.join(sys.argv[3:])+'\\n')
if sys.argv[-1]=='gate-plan': print('{"core":"gate-core","full":["gate-core","gate-browser"],"defer_to_final":[]}')
if sys.argv[-1]=='gate-core': (p/'parent-description').write_text('计划被删除')
""",
        )
        result = self.sync()
        self.assertEqual(result["frontier"]["next"], "blocked")
        data = dict(
            self.data,
            ticket_id="demo-1.1",
            mode="new",
            test_mode="direct_verification",
            approved_seams=[],
            rules_paths=[],
            testing_seams_doc="/rules/seams.md",
            sync_result=result["sync_result"],
            linked_spec="demo-1",
        )
        source = self.root / "blocked-prepare.json"
        source.write_text(json.dumps(data))
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "controller",
                "prepare",
                "executor",
                "--input",
                str(source),
            ],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("execution-plan", proc.stderr)

    def test_no_change_skips_commands_and_preserves_main(self):
        head = self.git(self.primary, "rev-parse", "HEAD")
        r = self.sync()
        self.assertFalse(r["changed"])
        self.assertEqual(self.commands(), ["gate-plan"])
        self.assertEqual(r["head"], head)
        self.assertEqual(r["frontier"]["next"], "claim")

    def test_fast_forward_and_new_base(self):
        target = self.change(self.primary)
        r = self.sync()
        self.assertEqual(r["head"], target)
        self.assertEqual(self.commands(), ["env-facts", "gate-plan", "gate-core"])
        self.assertEqual(self.git(self.primary, "rev-parse", "HEAD"), target)
        self.assertFalse(self.sync()["changed"])
        self.assertEqual(len(self.commands()), 4)

    def test_diverged_merge_preserves_both_histories(self):
        previous = self.change(self.wt, "ticket")
        target = self.change(self.primary)
        r = self.sync()
        self.assertEqual(
            self.git(self.wt, "rev-list", "--parents", "-n", "1", r["head"]).split()[1:],
            [previous, target],
        )

    def test_conflict_is_preserved_without_smoke(self):
        self.change(self.wt, "code", "ticket\n")
        self.change(self.primary, "code", "main\n")
        self.sync(ok=False)
        self.assertTrue(self.git(self.wt, "diff", "--name-only", "--diff-filter=U"))
        self.assertEqual(self.commands(), [])
        self.sync(ok=False)
        (self.wt / "code").write_text("resolved\n")
        self.commit(self.wt, "resolve")
        self.sync()
        self.assertEqual(len(self.commands()), 3)

    def test_implementation_dirty_rejected(self):
        for wt in (self.wt,):
            p = wt / "dirty"
            p.write_text("keep")
            self.sync(ok=False)
            self.assertEqual(p.read_text(), "keep")
            p.unlink()
        self.assertEqual(self.commands(), [])

    def test_resume_ticket_never_merges(self):
        self.change(self.primary)
        before = self.git(self.wt, "rev-parse", "HEAD")
        (self.root / "status").write_text("in_progress")
        self.sync(ok=False)
        self.assertEqual(before, self.git(self.wt, "rev-parse", "HEAD"))

    def test_install_inputs_trigger_install(self):
        self.change(self.primary, "bun.lock")
        self.sync()
        self.assertEqual(self.commands(), ["install", "env-facts", "gate-plan", "gate-core"])

    def test_failed_smoke_is_retried_even_if_main_already_merged(self):
        self.change(self.primary)
        (self.root / "fail").touch()
        self.sync(ok=False)
        (self.root / "fail").unlink()
        self.sync()
        self.assertEqual(self.commands(), ["env-facts", "gate-plan", "gate-core"] * 2)

    def test_pending_sync_keeps_target_when_main_moves(self):
        target = self.change(self.primary)
        (self.root / "fail").touch()
        self.sync(ok=False)
        newer = self.change(self.primary, "later")
        (self.root / "fail").unlink()
        r = self.sync()
        self.assertEqual(r["target_main"], target)
        self.assertEqual(r["head"], target)
        self.assertEqual(self.git(self.primary, "rev-parse", "HEAD"), newer)
        self.assertEqual(self.sync()["target_main"], newer)

    def test_missing_ready_after_merge_revalidates(self):
        self.change(self.primary)
        r = self.sync()
        Path(r["sync_result"]).unlink()  # 模拟命令完成、ready 写入前中断。
        self.sync()
        self.assertEqual(len(self.commands()), 6)

    def test_signal_interruption_preserves_pending_and_retries(self):
        self.change(self.primary)
        (self.root / "signal").touch()
        self.sync(ok=False)
        (self.root / "signal").unlink()
        self.sync()
        self.assertEqual(self.commands(), ["env-facts", "env-facts", "gate-plan", "gate-core"])

    def test_pending_sync_rejects_old_ready_even_at_same_head(self):
        r = self.sync()
        directory = Path(r["sync_result"]).parent.parent / "interrupted"
        directory.mkdir()
        (directory / "intent.json").write_text("{}")
        data = dict(
            self.data,
            ticket_id="demo-1.1",
            mode="new",
            test_mode="direct_verification",
            approved_seams=[],
            rules_paths=[],
            testing_seams_doc="/rules/seams.md",
            sync_result=r["sync_result"],
        )
        p = self.root / "prepare.json"
        p.write_text(json.dumps(self.prepare_input(data)))
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "controller",
                "prepare",
                "executor",
                "--input",
                str(p),
            ],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("未完成同步", result.stderr)

    def test_main_moves_during_validation_without_chasing(self):
        target = self.change(self.primary)
        self.executable(
            "just",
            """import os,subprocess,sys
from pathlib import Path
p=Path(os.environ['FIXTURE'])/'repo'
if sys.argv[1:]==['--summary']:
 print('check-toolchain install typecheck test gate-plan gate-core gate-full env-facts fmt gate-browser');sys.exit(0)
with (Path(os.environ['FIXTURE'])/'commands').open('a') as f: f.write(' '.join(sys.argv[3:])+'\\n')
if sys.argv[-1]=='gate-plan': print('{"core":"gate-core","full":["gate-core","gate-browser"],"defer_to_final":[]}')
if sys.argv[3]=='env-facts':
    (p/'later').write_text('later')
    subprocess.run(['git','-C',str(p),'add','later'],check=True)
    subprocess.run(['git','-C',str(p),'commit','-m','later'],check=True)
""",
        )
        r = self.sync()
        self.assertEqual(r["target_main"], target)
        self.assertEqual(r["head"], target)
        self.assertNotEqual(self.git(self.primary, "rev-parse", "HEAD"), target)
        data = dict(
            self.data,
            ticket_id="demo-1.1",
            mode="new",
            test_mode="direct_verification",
            approved_seams=[],
            rules_paths=[],
            testing_seams_doc="/rules/seams.md",
            sync_result=r["sync_result"],
        )
        source = self.root / "prepare.json"
        source.write_text(json.dumps(self.prepare_input(data)))
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "controller",
                "prepare",
                "executor",
                "--input",
                str(source),
            ],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["base_commit"], target)

    def test_ready_rejects_missing_or_tampered_validation(self):
        self.change(self.primary)
        r = self.sync()
        ready = Path(r["sync_result"])
        original = ready.read_text()
        data = dict(
            self.data,
            ticket_id="demo-1.1",
            mode="new",
            test_mode="direct_verification",
            approved_seams=[],
            rules_paths=[],
            testing_seams_doc="/rules/seams.md",
            sync_result=str(ready),
        )
        p = self.root / "prepare.json"
        p.write_text(json.dumps(self.prepare_input(data)))
        args = [
            sys.executable,
            "-B",
            str(SCRIPT),
            "controller",
            "prepare",
            "executor",
            "--input",
            str(p),
        ]
        bad = json.loads(original)
        bad["commands"] = []
        ready.write_text(json.dumps(bad))
        result = subprocess.run(args, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("命令不完整", result.stderr)
        ready.write_text(original)
        log = Path(r["commands"][0]["path"]).parent / "output.log"
        log.write_text("tampered")
        result = subprocess.run(args, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("日志已变化", result.stderr)

    def test_prepare_new_requires_current_sync_evidence(self):
        r = self.sync()
        data = dict(
            self.data,
            ticket_id="demo-1.1",
            mode="new",
            test_mode="direct_verification",
            approved_seams=[],
            rules_paths=[],
            testing_seams_doc="/rules/seams.md",
            sync_result=r["sync_result"],
        )
        p = self.root / "prepare.json"
        p.write_text(json.dumps(self.prepare_input(data)))
        args = [
            sys.executable,
            "-B",
            str(SCRIPT),
            "controller",
            "prepare",
            "executor",
            "--input",
            str(p),
        ]
        result = subprocess.run(args, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        dispatch = json.loads(Path(json.loads(result.stdout)["dispatch_path"]).read_text())
        self.assertEqual(dispatch["base_commit"], r["head"])
        self.assertEqual(dispatch["ticket_scope"], "root")
        self.assertNotIn("stage", dispatch)
        facts = self.root / "stage-facts.json"
        facts.write_text("{}")
        stage = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "executor",
                "ticket-stage",
                "--dispatch",
                dispatch["dispatch_path"],
                "--input",
                str(facts),
            ],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(stage.returncode, 0, stage.stderr)
        self.assertEqual(json.loads(stage.stdout)["stage"], 0)
        self.change(self.wt, "ticket")
        result = subprocess.run(args, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD", result.stderr)

    def test_prepare_requires_verified_plan_and_explicit_inputs(self):
        r = self.sync()
        original = self.prepare_input(
            dict(
                self.data,
                ticket_id="demo-1.1",
                mode="new",
                test_mode="direct_verification",
                approved_seams=[],
                rules_paths=[],
                testing_seams_doc="/rules/seams.md",
                sync_result=r["sync_result"],
            )
        )
        for field in ("linked_spec", "required_boundary_gates", "preflight_acceptance"):
            with self.subTest(field=field):
                data = dict(original)
                del data[field]
                path = self.root / "missing-input.json"
                path.write_text(json.dumps(data))
                result = subprocess.run(
                    [
                        sys.executable,
                        "-B",
                        str(SCRIPT),
                        "controller",
                        "prepare",
                        "executor",
                        "--input",
                        str(path),
                    ],
                    env=self.env,
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
        accepted = Path(original["preflight_acceptance"]["path"])
        accepted.write_text("{}")
        path = self.root / "tampered-input.json"
        path.write_text(json.dumps(original))
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "controller",
                "prepare",
                "executor",
                "--input",
                str(path),
            ],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("证据文件已变化", result.stderr)

    def test_dirty_primary_sync_and_new_prepare_preserve_manual_edits(self):
        target = self.change(self.primary)
        (self.primary / "code").write_text("staged")
        self.git(self.primary, "add", "code")
        (self.primary / "code").write_text("unstaged")
        (self.primary / "manual").write_text("untracked")
        before = self.git(self.primary, "status", "--porcelain=v1")
        result = self.sync()
        self.assertEqual(result["target_main"], target)
        data = dict(
            self.data,
            ticket_id="demo-1.1",
            mode="new",
            test_mode="direct_verification",
            approved_seams=[],
            rules_paths=[],
            testing_seams_doc="/rules/seams.md",
            sync_result=result["sync_result"],
        )
        source = self.root / "prepare.json"
        source.write_text(json.dumps(self.prepare_input(data)))
        proc = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "controller",
                "prepare",
                "executor",
                "--input",
                str(source),
            ],
            env=self.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["base_commit"], target)
        self.assertEqual(self.git(self.primary, "status", "--porcelain=v1"), before)
        self.assertEqual((self.primary / "code").read_text(), "unstaged")

    def test_primary_unfinished_git_operation_blocks_sync(self):
        marker = self.primary / ".git" / "CHERRY_PICK_HEAD"
        marker.write_text(self.git(self.primary, "rev-parse", "HEAD"))
        self.assertIn("未完成 Git 操作", self.sync(ok=False))


if __name__ == "__main__":
    unittest.main()

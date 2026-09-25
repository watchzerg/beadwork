"""真实 Git worktree 同步；只读 Beads 与 just 采用外部命令 fixture。"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

import evidence
import execution_plan

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
            "import os,sys,subprocess,signal\nfrom pathlib import Path\np=Path(os.environ['FIXTURE']); a=sys.argv[1:]\nif a==['--summary']:\n print('install test gate-core gate-full');sys.exit(0)\nassert a[:2]==['--one','--']\nwith (p/'commands').open('a') as f: f.write(' '.join(a[2:])+'\\n')\nif (p/'signal').exists(): os.kill(os.getppid(),signal.SIGTERM); __import__('time').sleep(5)\nif (p/'fail').exists() and a[2]=='gate-core': sys.exit(1)\n",
        )
        self.data = {
            "repository_root": str(self.primary),
            "parent_id": "demo-1",
            "expected_children": ["demo-1.1"],
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

    def final_input(self, name="package.json"):
        (self.root / "status").write_text("closed")
        target = self.change(self.primary, name)
        self.data["reviewed_main"] = target
        return target

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
            linked_spec="demo-1",
            workspace={
                "primary_worktree": str(self.primary),
                "implementation_worktree": str(self.wt),
                "branch": "implement/demo-1",
                "observed_head": self.git(self.wt, "rev-parse", "HEAD"),
                "clean": True,
            },
        )
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

    def test_diverged_merge_preserves_both_histories(self):
        previous = self.change(self.wt, "ticket")
        target = self.change(self.primary)
        r = self.sync()
        self.assertEqual(
            self.git(self.wt, "rev-list", "--parents", "-n", "1", r["head"]).split()[1:],
            [previous, target],
        )


if __name__ == "__main__":
    unittest.main()

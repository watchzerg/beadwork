"""在真实临时 worktree 中验证采集、取消和报告汇总。"""

import copy
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import pytest

import test_controller as fixture

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts"
SCRIPT = SCRIPTS / "beadwork.py"
ASSEMBLE = SCRIPT
REAL_JUST = shutil.which("just")

pytestmark = pytest.mark.integration


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.prepare()
        self.dispatch = self.h.dispatch
        self.fake = self.h.root / "bin" / "just"
        self.fake.write_text(
            "#!"
            + sys.executable
            + "\n"
            + "import json, os, signal, sys, time\nfrom pathlib import Path\nif sys.argv[1:] == ['--summary']:\n    if os.environ.get('TEST_MODE') == 'spawnfail': Path(sys.argv[0]).unlink()\n    print('install test gate-core gate-full'); sys.exit(0)\nassert sys.argv[1:3] == ['--one', '--']\nmode = os.environ.get('TEST_MODE', 'pass')\nprint(json.dumps({'argv': sys.argv[3:], 'cwd': os.getcwd()}), flush=True)\nif mode == 'fail': print('目标断言失败'); sys.exit(7)\nif mode == 'large': os.write(1, b'x' * 200000 + b'\\xffEND'); sys.exit(0)\nif mode == 'change': Path('new-file').write_text('changed'); sys.exit(0)\nif mode == 'hang':\n    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n    print('READY', flush=True)\n    while True: time.sleep(.1)\n"
        )
        self.fake.chmod(0o755)
        self.serial = 0

    def command(self, recipe="test", *parameters):
        return [
            sys.executable,
            "-B",
            str(SCRIPT),
            "run-verification",
            "--dispatch",
            str(self.dispatch),
            "--recipe",
            recipe,
            "--",
            *parameters,
        ]

    def run_record(self, mode="pass", recipe="test", parameters=(), expected=0):
        result = subprocess.run(
            self.command(recipe, *parameters),
            cwd=self.h.root,
            env={**self.h.env, "TEST_MODE": mode},
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assemble(self, status="BLOCKED", notes=None, priors=(), expected=0):
        self.serial += 1
        draft = copy.deepcopy(self.h.h.report)
        for key in (
            "base_commit",
            "head_commit",
            "implementation_commits",
            "review",
            "delivery_kind",
        ):
            del draft[key]
        draft.update(
            status=status,
            outcome="interrupted",
            test_plan=None,
            verification=[],
            acceptance=[],
            blockers=["测试部分报告"],
        )
        if notes is not None:
            draft["verification_notes"] = notes
        path = self.dispatch.parent / f"draft-run-{self.serial}.json"
        output = self.dispatch.parent / f"report-run-{self.serial}.json"
        self.h.put(path, draft)
        command = [
            sys.executable,
            "-B",
            str(ASSEMBLE),
            "executor",
            "assemble",
            "--dispatch",
            str(self.dispatch),
            "--draft",
            str(path),
            "--output",
            str(output),
        ]
        for prior in priors:
            command.extend(("--verification-dispatch", str(prior)))
        result = subprocess.run(
            command, cwd=self.h.root, env=self.h.env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(output.read_text()) if expected == 0 else result

    @unittest.skipUnless(REAL_JUST, "需要安装 just 以验证真实入口")
    def test_gate_full_is_unfiltered_and_records_one_complete_run(self):
        self.fake.unlink()
        (self.h.wt / "justfile").write_text("gate-full:\n    @echo FULL\n")
        green = self.run_record(recipe="gate-full")
        self.assertEqual(green["log_tail"].splitlines(), ["FULL"])
        rejected = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPT),
                "run-verification",
                "--dispatch",
                str(self.dispatch),
                "--recipe",
                "gate-full",
                "--",
                "gate-core",
            ],
            env=self.h.env,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("不接受筛选参数", rejected.stderr)
        for run in (green,):
            directory = Path(run["run_path"])
            self.assertTrue((directory / "started.json").exists())
            result = json.loads((directory / "result.json").read_text())
            self.assertEqual(result["outcome"], "exited")
            self.assertTrue(result["process_group_gone"])
        report = self.assemble()
        self.assertEqual(len(report["verification"]), 1)
        self.assertIn("gate-full", report["verification"][0]["command"])


if __name__ == "__main__":
    unittest.main()

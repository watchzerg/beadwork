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
            + "import json, os, signal, sys, time\nfrom pathlib import Path\nif sys.argv[1:] == ['--summary']:\n    if os.environ.get('TEST_MODE') == 'spawnfail': Path(sys.argv[0]).unlink()\n    print('install test gate-core gate-full'); sys.exit(0)\nassert sys.argv[1:3] == ['--one', '--']\nmode = os.environ.get('TEST_MODE', 'pass')\nprint(json.dumps({'argv': sys.argv[3:], 'cwd': os.getcwd()}), flush=True)\nif mode == 'fail': print('目标断言失败'); sys.exit(7)\nif mode == 'large': os.write(1, b'x' * (3 * 1024 * 1024) + b'\\xffEND'); sys.exit(0)\nif mode == 'change': Path('new-file').write_text('changed'); sys.exit(0)\nif mode == 'hang':\n    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n    print('READY', flush=True)\n    while True: time.sleep(.1)\n"
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

    def test_large_log_summary_and_bound_result_expose_truncation(self):
        import evidence

        summary = self.run_record(mode="large")
        directory = Path(summary["run_path"])
        result = json.loads((directory / "result.json").read_text())
        log = directory / "output.log"
        self.assertTrue(summary["log_truncated"])
        self.assertEqual(summary["output_bytes"], result["output_bytes"])
        self.assertTrue(result["log_truncated"])
        self.assertEqual(result["outcome"], "exited")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["log_bytes"], log.stat().st_size)
        self.assertLess(result["log_bytes"], 2 * 1024 * 1024 + 100)
        self.assertEqual(result["log_sha256"], evidence.digest(log))
        self.assertTrue(summary["log_tail"].endswith("\ufffdEND"))

    def test_unsupported_recipe_explains_test_route_without_starting_verification(self):
        invoked = self.h.root / "just-invoked"
        self.fake.write_text(
            f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(invoked)!r}).touch()\n"
        )
        before = set(self.dispatch.parent.glob("verification-*"))
        result = subprocess.run(
            self.command("gate-database"),
            cwd=self.h.root,
            env=self.h.env,
            capture_output=True,
            text=True,
            timeout=15,
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr)
        self.assertEqual(error["outcome"], "recorder_error")
        self.assertIn("--recipe test -- <项目参数>", error["error"])
        self.assertIn("确认覆盖等价", error["error"])
        self.assertIn("不得省略原命令的准备步骤或检查", error["error"])
        self.assertFalse(invoked.exists())
        self.assertEqual(set(self.dispatch.parent.glob("verification-*")), before)

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

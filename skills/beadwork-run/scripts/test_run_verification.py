"""在真实临时 worktree 中验证采集、取消和报告汇总。"""
import copy
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import unittest

import test_controller as fixture
import test_executor_operations as executor_fixture

SCRIPT = Path(__file__).with_name("run-verification.py")
ASSEMBLE = Path(__file__).with_name("executor-operations.py")
REAL_JUST = shutil.which("just")


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.h = fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.prepare()
        self.dispatch = self.h.dispatch
        self.fake = self.h.root / "bin" / "just"
        self.fake.write_text("#!" + sys.executable + "\n" + '''import json, os, signal, sys, time
from pathlib import Path
if sys.argv[1:] == ['--summary']:
    if os.environ.get('TEST_MODE') == 'spawnfail': Path(sys.argv[0]).unlink()
    print('test typecheck gate-unit gate-demo'); sys.exit(0)
assert sys.argv[1:3] == ['--one', '--']
mode = os.environ.get('TEST_MODE', 'pass')
print(json.dumps({'argv': sys.argv[3:], 'cwd': os.getcwd()}), flush=True)
if mode == 'fail': print('目标断言失败'); sys.exit(7)
if mode == 'large': os.write(1, b'x' * 200000 + b'\\xffEND'); sys.exit(0)
if mode == 'change': Path('new-file').write_text('changed'); sys.exit(0)
if mode == 'hang':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print('READY', flush=True)
    while True: time.sleep(.1)
''')
        self.fake.chmod(0o755)
        self.serial = 0

    def command(self, recipe="test", *parameters):
        return [sys.executable, "-B", str(SCRIPT), "--dispatch", str(self.dispatch),
                "--recipe", recipe, "--", *parameters]

    def run_record(self, mode="pass", recipe="test", parameters=(), expected=0):
        result = subprocess.run(self.command(recipe, *parameters), cwd=self.h.root,
            env={**self.h.env, "TEST_MODE": mode}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def assemble(self, status="BLOCKED", notes=None, priors=(), expected=0):
        self.serial += 1
        draft = copy.deepcopy(self.h.h.report)
        for key in ("base_commit", "head_commit", "implementation_commits", "review"):
            del draft[key]
        draft.update(status=status, outcome="interrupted", test_plan=None, verification=[], acceptance=[], blockers=["测试部分报告"])
        if notes is not None:
            draft["verification_notes"] = notes
        path = self.dispatch.parent / f"draft-run-{self.serial}.json"
        output = self.dispatch.parent / f"report-run-{self.serial}.json"
        self.h.put(path, draft)
        command = [sys.executable, "-B", str(ASSEMBLE), "assemble", "--dispatch", str(self.dispatch),
                   "--draft", str(path), "--output", str(output)]
        for prior in priors:
            command.extend(("--verification-dispatch", str(prior)))
        result = subprocess.run(command, cwd=self.h.root, env=self.h.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(output.read_text()) if expected == 0 else result

    def test_arguments_cwd_dirty_state_and_bounded_raw_log(self):
        parameters = ["a space.ts", "$(touch BAD)", "`touch BAD2`", "-t", "名称"]
        run = self.run_record(parameters=parameters)
        log = Path(run["log_path"])
        actual = json.loads(log.read_text())
        self.assertEqual(actual, {"argv": ["test", *parameters], "cwd": str(self.h.wt.resolve())})
        self.assertFalse((self.h.wt / "BAD").exists())
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        (self.h.wt / "new-test").write_text("test")
        large = self.run_record("large")
        self.assertTrue(large["dirty"])
        self.assertGreater(Path(large["log_path"]).stat().st_size, 200000)
        self.assertLessEqual(len(large["log_tail"]), 2048)
        self.assertTrue(Path(large["log_path"]).read_bytes().endswith(b"\xffEND"))

    def test_failed_red_and_retry_auto_collect_with_note(self):
        red = self.run_record("fail", expected=1)
        green = self.run_record()
        report = self.assemble(notes={red["run_path"]: "目标断言失败，构成 S1 red"})
        self.assertEqual(len(report["verification"]), 2)
        first, second = report["verification"]
        self.assertIn("exit_code=7", first["result"])
        self.assertIn("S1 red", first["result"])
        self.assertIn("exit_code=0", second["result"])
        self.assertIn(green["run_path"], second["result"])

    def test_changed_state_is_not_success(self):
        run = self.run_record("change", expected=2)
        self.assertEqual(run["outcome"], "state_changed")
        self.assertEqual(run["exit_code"], 0)

    def test_reject_mutating_and_missing_recipes(self):
        for recipe in ("fmt", "install", "gate-absent"):
            result = subprocess.run(self.command(recipe), env=self.h.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
        self.assertEqual(list(self.dispatch.parent.glob("verification-*")), [])

    def test_tampered_log_and_unknown_note_rejected(self):
        run = self.run_record()
        self.assemble(notes={"/unknown": "说明"}, expected=1)
        Path(run["log_path"]).write_text("改写")
        self.assemble(expected=1)

    def test_spawn_failure_has_a_record_and_is_not_red(self):
        run = self.run_record("spawnfail", expected=2)
        self.assertEqual(run["outcome"], "recorder_error")
        self.assertIsNone(run["exit_code"])
        self.assertIn("recorder_error", self.assemble()["verification"][0]["result"])

    def test_done_report_includes_automatic_evidence_and_controller_accepts(self):
        e = executor_fixture.ExecutorOperationsTests()
        e.setUp()
        self.addCleanup(e.doCleanups)
        (e.h.root / "bin" / "just").write_bytes(self.fake.read_bytes())
        (e.h.root / "bin" / "just").chmod(0o755)
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--dispatch", str(e.dispatch),
                                 "--recipe", "gate-unit"], env=e.h.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        run = json.loads(result.stdout)
        collection = e.collect(e.round())
        receipt, report_path = e.assemble([collection])
        report = json.loads(report_path.read_text())
        self.assertIn(run["run_path"], report["verification"][0]["result"])
        e.h.report = report_path
        e.h.receipt = report_path.parent / "receipt.json"
        e.h.put(e.h.receipt, receipt)
        e.h.accept()

    @unittest.skipUnless(REAL_JUST, "需要安装 just 以验证真实入口")
    def test_real_just_rejects_extra_recipe_before_execution(self):
        self.fake.unlink()
        (self.h.wt / "justfile").write_text(
            'gate-unit:\n    @echo UNEXPECTED_GATE\nfmt:\n    @echo UNREQUESTED_FMT\n')
        run = self.run_record(recipe="gate-unit", parameters=("fmt",), expected=1)
        self.assertEqual(run["outcome"], "exited")
        self.assertNotEqual(run["exit_code"], 0)
        self.assertNotIn("UNEXPECTED_GATE", run["log_tail"])
        self.assertNotIn("UNREQUESTED_FMT", run["log_tail"])
        self.assertIn("expected 1 command-line recipe invocation", run["log_tail"])

    @unittest.skipUnless(REAL_JUST, "需要安装 just 以验证真实入口")
    def test_real_just_retains_recipe_dependencies(self):
        self.fake.unlink()
        (self.h.wt / "justfile").write_text(
            'gate-unit: dependency\n    @echo GATE\ndependency:\n    @echo DEPENDENCY\n')
        run = self.run_record(recipe="gate-unit")
        self.assertEqual(run["log_tail"].splitlines(), ["DEPENDENCY", "GATE"])

    @unittest.skipUnless(REAL_JUST, "需要安装 just 以验证真实入口")
    def test_real_just_variadic_arguments_can_match_recipe_names(self):
        self.fake.unlink()
        (self.h.wt / "justfile").write_text(
            'test *ARGS:\n    @echo {{ARGS}}\nfmt:\n    @echo UNREQUESTED_FMT\n')
        run = self.run_record(parameters=("sample", "fmt"))
        self.assertEqual(run["log_tail"], "sample fmt")

    def test_explicit_resume_retains_history_and_rejects_other_ticket(self):
        old = self.dispatch
        self.run_record("fail", expected=1)
        self.h.prepare()
        self.dispatch = self.h.dispatch
        self.run_record()
        self.assertEqual(len(self.assemble()["verification"]), 1)
        self.assertEqual(len(self.assemble(priors=[old])["verification"]), 2)
        self.h.prepare(ticket_id="another")
        self.dispatch = self.h.dispatch
        self.assemble(priors=[old], expected=1)

    def start_hanging(self):
        process = subprocess.Popen(self.command(), env={**self.h.env, "TEST_MODE": "hang"},
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            for directory in self.dispatch.parent.glob("verification-*"):
                log = directory / "output.log"
                if log.exists() and "READY" in log.read_text():
                    return process, directory
            time.sleep(.02)
        self.fail("验证命令未启动")

    def test_cancel_kills_uncooperative_command_and_records_interruption(self):
        process, directory = self.start_hanging()
        process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=8)
        self.assertEqual(process.returncode, 3, stdout + stderr)
        result = json.loads((directory / "result.json").read_text())
        self.assertEqual(result["outcome"], "interrupted")
        self.assertEqual(result["exit_code"], -signal.SIGKILL)
        self.assertTrue(result["process_group_gone"])
        self.assertIn("interrupted", self.assemble()["verification"][0]["result"])

    def test_missing_terminal_record_is_preserved_as_unknown(self):
        run = self.run_record()
        # 模拟强杀留下的文件集合，测试不制造实际孤儿进程。
        (Path(run["run_path"]) / "result.json").unlink()
        report = self.assemble()
        self.assertIn("退出结果未知", report["verification"][0]["result"])

    @unittest.skipUnless(REAL_JUST, "需要安装 just 以验证真实入口")
    def test_real_just_smoke(self):
        self.fake.unlink()
        (self.h.wt / "justfile").write_text('test *ARGS:\n    @printf "%s\\n" "{{ARGS}}"\n')
        run = self.run_record(parameters=("smoke",))
        self.assertEqual(run["exit_code"], 0)
        self.assertIn("smoke", run["log_tail"])

    @unittest.skipUnless(REAL_JUST, "需要安装 just 以验证真实入口")
    def test_executor_final_records_nested_gates_and_failure(self):
        self.fake.unlink()
        (self.h.wt / "justfile").write_text(
            'final *GATES:\n    @just gate-full\n    @for gate in {{GATES}}; do just "$gate" || exit $?; done\n'
            'gate-full:\n    @echo FULL\ngate-browser:\n    @echo BROWSER\n'
            'gate-fail:\n    @echo FAILED\n    @exit 7\ngate-after:\n    @echo UNEXPECTED_AFTER\n')
        green = self.run_record(recipe="final", parameters=("gate-browser",))
        self.assertEqual(green["log_tail"].splitlines(), ["FULL", "BROWSER"])
        failed = self.run_record(recipe="final", parameters=("gate-fail", "gate-after"), expected=1)
        self.assertNotIn("UNEXPECTED_AFTER", Path(failed["log_path"]).read_text())
        self.assertNotEqual(failed["exit_code"], 0)
        for run in (green, failed):
            directory = Path(run["run_path"])
            self.assertTrue((directory / "started.json").exists())
            result = json.loads((directory / "result.json").read_text())
            self.assertEqual(result["outcome"], "exited")
            self.assertTrue(result["process_group_gone"])
        report = self.assemble()
        self.assertEqual(len(report["verification"]), 2)
        self.assertIn("final gate-browser", report["verification"][0]["command"])
        self.assertIn(failed["run_path"], report["verification"][1]["result"])


if __name__ == "__main__":
    unittest.main()

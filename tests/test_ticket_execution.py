"""通过公开 CLI 验证整票协调、implementer gate-fix、review 和恢复边界。"""

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any

import pytest

import review_fixture
import test_controller as fixture
from fixture_support import closure_source

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/beadwork-run/scripts"

pytestmark = pytest.mark.workflow


class TicketExecutionTests(unittest.TestCase):
    def setUp(self):
        self.h: Any = fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.utility_fixture = False
        self.h.prepare(
            mode="new",
            test_mode="direct_verification",
            approved_seams=[],
        )
        self.root_dispatch = self.h.dispatch
        self.serial = 0
        fake = self.h.root / "bin/just"
        fake.write_text(
            "#!"
            + sys.executable
            + "\n"
            + "import os,sys\nif sys.argv[1:] == ['--summary']:\n    print('install test gate-core gate-full'); sys.exit(0)\nassert sys.argv[1:3] == ['--one','--']\nprint('验证结果')\nsys.exit(7 if os.environ.get('FAIL_GATE') == sys.argv[3] else 0)\n"
        )
        fake.chmod(0o755)
        self.stage()

    def cli(self, command, *args, ok=True, env=None):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "beadwork.py"),
                command,
                *map(str, args),
            ],
            cwd=self.h.root,
            env=env or self.h.env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def file(self, name, data, folder=None):
        self.serial += 1
        path = (folder or self.h.root) / f"{name}-{self.serial}.json"
        self.h.put(path, data)
        return path

    def stage(self, continuation="resume", ok=True, **facts):
        result = self.cli(
            "executor",
            "ticket-stage",
            "--dispatch",
            self.root_dispatch,
            "--input",
            self.file("facts", dict(continuation=continuation, **facts)),
            ok=ok,
        )
        if ok:
            self.sd = Path(result["stage_dispatch"])
            self.wd = Path(result["implementer_dispatch"])
            self.stage_info = result
            self.assertEqual(
                result["active_stage_context_source"],
                json.loads(self.wd.read_text())["active_stage_context_source"],
            )
            launch = {"fork_turns": "none", "required": True}
            self.assertEqual(result["implementer_launch_context"], launch)
            self.assertEqual(json.loads(self.wd.read_text())["launch_context"], launch)
        return result

    def commit(self):
        self.serial += 1
        (self.h.wt / "ticket.txt").write_text(f"实现 {self.serial}")
        self.h.h.git(self.h.wt, "add", "ticket.txt")
        self.h.h.git(self.h.wt, "commit", "-m", f"test-1 实现 {self.serial}")

    def gate(self, recipe="gate-core", fail=False, delivery=True):
        argv = ["--dispatch", self.wd, "--recipe", recipe]
        if delivery:
            argv.append("--delivery")
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(SCRIPTS / "beadwork.py"),
                "run-verification",
                *map(str, argv),
            ],
            cwd=self.h.root,
            env={
                **self.h.env,
                "FAIL_GATE": recipe if fail else "",
            },
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1 if fail else 0, result.stdout + result.stderr)
        return Path(json.loads(result.stdout)["run_path"]) / "result.json"

    def draft(self, outcome="passed"):
        d = json.loads(self.wd.read_text())
        return {
            "status": "DONE" if outcome == "passed" else "BLOCKED",
            "outcome": outcome,
            "test_plan": {
                "decision_source": "ticket/spec",
                "red_evidence": "实际行为 red" if d["test_mode"] == "TDD" else None,
            },
            "acceptance": [{"criterion": "目标行为", "evidence": "实现与 gate 日志"}],
            "verification": [],
            "requested_context": [],
            "blockers": [] if outcome == "passed" else ["阶段未完成"],
            "concerns": [],
        }

    def implement(self, outcome="passed", ok=True, accept=True, **changes):
        draft = dict(
            self.draft(outcome),
            verification_notes={},
            stopped_tasks=True,
        )
        draft.update(changes)
        output = self.file("unused", {}, self.wd.parent)
        output.unlink()
        receipt = self.cli(
            "executor",
            "implementer-assemble",
            "--dispatch",
            self.wd,
            "--draft",
            self.file("writer-draft", draft),
            "--output",
            output,
            ok=ok,
        )
        if ok:
            rp = self.file("receipt", receipt, self.wd.parent)
            if accept:
                cp = closure_source(self.wd, output)
                self.cli(
                    "executor",
                    "implementer-accept",
                    "--dispatch",
                    self.sd,
                    "--report",
                    output,
                    "--receipt",
                    rp,
                    "--closure",
                    cp,
                )
            self.writer_report, self.writer_receipt = output, rp
        return receipt

    def review(self, blocking=False):
        e = review_fixture.ReviewFixture()
        e.h, e.dispatch, e.directory = self.h, self.sd, self.sd.parent
        evidence = None
        if (
            self.h.h.git(self.h.wt, "rev-parse", "HEAD")
            == json.loads(self.sd.read_text())["base_commit"]
        ):
            evidence = self.file(
                "acceptance", [{"criterion": "目标行为", "evidence": "现有行为与验证"}]
            )
        return e.collect(e.round(blocking=blocking, evidence=evidence))

    def assemble(self, reviews=(), outcome="passed", ok=True, **changes):
        draft = dict(self.draft(outcome), stopped_tasks=True, **changes)
        output = self.file("unused", {}, self.sd.parent)
        output.unlink()
        argv = [
            "ticket-assemble",
            "--dispatch",
            self.sd,
            "--draft",
            self.file("stage-draft", draft),
            "--output",
            output,
        ]
        result = self.cli("executor", *argv, ok=ok)
        if ok:
            self.stage_report = output
        return result

    def deliver(self, ok=True):
        output = self.file("unused", {}, self.root_dispatch.parent)
        output.unlink()
        receipt = self.cli(
            "executor",
            "ticket-deliver",
            "--dispatch",
            self.root_dispatch,
            "--output",
            output,
            ok=ok,
        )
        if ok:
            rp = self.file("receipt", receipt, output.parent)
            self.root_report, self.root_receipt = output, rp
            self.acceptance = output.parent / ("accepted-" + str(self.serial) + ".json")
            cp = closure_source(self.root_dispatch, output)
            self.cli(
                "controller",
                "accept",
                "--dispatch",
                self.root_dispatch,
                "--report",
                output,
                "--receipt",
                rp,
                "--output",
                self.acceptance,
                "--closure",
                cp,
            )
        return receipt

    def ready_writer(self):
        self.commit()
        self.gate()
        self.implement()

    def test_full_ticket_and_controller_accept(self):
        self.ready_writer()
        self.assemble([self.review()])
        self.deliver()
        self.stage(ok=False)

    def test_gate_exhaustion_advances_only_after_three_repairs(self):
        self.commit()
        failure = self.gate(fail=True)
        self.implement("code_failure", ok=False)
        for number in range(3):
            result = self.cli(
                "executor",
                "begin-gate-repair",
                "--dispatch",
                self.wd,
                "--failure",
                failure,
            )
            self.assertEqual(result["repair_number"], number + 1)
            self.stage()
            self.commit()
            failure = self.gate(fail=True)
        self.implement("code_failure")
        self.assemble(outcome="code_failure")
        self.stage(ok=False)
        self.stage("repair")
        self.assertEqual(self.stage_info["stage"], 1)
        context = json.loads(
            Path(self.stage_info["active_stage_context_source"]["path"]).read_text()
        )
        self.assertEqual(context["continuation"], "repair")
        self.assertEqual(context["blocking_findings"], [])
        self.assertEqual(
            context["previous_implementer_source"]["report"]["path"],
            str(self.writer_report),
        )
        failure = self.gate(fail=True)
        result = self.cli(
            "executor",
            "begin-gate-repair",
            "--dispatch",
            self.wd,
            "--failure",
            failure,
        )
        self.assertEqual(result["repair_number"], 1)


if __name__ == "__main__":
    unittest.main()

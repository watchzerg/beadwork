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
    initial_mode = "direct_verification"
    initial_seams: list[str] = []

    def setUp(self):
        self.h: Any = fixture.ControllerTests()
        self.h.setUp()
        self.addCleanup(self.h.doCleanups)
        self.h.utility_fixture = False
        self.h.prepare(
            mode="new",
            test_mode=self.initial_mode,
            approved_seams=self.initial_seams,
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


@pytest.fixture
def adaptation():
    h = TicketExecutionTests()
    h.initial_mode = "TDD"
    h.initial_seams = ["S1"]
    try:
        h.setUp()
        yield h
    finally:
        h.doCleanups()


def adapt(h, mode="direct_verification", ok=True):
    facts = h.file(
        "adapt",
        {
            "mode": mode,
            "reason": "完整基线行为与覆盖已核对",
            "acceptance": [{"criterion": "目标行为", "evidence": "基线源码与测试"}],
            "verification": [{"command": "基线验证", "result": "通过"}],
        },
    )
    result = h.cli("executor", "ticket-adapt-plan", "--dispatch", h.sd, "--input", facts, ok=ok)
    if ok:
        h.sd, h.wd = Path(result["stage_dispatch"]), Path(result["implementer_dispatch"])
    return result


def block_stage(h, status, outcome, filename, stopped=True):
    output = h.sd.parent / filename
    draft = dict(
        h.draft(outcome),
        status=status,
        stopped_tasks=stopped,
        requested_context=["补齐基线事实"] if status == "NEEDS_CONTEXT" else [],
    )
    h.cli(
        "executor",
        "ticket-assemble",
        "--dispatch",
        h.sd,
        "--draft",
        h.file("blocked-draft", draft),
        "--output",
        output,
    )
    return output


def add_context(h):
    import hashlib

    source = h.file("context", {"fact": "已核对基线要求，需求与 seam 不变"})
    facts = h.file(
        "context-input",
        {
            "reason": "补齐恢复事实",
            "sources": [
                {"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
            ],
        },
    )
    return h.cli("executor", "context-add", "--dispatch", h.root_dispatch, "--input", facts)


@pytest.mark.parametrize("filename", ["report.json", "blocked-custom.json"])
@pytest.mark.parametrize(
    "status,outcome",
    [
        ("NEEDS_CONTEXT", "blocked"),
        ("BLOCKED", "blocked"),
        ("BLOCKED", "interrupted"),
    ],
)
def test_blocked_plan_adaptation_completes_same_stage(adaptation, filename, status, outcome):
    h = adaptation
    original = json.loads(h.sd.read_text())
    # 保留已有验证来源和已接纳的部分实现交付。
    h.gate()
    h.implement("blocked")
    old_report = block_stage(h, status, outcome, filename)
    old_bytes = old_report.read_bytes()
    checkpoints = {p: p.read_bytes() for p in h.root_dispatch.parent.glob("checkpoint-*.json")}
    if status == "NEEDS_CONTEXT":
        add_context(h)
    h.stage()
    result = adapt(h)
    current = json.loads(h.sd.read_text())
    for key in (
        "base_commit",
        "stage",
        "stage_base",
        "models",
        "approved_seams",
        "gate_repair_root",
    ):
        assert current[key] == original[key]
    assert result["stage"] == 0
    assert old_report.read_bytes() == old_bytes
    assert all(p.read_bytes() == content for p, content in checkpoints.items())
    adjustment = json.loads(Path(current["plan_adjustment"]["path"]).read_text())
    prior = json.loads(Path(adjustment["recovery"]["checkpoint"]["path"]).read_text())
    assert prior["state"]["selected_stage"]["report"]["path"] == str(old_report)
    h.stage()
    # 同阶段再次适配不重置阶段或来源；最终按已有行为完成整票验收。
    adapt(h, "TDD")
    adapt(h)
    h.gate()
    h.implement()
    h.assemble([h.review()])
    h.deliver()
    report = json.loads(h.root_report.read_text())
    assert report["delivery_kind"] == "already_satisfied"
    assert len(report["execution"]["implementers"]) == 2
    assert report["stage"] == 0


def test_adaptation_requires_stopped_tasks_and_context(adaptation):
    h = adaptation
    block_stage(h, "NEEDS_CONTEXT", "blocked", "report.json", stopped=False)
    assert "停止" in adapt(h, ok=False)["error"]
    block_stage(h, "NEEDS_CONTEXT", "blocked", "corrected.json")
    assert "context-add" in adapt(h, ok=False)["error"]
    add_context(h)
    adapt(h)


def test_adaptation_rejects_delivered_writer(adaptation):
    h = adaptation
    h.ready_writer()
    assert "实现已交付" in adapt(h, ok=False)["error"]
    # 阶段报告的部分状态不能解冻已经成功交付的 writer。
    block_stage(h, "BLOCKED", "blocked", "report.json")
    assert "实现已交付" in adapt(h, ok=False)["error"]


def test_adaptation_rejects_review_and_terminal_stage(adaptation):
    h = adaptation
    h.ready_writer()
    review = h.review(blocking=True)
    assert "review" in adapt(h, ok=False)["error"]
    h.assemble([review], outcome="code_failure")
    assert "代码失败" in adapt(h, ok=False)["error"]
    h.stage("repair")
    adapt(h)
    h.commit()
    h.gate()
    h.implement()
    h.assemble([h.review()])
    assert "已完成" in adapt(h, ok=False)["error"]


def test_adaptation_and_writer_freeze_on_reserved_review(adaptation):
    import sys
    from unittest.mock import patch

    with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
        import dispatch_contract
        import ticket_state

        h = adaptation
        ticket_state.reserve_review(dispatch_contract.dispatch(str(h.sd)))
        assert "review" in adapt(h, ok=False)["error"]
        with pytest.raises(ValueError, match="review"):
            ticket_state.require_writer(dispatch_contract.dispatch(str(h.wd)))


def test_adaptation_preserves_used_gate_repairs(adaptation):
    h = adaptation
    failure = h.gate(fail=True)
    first = h.cli("executor", "begin-gate-repair", "--dispatch", h.wd, "--failure", failure)
    assert first["repair_number"] == 1
    original = Path(first["gate_repair_path"]).read_bytes()
    h.implement("blocked")
    block_stage(h, "BLOCKED", "blocked", "report.json")
    adapt(h)
    failure = h.gate(fail=True)
    second = h.cli("executor", "begin-gate-repair", "--dispatch", h.wd, "--failure", failure)
    assert second["repair_number"] == 2
    assert second["remaining_repairs"] == 1
    assert Path(first["gate_repair_path"]).read_bytes() == original


def test_adaptation_revalidates_original_blocked_report(adaptation):
    h = adaptation
    report = block_stage(h, "BLOCKED", "blocked", "report.json")
    adapt(h)
    report.write_text(report.read_text() + "\n")
    assert "证据文件已变化" in h.stage(ok=False)["error"]


def test_adaptation_requires_dispatcher_stop_observation(adaptation):
    h = adaptation
    h.implement("blocked", accept=False)
    closure = closure_source(h.wd, h.writer_report, observed_stopped=False)
    h.cli(
        "executor",
        "implementer-accept",
        "--dispatch",
        h.sd,
        "--report",
        h.writer_report,
        "--receipt",
        h.writer_receipt,
        "--closure",
        closure,
    )
    assert "收尾观察" in adapt(h, ok=False)["error"]
    # 新交付和新的派发者观察追加到检查点，不覆盖原报告或收尾证据。
    h.implement("blocked")
    adapt(h)


@pytest.mark.parametrize("source_kind", ["report", "closure"])
def test_adaptation_revalidates_implementer_recovery_sources(adaptation, source_kind):
    h = adaptation
    h.implement("blocked")
    latest = sorted(h.root_dispatch.parent.glob("checkpoint-*.json"))[-1]
    state = json.loads(latest.read_text())["state"]
    report_source = state["implementer_sources"][-1]["report"]
    source = (
        report_source if source_kind == "report" else state["closures"][report_source["sha256"]]
    )
    if "closure_source" in source:
        source = source["closure_source"]
    adapt(h)
    path = Path(source["path"])
    path.write_text(path.read_text() + "\n")
    assert "证据文件已变化" in h.stage(ok=False)["error"]


if __name__ == "__main__":
    unittest.main()

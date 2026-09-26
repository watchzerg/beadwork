"""单票与最终 review 后的文档收尾、证据复用和停止条件。"""

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import document_closeout
import test_finalization
import test_ticket_execution
from fixture_support import stop_observation

pytestmark = pytest.mark.workflow


@pytest.fixture(params=["ticket", "final"])
def flow(request):
    final = request.param == "final"
    f: Any = (
        test_finalization.FinalizationTests()
        if final
        else test_ticket_execution.TicketExecutionTests()
    )
    if not final:
        f.initial_mode, f.initial_seams = "TDD", ["S1"]
    f.setUp()
    try:
        if final:
            stage = f.stage()
            f.done_document(stage)
            f.gate(stage)
            call = f.call
        else:
            test_ticket_execution.adapt(f)
            stage = f.sd
            f.commit()
            f.gate()
            f.implement()

            def call(*args, **kwargs):
                return f.cli("executor", *args, **kwargs)

        yield SimpleNamespace(f=f, final=final, stage=stage, call=call)
    finally:
        f.doCleanups()


def review(flow, scope="docs"):
    f = flow.f
    return (
        f.review(flow.stage, blocking=True, repair_scope=scope)
        if flow.final
        else f.review(blocking=True, repair_scope=scope)
    )


def prepare(flow, ok=True):
    path = flow.f.h.root / "closeout-input.json"
    path.write_text(
        json.dumps({"files": ["README.md"], "reason": "只补齐已实现行为的使用说明，不改变执行协议"})
    )
    return flow.call("document-closeout-prepare", "--dispatch", flow.stage, "--input", path, ok=ok)


def finish(
    flow, prepared, outcome="passed", file="README.md", ok=True, after_commit=None, assemble_ok=True
):
    f = flow.f
    writer = Path(prepared["document_dispatch"])
    (f.h.wt / file).write_text("当前已验证行为的说明：" + str(flow.stage.parent.name) + "。\n")
    f.h.h.git(f.h.wt, "add", file)
    f.h.h.git(f.h.wt, "commit", "-m", "test-1 同步使用说明")
    if after_commit:
        after_commit()
    draft = {
        "status": "DONE",
        "outcome": "passed",
        "result": "updated",
        "inspected": [{"source": "原始 findings 与实际实现", "assessment": "核对说明与已验证行为"}],
        "summary": "已修复文档 findings",
        "verification_notes": {},
        "stopped_tasks": True,
        "blockers": [],
        "remaining_work": [],
    }
    path = writer.parent / "draft.json"
    path.write_text(json.dumps(draft))
    report = writer.parent / "report.json"
    receipt = flow.call(
        "document-assemble",
        "--dispatch",
        writer,
        "--draft",
        path,
        "--output",
        report,
        ok=assemble_ok,
    )
    if not assemble_ok:
        return receipt
    receipt_path = writer.parent / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    observation = writer.parent / "observation.json"
    observation.write_text(json.dumps(stop_observation(report)))
    assessment = writer.parent / "assessment.json"
    assessment.write_text(
        json.dumps(
            {
                "outcome": outcome,
                "dispositions": [
                    {
                        "axis": "standards",
                        "finding_index": 0,
                        "resolved": outcome == "passed",
                        "evidence": "核对 README 与实际实现",
                    }
                ],
                "scope_evidence": "已核对全部提交，仅修改行为说明",
                "checks_evidence": "已检查链接和命令示例",
                "blockers": []
                if outcome == "passed"
                else [
                    "仍有遗漏"
                    if outcome == "blocked"
                    else "需求要求实际实现补齐，文档修改不足以解决"
                ],
            }
        )
    )
    return flow.call(
        "document-closeout-accept",
        "--dispatch",
        flow.stage,
        "--report",
        report,
        "--receipt",
        receipt_path,
        "--observation",
        observation,
        "--input",
        assessment,
        ok=ok,
    )


def assemble(flow, outcome="passed", ok=True):
    if flow.final:
        return flow.f.assemble(
            flow.stage,
            status="READY_TO_MERGE" if outcome == "passed" else "BLOCKED",
            outcome=outcome,
            ok=ok,
        )
    return flow.f.assemble(outcome=outcome, ok=ok)


def test_docs_only_finishes_with_original_gate_and_review(flow):
    collection = review(flow)
    original = collection.read_bytes()
    head = flow.f.h.h.git(flow.f.h.wt, "rev-parse", "HEAD")
    prepared = prepare(flow)
    assert prepared["document_launch_context"] == {"fork_turns": "none", "required": True}
    writer = json.loads(Path(prepared["document_dispatch"]).read_text())
    assert writer["base_commit"] == head
    finish(flow, prepared)
    assert collection.read_bytes() == original
    assert json.loads(original)["gate"] == "BLOCKED"
    assert json.loads(original)["repair_route"] == "docs"
    assert not list(Path(prepared["document_dispatch"]).parent.glob("verification-*"))
    assert "已派发" in prepare(flow, ok=False)["error"]
    with pytest.raises(ValueError, match="已验收"):
        document_closeout.require_writer(writer)
    if flow.final:
        report, _ = assemble(flow)
        result = json.loads(report.read_text())
        assert len(result["review_rounds"]) == 1
        assert {row["head_commit"] for row in result["verification"]} == {head}
        delivered = flow.call(
            "final-deliver",
            "--dispatch",
            flow.f.root,
            "--output",
            flow.f.root.parent / "delivered.json",
        )
        flow.f.h.deliver(json.loads(Path(delivered["report_path"]).read_text()))
        flow.f.h.accept()
    else:
        assemble(flow)
        result = json.loads(flow.f.stage_report.read_text())
        assert result["review"]["attempts"] == 1
        assert result["review"]["gate"] == "BLOCKED"
        flow.f.deliver()
    assert result["stage"] == 0
    assert result["head_commit"] != head
    assert document_closeout.candidate_head(result) == head
    tampered = dict(result, head_commit=head)
    with pytest.raises(ValueError, match="未覆盖"):
        document_closeout.validate(tampered)


def test_failed_closeout_stops_without_another_writer(flow):
    review(flow)
    prepared = prepare(flow)
    finish(flow, prepared, outcome="blocked")
    assemble(flow, outcome="blocked")
    assemble(flow, ok=False)
    assert "已派发" in prepare(flow, ok=False)["error"]


def test_code_findings_keep_existing_repair_route(flow):
    collection = review(flow, "code")
    assert json.loads(collection.read_text())["repair_route"] == "code"
    assert "全部阻塞项" in prepare(flow, ok=False)["error"]
    assemble(flow, outcome="code_failure")


def test_closeout_requires_scoped_changes(flow):
    review(flow)
    prepared = prepare(flow)
    answer = finish(flow, prepared, file="unapproved.py", ok=False)
    assert "超出派发范围" in answer["error"]


def test_code_required_returns_to_normal_repair_stage(flow):
    review(flow)
    prepared = prepare(flow)
    finish(flow, prepared, outcome="code_required")
    assembled = assemble(flow, outcome="code_failure")
    if flow.final:
        _, receipt = assembled
        stage = flow.f.stage(previous=flow.stage, receipt=receipt, continuation="repair")
        flow.f.done_fixer(flow.f.stage_info["fixer_dispatch"])
        flow.stage = stage
        review(flow)
        finish(flow, prepare(flow))
        flow.f.assemble(stage, status="READY_TO_MERGE", outcome="passed")
    else:
        flow.f.stage(continuation="repair")
        flow.f.commit()
        flow.f.gate()
        flow.f.implement()
        flow.f.review()
        flow.f.assemble()
        flow.f.deliver()
    assert flow.f.stage_info["stage"] == 1


def run_document_check(flow, prepared, *, recipe="test", exit_code=0):
    binary = flow.f.h.root / "bin/just"
    binary.write_text(
        "#!" + sys.executable + "\nimport sys\n"
        "if sys.argv[1:]==['--summary']: print('install test gate-core gate-full')\n"
        f"else: print('文档检查'); sys.exit({exit_code})\n"
    )
    binary.chmod(0o755)
    return subprocess.run(
        [
            sys.executable,
            "-B",
            str(test_finalization.OPS),
            "run-verification",
            "--dispatch",
            prepared["document_dispatch"],
            "--recipe",
            recipe,
        ],
        cwd=flow.f.h.root,
        env=flow.f.h.env,
        text=True,
        capture_output=True,
    )


def test_document_checks_are_separate_from_code_gate(flow):
    review(flow)
    prepared = prepare(flow)
    forbidden = run_document_check(flow, prepared, recipe="gate-core")
    assert forbidden.returncode != 0 and "不运行代码 gate" in forbidden.stderr
    failed = run_document_check(flow, prepared, exit_code=1)
    assert failed.returncode == 1

    def check_repaired_docs():
        passed = run_document_check(flow, prepared)
        assert passed.returncode == 0, passed.stdout + passed.stderr

    finish(flow, prepared, after_commit=check_repaired_docs)
    assemble(flow)


def test_failed_document_check_cannot_disappear_after_commit(flow):
    review(flow)
    prepared = prepare(flow)
    failed = run_document_check(flow, prepared, exit_code=1)
    assert failed.returncode == 1
    result = finish(flow, prepared, assemble_ok=False)
    assert "文档定向检查" in result["error"]

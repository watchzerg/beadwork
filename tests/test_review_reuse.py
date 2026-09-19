"""review 校验复用只覆盖相同内容；更正、失败和收尾变化必须重新核对。"""

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest import TestCase, main
from unittest.mock import patch

import pytest

import evidence
import handoff
import report_io
import review_evidence

pytestmark = pytest.mark.integration


class ReviewReuseTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        dispatch = self.root / "dispatch.json"
        evidence.write(
            dispatch,
            dict(
                role="executor",
                workflow_contract_version=1,
                dispatch_path=str(dispatch),
                report_path=str(self.root / "report.json"),
                base_commit="a" * 40,
            ),
        )
        folder = self.root / "review"
        folder.mkdir()
        self.round = folder / "round.json"
        record: dict[str, Any] = dict(
            dispatch=evidence.binding(dispatch),
            reviewed_base="a" * 40,
            reviewed_head="b" * 40,
            axes={},
        )
        self.sources = {}
        for axis in review_evidence.AXES:
            directory = folder / axis
            directory.mkdir()
            identity = directory / "dispatch.json"
            report = directory / "report.json"
            evidence.write(
                identity,
                dict(
                    axis=axis, reviewed_base="a" * 40, reviewed_head="b" * 40, handoff_required=True
                ),
            )
            evidence.write(
                report,
                dict(
                    axis=axis, reviewed_base="a" * 40, reviewed_head="b" * 40, findings=[], notes=[]
                ),
            )
            receipt = directory / "receipt.json"
            evidence.write(
                receipt,
                dict(
                    status="COMPLETED",
                    report_path=str(report),
                    report_sha256=evidence.digest(report),
                ),
            )
            closure = handoff.close(
                str(identity),
                str(report),
                dict(
                    task_id="review-task",
                    stopped=True,
                    observed_at="2026-09-19",
                    evidence="已观察到退出",
                    unresolved=[],
                ),
            )
            self.sources[axis] = dict(
                report=str(report), receipt=str(receipt), closure=closure["closure_source"]["path"]
            )
            record["axes"][axis] = evidence.binding(identity)
        evidence.write(self.round, record)

    def test_same_content_reuses_checks_but_changed_closure_is_rejected(self):
        verified = set()
        with patch.object(report_io, "reviewer", wraps=report_io.reviewer) as checks:
            for _ in range(2):
                review_evidence.pair_from_sources(self.round, self.sources, verified=verified)
            self.assertEqual(checks.call_count, 2)
            closure = Path(self.sources["standards"]["closure"])
            value = evidence.read(closure)
            value["stopped"] = False
            closure.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "未确认任务停止"):
                review_evidence.pair_from_sources(self.round, self.sources, verified=verified)
            self.assertEqual(checks.call_count, 2)

    def test_failed_check_is_not_reused(self):
        verified = set()
        with patch.object(report_io, "reviewer", side_effect=ValueError("模拟 verifier 失败")):
            with self.assertRaisesRegex(ValueError, "模拟 verifier 失败"):
                review_evidence.pair_from_sources(self.round, self.sources, verified=verified)
        self.assertFalse(verified)
        with patch.object(report_io, "reviewer", wraps=report_io.reviewer) as checks:
            review_evidence.pair_from_sources(self.round, self.sources, verified=verified)
            self.assertEqual(checks.call_count, 2)

    def test_corrected_report_and_receipt_require_new_check(self):
        verified = set()
        review_evidence.pair_from_sources(self.round, self.sources, verified=verified)
        old = self.sources["standards"]
        report = Path(old["report"]).with_name("correction.json")
        value = evidence.read(old["report"])
        value["notes"].append("补充依据")
        evidence.write(report, value)
        receipt = report.with_name("correction-receipt.json")
        evidence.write(
            receipt,
            dict(
                status="COMPLETED", report_path=str(report), report_sha256=evidence.digest(report)
            ),
        )
        closure = handoff.close(
            str(report.parent / "dispatch.json"),
            str(report),
            dict(
                task_id="review-task",
                stopped=True,
                observed_at="2026-09-19",
                evidence="已观察到退出",
                unresolved=[],
            ),
        )
        self.sources["standards"] = dict(
            report=str(report), receipt=str(receipt), closure=closure["closure_source"]["path"]
        )
        with patch.object(report_io, "reviewer", wraps=report_io.reviewer) as checks:
            _, _, pair, _ = review_evidence.pair_from_sources(
                self.round, self.sources, verified=verified
            )
            self.assertEqual(checks.call_count, 1)
            self.assertEqual(pair["standards"]["notes"], ["补充依据"])


if __name__ == "__main__":
    main()

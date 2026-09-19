"""Beadwork 测试的进程隔离、marker 分类与公共路径。"""

from pathlib import Path
import os

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/beadwork-run/scripts"

WORKFLOW_MODULES = {"test_ticket_execution.py", "test_handoff.py", "test_main_sync.py"}
UNIT_MODULES = {
    "test_evidence.py", "test_graph.py", "test_maintenance_check.py",
    "test_review_reuse.py", "test_stage_policy.py", "test_verification_records.py",
    "test_workflow_contract.py",
}


def pytest_collection_modifyitems(items):
    for item in items:
        name = Path(str(item.path)).name
        marker = pytest.mark.workflow if name in WORKFLOW_MODULES else (
            pytest.mark.unit if name in UNIT_MODULES else pytest.mark.integration)
        item.add_marker(marker)


@pytest.fixture(autouse=True)
def restore_process_environment():
    """每例恢复完整环境，允许 xdist 进程安全地并行测试。"""
    before = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(before)

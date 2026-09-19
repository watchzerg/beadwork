"""在隔离 pytest collection 中验证 marker 契约。"""

from pathlib import Path

import pytest


pytestmark = pytest.mark.integration
MARKER_CONTRACT = Path(__file__).with_name("marker_contract.py")


def isolated_collection(pytester: pytest.Pytester, source: str):
    pytester.makeini(
        """[pytest]
addopts = --strict-markers
markers =
    unit: pure rules
    integration: local boundary
    workflow: operation chain
    distribution: copied skill distribution
"""
    )
    pytester.makeconftest(
        f"""import sys
sys.path.insert(0, {str(MARKER_CONTRACT.parent)!r})
from marker_contract import pytest_collection_modifyitems
"""
    )
    pytester.makepyfile(test_sample=source)
    return pytester.runpytest_subprocess("--collect-only", "-q")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("def test_unmarked(): pass", "主 marker 应恰好一个，实际为 无"),
        (
            "import pytest\n@pytest.mark.unit\n@pytest.mark.integration\ndef test_multiple(): pass",
            "主 marker 应恰好一个，实际为 integration, unit",
        ),
        (
            "import pytest\n@pytest.mark.distribution\n@pytest.mark.workflow\ndef test_distribution(): pass",
            "distribution 必须同时属于 integration",
        ),
        (
            "import pytest\n@pytest.mark.unknown\ndef test_unknown(): pass",
            "unknown",
        ),
    ],
)
def test_invalid_marker_collection_fails(pytester, source, message):
    result = isolated_collection(pytester, source)
    assert result.ret != 0
    output = "\n".join([*result.stdout.lines, *result.stderr.lines])
    assert message in output


@pytest.mark.parametrize(
    "source",
    [
        "import pytest\npytestmark = pytest.mark.unit\ndef test_unit(): pass",
        (
            "import pytest\npytestmark = pytest.mark.unit\n"
            "@pytest.mark.unit\ndef test_inherited_same_marker(): pass"
        ),
        (
            "import pytest\n@pytest.mark.integration\n@pytest.mark.distribution\n"
            "def test_distribution(): pass"
        ),
    ],
)
def test_valid_marker_collection_succeeds(pytester, source):
    result = isolated_collection(pytester, source)
    assert result.ret == 0
    result.stdout.fnmatch_lines(["*1 test collected*"])

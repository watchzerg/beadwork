"""修复路由只由两轴阻塞项共同决定。"""

import pytest

from review_evidence import repair_route

pytestmark = pytest.mark.unit


def test_mixed_findings_route_and_nonblocking_smells():
    pair = {
        "standards": {"findings": [{"blocking": False, "repair_scope": "code"}]},
        "spec": {"findings": []},
    }
    assert repair_route(pair) == "none"
    pair["spec"]["findings"].append({"blocking": True, "repair_scope": "docs"})
    assert repair_route(pair) == "docs"
    pair["standards"]["findings"].append({"blocking": True, "repair_scope": "code"})
    assert repair_route(pair) == "code"

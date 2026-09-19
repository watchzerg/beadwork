"""pytest 主层 marker 的最小 collection 契约。"""

from __future__ import annotations

import pytest

MAIN_MARKERS = frozenset({"unit", "integration", "workflow"})


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    errors: list[str] = []
    for item in items:
        marker_names = {marker.name for marker in item.iter_markers()}
        main_markers = marker_names & MAIN_MARKERS
        if len(main_markers) != 1:
            actual = ", ".join(sorted(main_markers)) or "无"
            errors.append(f"{item.nodeid}: 主 marker 应恰好一个，实际为 {actual}")
        if "distribution" in marker_names and "integration" not in main_markers:
            errors.append(f"{item.nodeid}: distribution 必须同时属于 integration")
    if errors:
        raise pytest.UsageError("测试 marker 分类无效：\n- " + "\n- ".join(errors))

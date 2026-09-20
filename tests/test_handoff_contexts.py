"""context 链的文件筛选不放宽正式记录的完整性校验。"""

import pytest

import evidence
import handoff

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("corruption", ["missing_record", "previous_binding", "source_binding"])
def test_contexts_reject_broken_numbered_chain(tmp_path, corruption):
    source = tmp_path / "facts.txt"
    source.write_text("补充事实")
    first = tmp_path / "context-add-000001.json"
    evidence.write(first, {"sources": [evidence.binding(str(source))], "previous": None})
    second = tmp_path / "context-add-000002.json"
    previous = evidence.binding(str(first))
    evidence.write(second, {"sources": [], "previous": previous})
    dispatch = {"dispatch_path": str(tmp_path / "dispatch.json")}
    assert handoff.contexts(dispatch) == [previous, evidence.binding(str(second))]

    if corruption == "missing_record":
        first.unlink()
    elif corruption == "previous_binding":
        first.write_text(first.read_text() + "\n")
    else:
        source.write_text("已改变的事实")

    with pytest.raises(ValueError):
        handoff.contexts(dispatch)

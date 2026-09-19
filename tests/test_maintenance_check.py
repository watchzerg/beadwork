from pathlib import Path

import pytest

import maintenance_check

pytestmark = pytest.mark.integration


def test_local_link_check(tmp_path):
    root = Path(tmp_path)
    (root / "docs").mkdir()
    (root / "skills").mkdir()
    (root / "README.md").write_text("[说明](docs/target.md)")
    (root / "AGENTS.md").write_text("维护约束")
    (root / "docs/target.md").write_text("目标")
    source = root / "docs/source.md"
    source.write_text("[有效](target.md) [外部](https://example.com)")
    assert maintenance_check.local_links(root) == []
    (root / "AGENTS.md").write_text("[断裂](missing.md)")
    assert maintenance_check.local_links(root) == [{"source": "AGENTS.md", "target": "missing.md"}]


def test_structure_check_requires_explicit_invocation_policy(tmp_path):
    root = Path(tmp_path)
    (root / "skills/beadwork-run/references").mkdir(parents=True)
    (root / "skills/beadwork-run/scripts").mkdir()
    (root / "skills/beadwork-run/agents").mkdir()
    (root / "skills/beadwork-run/SKILL.md").write_text("skill")
    policy = root / "skills/beadwork-run/agents/openai.yaml"
    policy.write_text("policy:\n  allow_implicit_invocation: false\n")
    assert maintenance_check.structure_check(root)["exit_code"] == 0
    policy.write_text("policy:\n  allow_implicit_invocation: true\n")
    assert maintenance_check.structure_check(root)["exit_code"] == 1


def test_syntax_check_does_not_create_bytecode(tmp_path):
    scripts = tmp_path / "skills/beadwork-run/scripts"
    scripts.mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (scripts / "valid.py").write_text("answer = 42\n")
    assert maintenance_check.syntax_check(tmp_path)["exit_code"] == 0
    assert not (scripts / "__pycache__").exists()

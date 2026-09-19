from pathlib import Path

import maintenance_check


def test_local_link_check(tmp_path):
    root = Path(tmp_path); (root / "docs").mkdir(); (root / "skills").mkdir()
    (root / "docs/target.md").write_text("目标")
    source = root / "docs/source.md"; source.write_text("[有效](target.md) [外部](https://example.com)")
    assert maintenance_check.local_links(root) == []
    source.write_text("[断裂](missing.md)")
    assert maintenance_check.local_links(root) == [{"source": "docs/source.md", "target": "missing.md"}]


def test_pytest_argv_keeps_unit_serial_and_parallelizes_slow_suites(tmp_path):
    unit = maintenance_check.pytest_argv(tmp_path, "unit", 8)
    integration = maintenance_check.pytest_argv(tmp_path, "integration", 8)
    assert "-n" not in unit
    assert integration[-3:] == ["-n", "8", "--dist=worksteal"]


def test_syntax_check_does_not_create_bytecode(tmp_path):
    scripts = tmp_path / "skills/beadwork-run/scripts"
    scripts.mkdir(parents=True)
    (scripts / "valid.py").write_text("answer = 42\n")
    assert maintenance_check.syntax_check(tmp_path)["exit_code"] == 0
    assert not (scripts / "__pycache__").exists()

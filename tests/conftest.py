"""Beadwork 测试的 marker 契约与公共路径。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/beadwork-run/scripts"

pytest_plugins = ("pytester",)

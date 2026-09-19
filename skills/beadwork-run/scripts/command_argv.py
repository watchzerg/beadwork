"""构造指向当前 skill 分发目录统一 CLI 的 argv。"""

from __future__ import annotations

import sys
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().with_name("beadwork.py")


def beadwork_argv(*arguments: object) -> list[str]:
    """返回不经过 shell 的统一 CLI argv。"""
    return [sys.executable, "-B", str(ENTRYPOINT), *(str(value) for value in arguments)]

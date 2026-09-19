#!/usr/bin/env python3
# ruff: noqa: E402, I001, UP036 - 版本检查和自带模块路径必须先于运行模块加载
"""Beadwork 唯一公开 Python CLI。"""

import json
import sys
from pathlib import Path


if sys.version_info < (3, 14):
    print(
        json.dumps(
            {
                "error": "Beadwork 需要 Python 3.14 或更高版本；"
                f"当前为 {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
            },
            ensure_ascii=False,
        ),
        file=sys.stderr,
    )
    raise SystemExit(2)

sys.dont_write_bytecode = True
scripts = str(Path(__file__).resolve().parent)
if scripts not in sys.path:
    sys.path.insert(0, scripts)

import cli


if __name__ == "__main__":
    raise SystemExit(cli.main())

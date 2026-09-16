#!/usr/bin/env python3
"""兼容 CLI 文件名；实现位于可普通 import 的 executor_operations。"""
import json
import sys

from executor_operations import main


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        sys.exit(1)

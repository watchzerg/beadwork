#!/usr/bin/env python3
"""兼容 CLI 文件名；实现位于可普通 import 的 run_verification。"""

import json
import sys

import run_verification

if __name__ == "__main__":
    try:
        sys.exit(run_verification.main())
    except Exception as error:
        print(
            json.dumps({"outcome": "recorder_error", "error": str(error)}, ensure_ascii=False),
            file=sys.stderr,
        )
        sys.exit(2)

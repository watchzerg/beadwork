#!/usr/bin/env python3
"""兼容 CLI 文件名；实现位于可普通 import 的 verify_ticket。"""

import json
import sys

import verify_ticket

if __name__ == "__main__":
    verify_ticket._use_utf8()
    try:
        verify_ticket.main(sys.argv[1:])
    except Exception as error:
        verify_ticket._use_utf8()
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        sys.exit(1)

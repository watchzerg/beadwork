#!/usr/bin/env python3
"""phase 报告校验 CLI；实现位于 ``phase_validation``。"""

import json
import sys

import phase_validation

if __name__ == "__main__":
    try:
        phase_validation.main(sys.argv[1:])
    except Exception as error:
        sys.stderr.write(json.dumps({"error": str(error)}, ensure_ascii=False) + "\n")
        sys.exit(1)

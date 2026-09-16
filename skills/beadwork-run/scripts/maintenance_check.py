"""Beadwork 源码维护检查入口：docs、scripts 或 full。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def local_links(root):
    failures = []
    for source in sorted((root / "docs").rglob("*.md")) + sorted((root / "skills").rglob("*.md")):
        text = source.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", text):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("#") or target.startswith("<"):
                continue
            if not (source.parent / target).resolve().exists():
                failures.append({"source": str(source.relative_to(root)), "target": target})
    return failures


def run(root, name, argv):
    began = time.monotonic()
    result = subprocess.run([str(x) for x in argv], cwd=root, capture_output=True, text=True)
    return {"name": name, "argv": list(map(str, argv)), "exit_code": result.returncode,
            "seconds": round(time.monotonic() - began, 3), "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}


def check(root, profile, pattern=None):
    results = []
    links = local_links(root)
    results.append({"name": "local-links", "exit_code": 1 if links else 0, "seconds": 0, "failures": links})
    results.append(run(root, "diff-check", ["git", "diff", "--check"]))
    if profile in ("scripts", "full"):
        results.append(run(root, "py-compile", [sys.executable, "-B", "-m", "py_compile",
                                                *sorted((root / "skills/beadwork-run/scripts").glob("*.py"))]))
        results.append(run(root, "unittest", [sys.executable, "-B", "-m", "unittest", "discover",
                                              "-s", "skills/beadwork-run/scripts", "-p",
                                              "test_*.py" if profile == "full" else (pattern or "test_evidence.py")]))
        validator = Path.home() / ".codex/skills/.system/skill-creator/scripts/quick_validate.py"
        if validator.exists():
            results.append(run(root, "skill-validator", ["uv", "run", "--with", "pyyaml", "python",
                                                          validator, "skills/beadwork-run"]))
        else:
            results.append({"name": "skill-validator", "exit_code": None, "seconds": 0,
                            "skipped": "validator 不可用"})
    return {"profile": profile, "ok": all(row["exit_code"] in (0, None) for row in results),
            "results": results,
            "limits": ["未运行真实消费项目 ticket graph", "未验证真实 Codex 嵌套派发"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("profile", choices=("docs", "scripts", "full"))
    parser.add_argument("--pattern"); parser.add_argument("--output")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[3]
    result = check(root, args.profile, args.pattern)
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False)); sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__": main()

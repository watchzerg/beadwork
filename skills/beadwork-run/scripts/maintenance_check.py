"""Beadwork 源码维护检查入口：docs、显式测试分层或 full。"""
from __future__ import annotations

import argparse
import ast
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


def syntax_check(root):
    began = time.monotonic()
    failures = []
    for path in sorted((root / "skills/beadwork-run/scripts").glob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            failures.append({"path": str(path.relative_to(root)), "line": error.lineno, "error": error.msg})
    return {"name": "python-syntax", "exit_code": 1 if failures else 0,
            "seconds": round(time.monotonic() - began, 3), "failures": failures}


def pytest_argv(root, suite, jobs):
    result = [sys.executable, "-B", "-m", "pytest", "-m", suite if suite != "all" else
              "unit or integration or workflow", "--durations=20",
              "--junitxml", str(root / ".test-results" / f"{suite}.xml")]
    if suite != "unit" and jobs:
        result += ["-n", str(jobs), "--dist=worksteal"]
    return result


def check(root, profile, suite=None, jobs=4):
    results = []
    links = local_links(root)
    results.append({"name": "local-links", "exit_code": 1 if links else 0, "seconds": 0, "failures": links})
    results.append(run(root, "diff-check", ["git", "diff", "--check"]))
    if profile in ("scripts", "full"):
        selected = "all" if profile == "full" else suite
        if selected not in ("unit", "integration", "workflow", "all"):
            raise ValueError("scripts 必须使用 --suite 选择 unit、integration、workflow 或 all")
        (root / ".test-results").mkdir(exist_ok=True)
        results.append(syntax_check(root))
        results.append(run(root, "pytest-" + selected, pytest_argv(root, selected, jobs)))
    if profile == "full":
        validator = Path.home() / ".codex/skills/.system/skill-creator/scripts/quick_validate.py"
        if validator.exists():
            results.append(run(root, "skill-validator", ["uv", "run", "--with", "pyyaml", "python",
                                                          validator, "skills/beadwork-run"]))
        else:
            results.append({"name": "skill-validator", "exit_code": 1, "seconds": 0,
                            "error": "validator 不可用"})
    return {"profile": profile, "suite": suite, "jobs": jobs,
            "ok": all(row["exit_code"] == 0 for row in results),
            "results": results,
            "limits": ["未运行真实消费项目 ticket graph", "未验证真实 Codex 嵌套派发"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("profile", choices=("docs", "scripts", "full"))
    parser.add_argument("--suite", choices=("unit", "integration", "workflow", "all"))
    parser.add_argument("--jobs", type=int, default=4); parser.add_argument("--output")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[3]
    if args.jobs < 0: parser.error("--jobs 不能为负数")
    result = check(root, args.profile, args.suite, args.jobs)
    if args.output:
        Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False)); sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__": main()

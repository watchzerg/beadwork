"""按 Beadwork suite 约定构造并执行一次 pytest。"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


SUITES = {"unit", "integration", "workflow", "distribution", "all"}


def test_jobs() -> int:
    raw = os.environ.get("BEADWORK_TEST_JOBS", "4")
    try:
        jobs = int(raw)
    except ValueError as error:
        raise ValueError("BEADWORK_TEST_JOBS 必须是非负整数") from error
    if jobs < 0:
        raise ValueError("BEADWORK_TEST_JOBS 必须是非负整数")
    return jobs


def pytest_argv(root: Path, suite: str, extra: list[str], *, gate: bool = False) -> list[str]:
    if suite not in SUITES:
        raise ValueError(f"未知测试 suite：{suite}")
    if gate and (suite != "all" or extra):
        raise ValueError("完整门禁只允许无筛选的 all suite")
    if any(arg == "-m" or arg.startswith("-m=") for arg in extra):
        raise ValueError("额外 pytest 参数不能覆盖 suite 的 -m 选择")

    result = [sys.executable, "-B", "-m", "pytest"]
    if suite != "all":
        result.extend(["-m", suite])
    result.extend(
        [
            "--durations=20",
            "--junitxml",
            str(root / ".test-results" / f"{suite}.xml"),
        ]
    )
    jobs = test_jobs()
    if suite != "unit" and jobs:
        result.extend(["-n", str(jobs), "--dist=worksteal"])
    return result + extra


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    gate = bool(args and args[0] == "--gate")
    if gate:
        args.pop(0)
    if not args:
        print("用法：run_tests.py [--gate] <suite> [-- <pytest-args>...]", file=sys.stderr)
        return 2
    suite = args.pop(0)
    if args[:1] == ["--"]:
        args.pop(0)

    root = Path(__file__).resolve().parents[1]
    (root / ".test-results").mkdir(exist_ok=True)
    try:
        command = pytest_argv(root, suite, args, gate=gate)
    except ValueError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    environment = os.environ.copy()
    if gate:
        environment.pop("PYTEST_ADDOPTS", None)
    return subprocess.run(command, cwd=root, env=environment).returncode


if __name__ == "__main__":
    raise SystemExit(main())

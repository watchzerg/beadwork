"""Beadwork 仓库结构、文档链接和 Python 语法检查。"""

from __future__ import annotations

import ast
import json
import re
import sys
import time
from pathlib import Path

import yaml


def markdown_sources(root: Path) -> list[Path]:
    sources = [root / "README.md", root / "AGENTS.md"]
    sources.extend(sorted((root / "docs").rglob("*.md")))
    sources.extend(sorted((root / "skills").rglob("*.md")))
    return [source for source in sources if source.is_file()]


def local_links(root: Path) -> list[dict[str, str]]:
    failures = []
    for source in markdown_sources(root):
        text = source.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]*\]\(([^)]+)\)", text):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith(("#", "<")):
                continue
            if not (source.parent / target).resolve().exists():
                failures.append({"source": str(source.relative_to(root)), "target": target})
    return failures


def syntax_check(root: Path) -> dict[str, object]:
    began = time.monotonic()
    failures = []
    paths = sorted((root / "scripts").glob("*.py"))
    paths.extend(sorted((root / "skills/beadwork-run/scripts").glob("*.py")))
    for path in paths:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as error:
            failures.append(
                {"path": str(path.relative_to(root)), "line": error.lineno, "error": error.msg}
            )
    return {
        "name": "python-syntax",
        "exit_code": 1 if failures else 0,
        "seconds": round(time.monotonic() - began, 3),
        "failures": failures,
    }


def structure_check(root: Path) -> dict[str, object]:
    required = [
        "skills/beadwork-run/SKILL.md",
        "skills/beadwork-run/agents/openai.yaml",
        "skills/beadwork-run/references",
        "skills/beadwork-run/scripts",
    ]
    failures = [path for path in required if not (root / path).exists()]
    policy_path = root / "skills/beadwork-run/agents/openai.yaml"
    if policy_path.is_file():
        policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        if policy != {"policy": {"allow_implicit_invocation": False}}:
            failures.append("skills/beadwork-run/agents/openai.yaml: explicit-only policy")
    return {
        "name": "repository-structure",
        "exit_code": 1 if failures else 0,
        "failures": failures,
    }


def check(root: Path) -> dict[str, object]:
    links = local_links(root)
    results = [
        {"name": "local-links", "exit_code": 1 if links else 0, "failures": links},
        structure_check(root),
        syntax_check(root),
    ]
    return {"ok": all(row["exit_code"] == 0 for row in results), "results": results}


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    result = check(root)
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()

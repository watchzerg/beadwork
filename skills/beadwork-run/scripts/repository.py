"""仓库命令与事实检查；不管理阶段、tracker 或集成生命周期。"""

import os
import re
import subprocess
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run(args, cwd=None):
    result = subprocess.run([str(x) for x in args], cwd=cwd, capture_output=True, text=True)
    require(result.returncode == 0, f"命令失败 {args[0]} {args[1:]}：{result.stderr.strip()}")
    return result.stdout.rstrip("\n")


def git(root, *args):
    return run(["git", "-C", root, *args])


def status(root):
    return git(root, "status", "--porcelain=v1", "--untracked-files=all")


def sha(root, ref):
    result = git(root, "rev-parse", "--verify", ref)
    require(re.fullmatch(r"[0-9a-f]{40}", result), "需要完整 commit SHA")
    require(git(root, "cat-file", "-t", result) == "commit", "引用必须指向 commit")
    return result


def primary(root):
    entries = git(root, "worktree", "list", "--porcelain").split("\n\n")
    matches = [
        entry.splitlines()[0][9:]
        for entry in entries
        if "branch refs/heads/main" in entry.splitlines()
    ]
    require(len(matches) == 1, "必须有唯一 checkout main 的 primary worktree")
    return str(Path(matches[0]).resolve())


def topology(d, allow_missing=False):
    root = d["repository_root"]
    require(primary(root) == root, "primary worktree 已变化")
    expected = Path(root) / ".worktrees" / d["parent_id"]
    require(Path(d["worktree"]) == expected, "worktree 不符合固定布局")
    require(d["branch"] == "implement/" + d["parent_id"], "branch 不符合固定布局")
    if allow_missing and not expected.exists():
        return
    require(str(expected.resolve()) == str(expected), "worktree 路径不能经过 symlink")
    require(git(expected, "rev-parse", "--show-toplevel") == str(expected), "目标不是预期 worktree")
    require(
        git(expected, "symbolic-ref", "--short", "HEAD") == d["branch"],
        "implementation branch 不符",
    )
    require(
        git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
        == git(expected, "rev-parse", "--path-format=absolute", "--git-common-dir"),
        "worktree 不属于同一仓库",
    )


def primary_writable(root):
    require(primary(root) == root, "primary 必须 checkout main")
    require(not status(root), "primary 有未提交改动，暂不能更新 main")
    for name in (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
    ):
        path = git(root, "rev-parse", "--path-format=absolute", "--git-path", name)
        require(not Path(path).exists(), "primary 存在未完成 Git 操作：" + path)


def check_batch_beads(wt, main, head):
    commit_range = main + ".." + head
    # 普通提交仍逐个检查，不能用后续还原掩盖本批次写入。
    require(
        not git(
            wt,
            "log",
            "--full-history",
            "--no-merges",
            "-1",
            "--format=%H",
            commit_range,
            "--",
            ".beads",
        ),
        "批次包含 .beads commit",
    )
    for line in git(wt, "rev-list", "--min-parents=2", "--parents", commit_range).splitlines():
        commit, *parents = line.split()
        # 合入 main 时允许继承该父提交的 .beads；其余 merge 沿用第一父提交。
        upstream = [parent for parent in parents if git(wt, "merge-base", parent, main) == parent]
        source = upstream[-1] if upstream else parents[0]
        require(
            not git(wt, "diff", "--name-only", source, commit, "--", ".beads"),
            "merge 引入非 main 来源的 .beads 改动：" + commit,
        )


def paths(wt, *args):
    # 保留文件名中的空格、换行及末尾字符；禁用 rename 合并以列出旧、新路径。
    result = subprocess.run(["git", "--literal-pathspecs", "-C", wt, *args], capture_output=True)
    require(result.returncode == 0, os.fsdecode(result.stderr))
    return sorted({os.fsdecode(p) for p in result.stdout.split(b"\0") if p})


def workspace(d):
    require(d["role"] in ("executor", "implementer"), "需要 ticket dispatch")
    topology(d)
    wt = d["worktree"]
    require(sha(wt, d["base_commit"]) == d["base_commit"], "需要完整 BASE")
    git(wt, "merge-base", "--is-ancestor", d["base_commit"], "HEAD")
    return {
        "head": sha(wt, "HEAD"),
        "staged": paths(wt, "diff", "--cached", "--name-only", "--no-renames", "-z"),
        "unstaged": paths(wt, "diff", "--name-only", "--no-renames", "-z"),
        "untracked": paths(wt, "ls-files", "--others", "--exclude-standard", "-z"),
    }

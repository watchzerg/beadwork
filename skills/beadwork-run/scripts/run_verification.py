#!/usr/bin/env python3
"""执行一个 just 验证 recipe，保存原始日志并返回有界摘要；仅标准库。"""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import os
import re
import shlex
import shutil
import sys
import time
import uuid

sys.dont_write_bytecode = True

import dispatch_contract
import evidence
import final_state
import gate_repair
import process_runner
import repository
import ticket_state
import ticket_verification


def absolute(path):
    p = Path(path)
    repository.require(p.is_absolute() and p.resolve() == p, "需要无 symlink 的绝对路径")
    return p


def digest(path):
    return evidence.digest(path)


def write(path, value):
    with open(path, "x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


dispatch = dispatch_contract.verification_dispatch


def state(d):
    repository.topology(d)
    return {"head": repository.sha(d["worktree"], "HEAD"), "status": repository.status(d["worktree"])}


group_exists = process_runner.group_exists
stop = process_runner.stop


def tail(path):
    with Path(path).open("rb") as stream:
        stream.seek(max(0, Path(path).stat().st_size - 2048))
        return "\n".join(stream.read().decode("utf-8", errors="replace").splitlines()[-20:])


def run(args):
    repository.require(os.name == "posix", "此执行入口需要 POSIX 进程组")
    os.umask(0o077)
    source = absolute(args.dispatch)
    d = dispatch(source)
    before = state(d)
    if d.get("ticket_execution_version"):
        ticket_state.require_writer(d)
    if d.get('finalization_version') == 2:
        if d['role'] == 'fixer':
            final_state.require_writer(d)
        else:
            _, selected = final_state.selected(d)
            repository.require(not selected['round_path'], 'review 已开始，验证候选冻结')
            if d['stage']:
                repository.require(selected['fixes'] and evidence.read(evidence.bound(selected['fixes'][-1]['report']))['stopped_tasks'],
                          '补充验证前需验收 fixer 收尾')
    repository.git(d["worktree"], "merge-base", "--is-ancestor", d.get("base_commit", d.get("reviewed_main")), before["head"])
    repository.require(args.recipe in ("typecheck", "test", "final") or re.fullmatch(r"gate-[A-Za-z0-9_-]+", args.recipe),
              "仅执行 typecheck、test、final、gate-*")
    executable = shutil.which("just")
    repository.require(executable is not None, "未找到 just")
    repository.require(args.recipe in repository.run([executable, "--summary"], d["worktree"]).split(), "验证 recipe 不存在")
    parameters = args.parameters[1:] if args.parameters[:1] == ["--"] else args.parameters
    argv = ["just", "--one", "--", args.recipe, *parameters]
    attempt = None
    if args.delivery:
        if d['role'] == 'finalizer':
            repository.require(d.get('finalization_version') == 2 and not before['status'], '最终验证需要当前阶段干净 HEAD')
        else:
            attempt = gate_repair.delivery(d, before)
    directory = source.parent / ("verification-" + uuid.uuid4().hex)
    directory.mkdir(mode=0o700)
    started = {"dispatch_path": str(source), "dispatch_sha256": digest(source),
               "argv": argv, "executable": executable, "cwd": d["worktree"],
               "started_ns": time.time_ns(), "before": before}
    if attempt is not None:
        started["delivery_attempt"] = attempt
    write(directory / "started.json", started)
    print(json.dumps({"run_path": str(directory)}, ensure_ascii=False), file=sys.stderr, flush=True)
    began = time.monotonic()
    after = None
    log = directory / "output.log"
    executed = process_runner.run(argv, d["worktree"], log, executable=executable)
    try:
        after = state(d)
    except Exception as exc:
        executed.update(outcome="recorder_error", error=str(exc))
    if before != after and executed["outcome"] == "exited":
        executed["outcome"] = "state_changed"
    result = {"started_sha256": digest(directory / "started.json"), "ended_ns": time.time_ns(),
              "duration_seconds": round(time.monotonic() - began, 3), **executed, "after": after,
              "log_sha256": digest(log), "log_bytes": log.stat().st_size}
    # 部分文件永远不能被当作完整终态；SIGKILL 时保留 started/log。
    pending = directory / "result.pending"
    write(pending, result)
    pending.rename(directory / "result.json")
    summary = {"run_path": str(directory), "command": shlex.join(argv),
               "outcome": executed["outcome"], "exit_code": executed["exit_code"], "duration_seconds": result["duration_seconds"],
               "head": before["head"], "dirty": bool(before["status"]),
               "log_path": str(log), "log_tail": tail(log), "error": executed["error"]}
    print(json.dumps(summary, ensure_ascii=False))
    return ((0 if executed["exit_code"] == 0 else 1) if executed["outcome"] == "exited"
            else (3 if executed["outcome"] == "interrupted" else 2))


collect = ticket_verification.collect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dispatch", required=True)
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--delivery", action="store_true", help="固定干净 HEAD 的交付验证；开发定向验证不传")
    parser.add_argument("parameters", nargs=argparse.REMAINDER)
    return run(parser.parse_args())


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(json.dumps({"outcome": "recorder_error", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(2)

#!/usr/bin/env python3
"""执行一个 just 验证 recipe，保存原始日志并返回有界摘要；仅标准库。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
import controller as c


def absolute(path):
    p = Path(path)
    c.require(p.is_absolute() and p.resolve() == p, "需要无 symlink 的绝对路径")
    return p


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write(path, value):
    with open(path, "x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def dispatch(path):
    p = absolute(path)
    d = c.read(p)
    c.require(d["role"] in ("executor", "implementer", "fixer", "finalizer") and d["dispatch_path"] == str(p), "需要 executor 或 fixer dispatch")
    c.require(not d.get("ticket_execution_version") or d["role"] == "implementer", "单票验证采集仅由 implementer 执行")
    c.require(Path(d["report_path"]).parent == p.parent, "dispatch 证据目录不符")
    return d


def state(d):
    c.topology(d)
    return {"head": c.sha(d["worktree"], "HEAD"), "status": c.status(d["worktree"])}


def group_exists(pid):
    try:
        os.killpg(pid, 0)
        return True
    except ProcessLookupError:
        return False


def send(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def stop(process):
    """只处理本次专属进程组；外部资源及脱离该组的进程由调用者核对。"""
    send(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + 2
    while group_exists(process.pid) and time.monotonic() < deadline:
        process.poll()
        time.sleep(0.05)
    if group_exists(process.pid):
        send(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        return False
    return not group_exists(process.pid)


def tail(path):
    with Path(path).open("rb") as stream:
        stream.seek(max(0, Path(path).stat().st_size - 2048))
        return "\n".join(stream.read().decode("utf-8", errors="replace").splitlines()[-20:])


def run(args):
    c.require(os.name == "posix", "此执行入口需要 POSIX 进程组")
    os.umask(0o077)
    source = absolute(args.dispatch)
    d = dispatch(source)
    before = state(d)
    if d.get("ticket_execution_version"):
        import ticket_execution
        ticket_execution.require_writer(d)
    if d.get('finalization_version') == 2:
        import final_state
        import finalization
        if d['role'] == 'fixer':
            finalization.require_writer(d)
        else:
            _, selected = final_state.selected(d)
            c.require(not selected['round_path'], 'review 已开始，验证候选冻结')
            if d['stage']:
                c.require(selected['fixes'] and c.read(c.executor_ops().bound(selected['fixes'][-1]['report']))['stopped_tasks'],
                          '补充验证前需验收 fixer 收尾')
    c.git(d["worktree"], "merge-base", "--is-ancestor", d.get("base_commit", d.get("reviewed_main")), before["head"])
    c.require(args.recipe in ("typecheck", "test", "final") or re.fullmatch(r"gate-[A-Za-z0-9_-]+", args.recipe),
              "仅执行 typecheck、test、final、gate-*")
    executable = shutil.which("just")
    c.require(executable is not None, "未找到 just")
    c.require(args.recipe in c.run([executable, "--summary"], d["worktree"]).split(), "验证 recipe 不存在")
    parameters = args.parameters[1:] if args.parameters[:1] == ["--"] else args.parameters
    argv = ["just", "--one", "--", args.recipe, *parameters]
    attempt = None
    if args.delivery:
        import gate_repair
        if d['role'] == 'finalizer':
            c.require(d.get('finalization_version') == 2 and not before['status'], '最终验证需要当前阶段干净 HEAD')
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
    interrupted = []
    handlers = {}
    process = None
    after = None
    error = None
    outcome = "recorder_error"
    stopped = True
    code = None
    log = directory / "output.log"
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, lambda value, frame: interrupted.append(value))
        with log.open("xb") as output:
            process = subprocess.Popen(argv, executable=executable, cwd=d["worktree"], stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None and not interrupted:
                time.sleep(0.05)
            if interrupted:
                stopped = stop(process)
                outcome = "interrupted"
            elif group_exists(process.pid):
                stopped = stop(process)
                outcome = "recorder_error"
                error = "主命令退出后仍有同组进程，已尝试收尾；需核对日志与资源"
            else:
                outcome = "exited" if process.returncode >= 0 else "interrupted"
            code = process.returncode
        after = state(d)
        if before != after and outcome == "exited":
            outcome = "state_changed"
    except Exception as exc:
        error = str(exc)
        outcome = "recorder_error"
    finally:
        if process is not None and (process.poll() is None or group_exists(process.pid)):
            stopped = stop(process)
            code = process.returncode
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    result = {"started_sha256": digest(directory / "started.json"), "ended_ns": time.time_ns(),
              "duration_seconds": round(time.monotonic() - began, 3), "outcome": outcome,
              "exit_code": code, "cancel_signal": interrupted[0] if interrupted else None,
              "process_group_gone": stopped, "after": after, "error": error,
              "log_sha256": digest(log), "log_bytes": log.stat().st_size}
    # 部分文件永远不能被当作完整终态；SIGKILL 时保留 started/log。
    pending = directory / "result.pending"
    write(pending, result)
    pending.rename(directory / "result.json")
    summary = {"run_path": str(directory), "command": shlex.join(argv),
               "outcome": outcome, "exit_code": code, "duration_seconds": result["duration_seconds"],
               "head": before["head"], "dirty": bool(before["status"]),
               "log_path": str(log), "log_tail": tail(log), "error": error}
    print(json.dumps(summary, ensure_ascii=False))
    return (0 if code == 0 else 1) if outcome == "exited" else (3 if outcome == "interrupted" else 2)


def collect(current_path, prior_paths, notes, report_status, snapshots=None):
    """自动保留本次及显式恢复来源中的全部记录；不推导验证覆盖或 DONE。"""
    current = dispatch(current_path)
    selected = None
    if snapshots is not None:
        c.require(isinstance(snapshots, list), "验证快照必须为列表")
        selected = {}
        for item in snapshots:
            c.require(set(item) == {"started", "result"}, "验证快照字段不符")
            start = absolute(item["started"]["path"])
            c.require(start.name == "started.json" and digest(start) == item["started"]["sha256"], "验证快照来源已变化")
            key = str(start.parent)
            c.require(key not in selected, "验证快照重复")
            selected[key] = item
    keys = ("role", "repository_root", "worktree", "branch", "parent_id", "ticket_id", "base_commit", "attempt_id")
    rows = []
    found = set()
    sources = [absolute(current_path), *(absolute(p) for p in prior_paths)]
    c.require(len(set(sources)) == len(sources), "verification dispatch 不得重复")
    c.require(isinstance(notes, dict) and all(isinstance(k, str) and isinstance(v, str) and v.strip()
                                             for k, v in notes.items()), "verification_notes 必须为路径到说明的映射")
    for source in sources:
        previous = dispatch(source)
        c.require(all(current.get(k) == previous.get(k) for k in keys), "验证记录属于其他 ticket 或 BASE")
        for directory in sorted(source.parent.glob("verification-*")):
            absolute(directory)
            c.require(directory.is_dir(), "验证证据必须是目录")
            run_path = str(directory)
            if selected is not None and run_path not in selected:
                continue
            found.add(run_path)
            start_path = absolute(directory / "started.json")
            start = c.read(start_path)
            c.require(start["dispatch_path"] == str(source) and start["dispatch_sha256"] == digest(source),
                      "验证 dispatch 身份或内容已变化")
            c.require(start["cwd"] == current["worktree"], "验证 cwd 不符")
            text = "未完成记录；退出结果未知，需确认旧任务已结束"
            end_path = absolute(directory / "result.json")
            has_result = end_path.exists() if selected is None else selected[run_path]["result"] is not None
            if has_result:
                if selected is not None:
                    entry = selected[run_path]["result"]
                    c.require(entry["path"] == str(end_path) and digest(end_path) == entry["sha256"], "验证快照结果已变化")
                result = c.read(end_path)
                log = absolute(directory / "output.log")
                c.require(result["started_sha256"] == digest(start_path)
                          and result["log_sha256"] == digest(log)
                          and result["log_bytes"] == log.stat().st_size, "验证记录或日志已变化")
                text = (f"outcome={result['outcome']}；exit_code={result['exit_code']}；"
                        f"耗时={result['duration_seconds']}s；result_sha256={digest(end_path)}")
            elif report_status == "DONE":
                c.require(run_path in notes, "未完成验证需在 verification_notes 说明收尾确认及后续验证")
            text += (f"；运行 HEAD={start['before']['head']}；"
                     f"有未提交修改={bool(start['before']['status'])}；证据={directory}")
            if run_path in notes:
                text += "；执行者说明：" + notes[run_path]
            rows.append((start["started_ns"], run_path, {"command": shlex.join(start["argv"]), "result": text}))
    c.require(selected is None or set(selected) == found, "验证快照不属于当前来源")
    c.require(set(notes).issubset(found), "verification_notes 引用了未收集的运行目录")
    return [row[2] for row in sorted(rows, key=lambda row: (row[0], row[1]))]


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

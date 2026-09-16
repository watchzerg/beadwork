"""在专属 POSIX 进程组运行命令并保存完整合并日志。"""
from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import time


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


def run(argv, cwd, log_path, *, executable=None):
    if os.name != "posix":
        raise ValueError("此执行入口需要 POSIX 进程组")
    interrupted, handlers = [], {}
    process = None
    stopped = True
    code = None
    error = None
    outcome = "recorder_error"
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, lambda value, frame: interrupted.append(value))
        with Path(log_path).open("xb") as output:
            process = subprocess.Popen(argv, executable=executable, cwd=cwd, stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
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
    except Exception as exc:
        error = str(exc)
        outcome = "recorder_error"
    finally:
        if process is not None and (process.poll() is None or group_exists(process.pid)):
            stopped = stop(process)
            code = process.returncode
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    return {"outcome": outcome, "exit_code": code,
            "cancel_signal": interrupted[0] if interrupted else None,
            "process_group_gone": stopped, "error": error}

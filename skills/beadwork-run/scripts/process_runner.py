"""在专属 POSIX 进程组运行命令；合并保存 stdout 与 stderr。"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import time
from pathlib import Path

LOG_PART_BYTES = 1024 * 1024


class BoundedLog:
    """小日志完整保留；大日志仅保存首尾，内存和落盘大小均有界。"""

    def __init__(self, output):
        self.output = output
        self.output_bytes = 0
        self.tail = bytearray()

    def write(self, chunk):
        prefix = min(len(chunk), max(0, LOG_PART_BYTES - self.output_bytes))
        self.output.write(chunk[:prefix])
        self.output_bytes += len(chunk)
        if prefix and self.output_bytes >= LOG_PART_BYTES:
            self.output.flush()
        self.tail.extend(chunk[prefix:])
        if len(self.tail) > LOG_PART_BYTES:
            del self.tail[:-LOG_PART_BYTES]

    @property
    def truncated(self):
        return self.output_bytes > 2 * LOG_PART_BYTES

    def finish(self):
        if self.truncated:
            omitted = self.output_bytes - 2 * LOG_PART_BYTES
            self.output.write(f"\n[beadwork: 已省略中间 {omitted} 字节输出]\n".encode())
        self.output.write(self.tail)


def read_output(stream, capture, timeout):
    """每次最多读取一个块；返回 EOF，避免持续输出饿死信号与进程检查。"""
    if not select.select([stream], [], [], timeout)[0]:
        return False
    chunk = os.read(stream.fileno(), 64 * 1024)
    capture.write(chunk)
    return not chunk


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


def stop(process, drain=None):
    send(process.pid, signal.SIGTERM)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and (process.poll() is None or group_exists(process.pid)):
        if drain is None:
            time.sleep(0.05)
        else:
            drain()
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
    capture = None
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, lambda value, frame: interrupted.append(value))
        with Path(log_path).open("xb") as output:
            capture = BoundedLog(output)
            process = subprocess.Popen(
                argv,
                executable=executable,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                start_new_session=True,
            )
            assert process.stdout is not None
            with process.stdout as stream:
                eof = False

                def drain():
                    nonlocal eof
                    if eof:
                        time.sleep(0.05)
                    else:
                        eof = read_output(stream, capture, 0.05)

                try:
                    while process.poll() is None and not interrupted:
                        drain()
                    if interrupted:
                        stopped = stop(process, drain)
                        outcome = "interrupted"
                    elif group_exists(process.pid):
                        stopped = stop(process, drain)
                        outcome = "recorder_error"
                        error = "主命令退出后仍有同组进程，已尝试收尾；需核对日志与资源"
                    else:
                        outcome = "exited" if process.returncode >= 0 else "interrupted"
                    code = process.returncode
                    # 排空退出前的管道内容；脱离进程组的后代不能无限占住记录器。
                    deadline = time.monotonic() + 1
                    while not eof and time.monotonic() < deadline:
                        eof = read_output(stream, capture, 0.05)
                    if not eof:
                        outcome = "recorder_error"
                        error = "命令收尾后输出管道仍未关闭，日志可能不完整；需核对外部进程"
                finally:
                    capture.finish()
    except Exception as exc:
        error = str(exc)
        outcome = "recorder_error"
    finally:
        if process is not None and (process.poll() is None or group_exists(process.pid)):
            stopped = stop(process)
            code = process.returncode
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    return {
        "outcome": outcome,
        "exit_code": code,
        "cancel_signal": interrupted[0] if interrupted else None,
        "process_group_gone": stopped,
        "error": error,
        "output_bytes": capture.output_bytes if capture else 0,
        "log_truncated": capture.truncated if capture else False,
    }

"""真实进程输出的容量边界、退出结果与取消收尾。"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import process_runner

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("exit_code", [0, 7])
def test_large_output_keeps_head_tail_and_real_exit(tmp_path, exit_code):
    log = tmp_path / "output.log"
    part = process_runner.LOG_PART_BYTES
    result = process_runner.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            f"sys.stdout.buffer.write(b'H' * {part}); sys.stdout.flush(); "
            f"sys.stderr.buffer.write(b'M' * {part * 8}); sys.stderr.flush(); "
            f"sys.stdout.buffer.write(b'T' * {part}); sys.stdout.flush(); "
            f"sys.exit({exit_code})",
        ],
        tmp_path,
        log,
    )
    raw = log.read_bytes()
    assert result["outcome"] == "exited"
    assert result["exit_code"] == exit_code
    assert result["process_group_gone"]
    assert result["output_bytes"] == 10 * part
    assert result["log_truncated"]
    assert raw.startswith(b"H" * part)
    assert raw.endswith(b"T" * part)
    assert raw[part:-part] == f"\n[beadwork: 已省略中间 {8 * part} 字节输出]\n".encode()


@pytest.mark.parametrize("size", [31, 2 * process_runner.LOG_PART_BYTES])
def test_untruncated_output_preserves_bytes(tmp_path, size):
    log = tmp_path / "output.log"
    result = process_runner.run(
        [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(b'\\xff' * {size})"],
        tmp_path,
        log,
    )
    assert result["exit_code"] == 0
    assert result["output_bytes"] == size
    assert not result["log_truncated"]
    assert log.read_bytes() == b"\xff" * size


def test_closed_output_still_waits_for_exit(tmp_path):
    result = process_runner.run(
        [
            sys.executable,
            "-c",
            "import os,time; os.close(1); os.close(2); time.sleep(.1); os._exit(7)",
        ],
        tmp_path,
        tmp_path / "output.log",
    )
    assert result["outcome"] == "exited"
    assert result["exit_code"] == 7


def test_detached_pipe_holder_cannot_keep_recorder_running(tmp_path):
    pid_path = tmp_path / "detached.pid"
    child = (
        "import subprocess,sys\n"
        "from pathlib import Path\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        "start_new_session=True)\n"
        f"Path({str(pid_path)!r}).write_text(str(p.pid))\n"
    )
    try:
        began = time.monotonic()
        result = process_runner.run(
            [sys.executable, "-c", child], tmp_path, tmp_path / "output.log"
        )
        assert time.monotonic() - began < 10
        assert result["outcome"] == "recorder_error"
        assert result["exit_code"] == 0
        assert result["process_group_gone"]
        assert "输出管道仍未关闭" in result["error"]
    finally:
        if pid_path.exists():
            try:
                os.killpg(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("graceful", [False, True])
def test_cancel_continuous_output_stops_group_and_preserves_bounded_log(tmp_path, graceful):
    log = tmp_path / "output.log"
    pid_path = tmp_path / "child.pid"
    child = (
        "import os,signal,sys\n"
        "from pathlib import Path\n"
        "def on_term(sig, frame):\n"
        "    sys.stdout.buffer.write(b'y' * (3 * 1024 * 1024) + b'STOPPED\\n')\n"
        "    sys.stdout.flush()\n"
        "    sys.exit(0)\n"
        f"signal.signal(signal.SIGTERM, {'on_term' if graceful else 'signal.SIG_IGN'})\n"
        f"Path({str(pid_path)!r}).write_text(str(os.getpid()))\n"
        "while True: os.write(1, b'x' * 65536)\n"
    )
    wrapper = (
        "import json,sys\n"
        f"sys.path.insert(0, {str(Path(process_runner.__file__).parent)!r})\n"
        "import process_runner\n"
        f"print(json.dumps(process_runner.run({[sys.executable, '-c', child]!r}, "
        f"{str(tmp_path)!r}, {str(log)!r})), flush=True)\n"
    )
    recorder = subprocess.Popen(
        [sys.executable, "-B", "-c", wrapper], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        deadline = time.monotonic() + 10
        while not log.exists() or log.stat().st_size < process_runner.LOG_PART_BYTES:
            assert recorder.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.01)
        recorder.send_signal(signal.SIGTERM)
        stdout, stderr = recorder.communicate(timeout=10)
        assert recorder.returncode == 0, stderr
        result = json.loads(stdout)
        assert result["outcome"] == "interrupted", json.dumps(result)
        assert result["cancel_signal"] == signal.SIGTERM
        assert result["exit_code"] == (0 if graceful else -signal.SIGKILL)
        assert result["process_group_gone"]
        assert log.stat().st_size <= 2 * process_runner.LOG_PART_BYTES + 100
        if graceful:
            assert log.read_bytes().endswith(b"STOPPED\n")
            assert result["log_truncated"]
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid_path.read_text()), 0)
    finally:
        if recorder.poll() is None:
            recorder.kill()
            recorder.communicate(timeout=5)
        if pid_path.exists():
            try:
                os.killpg(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass

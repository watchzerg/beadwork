"""批次命令的 started/result/log 证据；不决定流程、重试或成功状态。"""

import uuid
from pathlib import Path

import evidence
import process_runner
import repository


def run(folder, name, argv, cwd, context=None, *, capture_stdout=False):
    directory = Path(folder) / (name + "-" + uuid.uuid4().hex)
    directory.mkdir()
    started = {"argv": list(map(str, argv)), "cwd": str(cwd), "context": context}
    evidence.write(directory / "started.json", started)
    stdout = directory / "stdout.log" if capture_stdout else None
    result = process_runner.run(
        started["argv"], str(cwd), directory / "output.log", stdout_path=stdout
    )
    result.update(
        started=evidence.binding(directory / "started.json"),
        log=evidence.binding(directory / "output.log"),
    )
    if stdout is not None:
        result["stdout"] = evidence.binding(stdout)
    evidence.write(directory / "result.json", result)
    return evidence.binding(directory / "result.json")


def read(source):
    path = evidence.bound(source)
    value = evidence.read(path)
    repository.require(
        Path(value["started"]["path"]).parent == path.parent
        and Path(value["log"]["path"]).parent == path.parent,
        "命令证据目录不符",
    )
    started = evidence.read(evidence.bound(value["started"]))
    log = evidence.bound(value["log"])
    if "stdout" in value:
        repository.require(
            Path(value["stdout"]["path"]) == path.parent / "stdout.log",
            "命令 stdout 证据目录不符",
        )
        evidence.bound(value["stdout"])
    return value, started, log


def stdout(source):
    value, _, _ = read(source)
    repository.require("stdout" in value, "命令缺少独立 stdout 来源")
    return evidence.bound(value["stdout"]).read_text()


def succeeded(value):
    return value["outcome"] == "exited" and value["exit_code"] == 0 and value["process_group_gone"]


def require_success(source):
    value, started, log = read(source)
    repository.require(succeeded(value), "命令失败或中断，证据：" + source["path"])
    return started, log

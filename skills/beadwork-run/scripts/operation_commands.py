"""批次命令的 started/result/log 证据；不决定流程、重试或成功状态。"""

import uuid
from pathlib import Path

import evidence
import process_runner
import repository


def run(folder, name, argv, cwd, context=None):
    directory = Path(folder) / (name + "-" + uuid.uuid4().hex)
    directory.mkdir()
    started = {"argv": list(map(str, argv)), "cwd": str(cwd), "context": context}
    evidence.write(directory / "started.json", started)
    result = process_runner.run(started["argv"], str(cwd), directory / "output.log")
    result.update(
        started=evidence.binding(directory / "started.json"),
        log=evidence.binding(directory / "output.log"),
    )
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
    return value, started, log


def succeeded(value):
    return value["outcome"] == "exited" and value["exit_code"] == 0 and value["process_group_gone"]


def require_success(source):
    value, started, log = read(source)
    repository.require(succeeded(value), "命令失败或中断，证据：" + source["path"])
    return started, log

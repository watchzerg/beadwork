"""运行来源的固定快照与内容绑定；覆盖策略由 ticket/final 调用方决定。"""
from pathlib import Path

import evidence


def snapshot(dispatch_path):
    rows = []
    for folder in sorted(Path(dispatch_path).parent.glob("verification-*")):
        rows.append({"started": evidence.binding(folder / "started.json"),
                     "result": evidence.binding(folder / "result.json")
                     if (folder / "result.json").exists() else None})
    return rows


def read(item):
    if not isinstance(item, dict) or set(item) != {"started", "result"}:
        raise ValueError("验证来源字段不符")
    started_path = evidence.bound(item["started"])
    if started_path.name != "started.json" or not started_path.parent.name.startswith("verification-"):
        raise ValueError("验证路径无效")
    started = evidence.read(started_path)
    result_path = None
    result = None
    log = started_path.parent / "output.log"
    if item["result"] is not None:
        result_path = evidence.bound(item["result"])
        if result_path != started_path.parent / "result.json":
            raise ValueError("验证 result 路径不符")
        result = evidence.read(result_path)
        if (result["started_sha256"] != evidence.digest(started_path)
                or result["log_sha256"] != evidence.digest(log)
                or result["log_bytes"] != log.stat().st_size):
            raise ValueError("验证记录或日志已变化")
    return started_path, started, result_path, result, log

"""运行来源的固定快照与内容绑定；覆盖策略由 ticket/final 调用方决定。"""

from pathlib import Path

import evidence


def snapshot(dispatch_path):
    rows = []
    for folder in sorted(Path(dispatch_path).parent.glob("verification-*")):
        evidence.absolute(folder)
        rows.append(
            {
                "directory": str(folder),
                "started": evidence.binding(folder / "started.json")
                if (folder / "started.json").exists()
                else None,
                "result": evidence.binding(folder / "result.json")
                if (folder / "result.json").exists()
                else None,
            }
        )
    return rows


def directory(item):
    if not isinstance(item, dict) or set(item) != {"directory", "started", "result"}:
        raise ValueError("验证来源字段不符")
    folder = evidence.absolute(item["directory"])
    if not folder.name.startswith("verification-"):
        raise ValueError("验证路径无效")
    for name in ("started", "result"):
        binding = item[name]
        if binding is not None and (
            not isinstance(binding, dict)
            or set(binding) != {"path", "sha256"}
            or binding["path"] != str(folder / (name + ".json"))
        ):
            raise ValueError("验证文件不属于运行目录")
    return folder


def read(item):
    folder = directory(item)
    if item["started"] is None:
        if (folder / "started.json").exists():
            raise ValueError("缺失的 started 记录已变化，需重新采集")
        raise ValueError("验证来源缺少 started.json：" + str(folder))
    started_path = evidence.bound(item["started"])
    started = evidence.read(started_path)
    if not isinstance(started, dict) or type(started.get("started_ns")) is not int:
        raise ValueError("验证 started 记录缺少有效时间")
    result_path = None
    result = None
    log = started_path.parent / "output.log"
    if item["result"] is not None:
        result_path = evidence.bound(item["result"])
        if result_path != started_path.parent / "result.json":
            raise ValueError("验证 result 路径不符")
        result = evidence.read(result_path)
        if (
            result["started_sha256"] != evidence.digest(started_path)
            or result["log_sha256"] != evidence.digest(log)
            or result["log_bytes"] != log.stat().st_size
        ):
            raise ValueError("验证记录或日志已变化")
    return started_path, started, result_path, result, log

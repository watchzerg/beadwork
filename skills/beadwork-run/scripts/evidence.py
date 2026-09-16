"""证据文件的严格 JSON 读取；只使用标准库。"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import uuid


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复 JSON key：" + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("无效 JSON 数值：" + value)


def loads(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_invalid_constant)


def read(path):
    return loads(Path(path).read_bytes())


def read_with_digest(path):
    raw = Path(path).read_bytes()
    return loads(raw), hashlib.sha256(raw).hexdigest()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def absolute(path):
    value = Path(path)
    if not value.is_absolute() or value.resolve() != value:
        raise ValueError("需要无 symlink 的绝对路径")
    return value


def binding(path):
    value = absolute(path)
    return {"path": str(value), "sha256": digest(value)}


def bound(item):
    if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
        raise ValueError("证据绑定必须只含 path/sha256")
    value = absolute(item["path"])
    if digest(value) != item["sha256"]:
        raise ValueError("证据文件已变化：" + str(value))
    return value


def write(path, value):
    """同目录完整写入后独占发布；失败不留下半个正式文件。"""
    target = Path(path)
    data = (value if isinstance(value, str)
            else json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    pending = target.parent / ("." + target.name + ".pending-" + uuid.uuid4().hex)
    try:
        with pending.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(pending, target)
    except FileExistsError as error:
        raise FileExistsError("证据文件已存在：" + str(target)) from error
    finally:
        try:
            pending.unlink()
        except FileNotFoundError:
            pass

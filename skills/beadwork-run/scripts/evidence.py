"""证据文件的严格 JSON 读取；只使用标准库。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


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

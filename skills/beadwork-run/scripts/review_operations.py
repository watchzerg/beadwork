"""ticket 与 final review 共用的 append-only 文件和双轴输入机制。"""
from pathlib import Path

import evidence

AXES = ("standards", "spec")


def publish_or_match(path, value):
    path = Path(path)
    if path.exists():
        if evidence.read(path) != value:
            raise ValueError("review 准备半成品与当前身份不符")
    else:
        evidence.write(path, value)


def require_axis_sources(sources):
    if not isinstance(sources, dict) or set(sources) != set(AXES):
        raise ValueError("必须明确提供两个轴的报告与回执")
    for axis in AXES:
        if set(sources[axis]) not in ({"report", "receipt"}, {"report", "receipt", "closure"}):
            raise ValueError("每轴需要 report/receipt 及可选 closure")

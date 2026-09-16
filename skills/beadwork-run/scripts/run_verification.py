"""可普通 import 的验证来源解析接口。"""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

_spec = spec_from_file_location("_run_verification_cli", Path(__file__).with_name("run-verification.py"))
if _spec is None or _spec.loader is None:
    raise RuntimeError("无法加载 run-verification.py")
_module = module_from_spec(_spec)
_spec.loader.exec_module(_module)

collect = _module.collect

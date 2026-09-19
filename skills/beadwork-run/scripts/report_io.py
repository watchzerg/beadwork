"""报告 schema 与校验服务；内部调用不启动 verifier 子进程。"""

import json
import os
from pathlib import Path

import evidence
import phase_validation
import verify_ticket
import worker_validation
from repository import require


def _executor(option, *args):
    if option == "--schema":
        result = verify_ticket.executor_schema(verify_ticket.axis_report_schema())
        verify_ticket.check_schema(result)
        return result
    if option == "--receipt-schema":
        return verify_ticket.RECEIPT
    require(option == "--check-report" and 1 <= len(args) <= 2, "executor verifier 参数无效")
    report_path = args[0]
    report, digest = verify_ticket.read_json(report_path)
    schema = verify_ticket.executor_schema(verify_ticket.axis_report_schema())
    failures = verify_ticket.report_errors(report, schema)
    if len(args) == 2:
        receipt, _ = verify_ticket.read_json(args[1])
        problems = verify_ticket.schema_errors(receipt, verify_ticket.RECEIPT)
        if problems:
            failures.append({"check": "receipt_schema", "observed": problems})
        else:
            wanted = {
                "status": report.get("status"),
                "report_path": os.path.abspath(report_path),
                "report_sha256": digest,
            }
            failures.extend(
                {"check": "receipt_" + key + "_matches"}
                for key, value in wanted.items()
                if receipt[key] != value
            )
    return {
        "ok": not failures,
        "report_sha256": digest,
        **({"failures": failures} if failures else {}),
    }


def verifier(role, option, *args):
    """调用 executor 或 phase 校验服务。"""
    if role == "executor":
        result = _executor(option, *args)
    else:
        if option == "--schema":
            result = phase_validation.schema(role)
        elif option == "--receipt-schema":
            result = phase_validation.schema(role, receipt=True)
        else:
            require(option == "--check-report", "phase verifier 参数无效")
            values = list(args)
            expected = None
            if "--expected" in values:
                index = values.index("--expected")
                require(index + 2 == len(values), "--expected 必须位于末尾")
                expected = values[index + 1]
                values = values[:index]
            require(1 <= len(values) <= 2, "phase verifier 参数无效")
            result = phase_validation.check(
                role, values[0], expected, values[1] if len(values) == 2 else None
            )
    if option == "--check-report":
        require(
            result.get("ok") is True,
            role + " 报告校验失败：" + json.dumps(result, ensure_ascii=False),
        )
    return result


def worker(role, option, *args):
    if option == "--schema":
        return worker_validation.schema(role)
    if option == "--receipt-schema":
        return worker_validation.schema(role, receipt=True)
    require(option == "--check-report", "worker verifier 参数无效")
    values = list(args)
    require("--expected" in values, "worker verifier 缺少 --expected")
    index = values.index("--expected")
    require(index + 2 == len(values) and 1 <= index <= 2, "worker verifier 参数无效")
    result = worker_validation.check(
        role, values[0], values[index + 1], values[1] if index == 2 else None
    )
    require(
        result.get("ok") is True, role + " 报告校验失败：" + json.dumps(result, ensure_ascii=False)
    )
    return result


def reviewer(option, *args):
    return worker("reviewer", option, *args)


def implementer(option, *args):
    return worker("implementer", option, *args)


def fixer(option, *args):
    return worker("fixer", option, *args)


def inspect_report(dispatch_path, report_path, receipt_path):
    d = evidence.read(dispatch_path)
    directory = Path(dispatch_path).resolve().parent
    for path in (report_path, receipt_path):
        require(Path(path).resolve().parent == directory, "报告和回执必须位于 dispatch 证据目录")
    role = d["role"]
    extra = [] if role == "executor" else ["--expected", dispatch_path]
    result = verifier(role, "--check-report", report_path, receipt_path, *extra)
    return d, evidence.read(report_path), result

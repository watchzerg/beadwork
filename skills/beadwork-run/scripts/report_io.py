"""固定 verifier CLI 的调用与报告来源读取；不作工作流成功判定。"""

from pathlib import Path
import json
import sys

from repository import require, run
import evidence

SCRIPTS = Path(__file__).resolve().parent

def verifier(role, option, *args, cwd=None):
    script = "verify-ticket.py" if role == "executor" else "verify-phase.py"
    command = [sys.executable, "-B", SCRIPTS / script, option]
    if role != "executor":
        command.append(role)
    output = json.loads(run(command + list(args), cwd))
    if option == "--check-report":
        require(output.get("ok") is True, "报告校验失败：" + json.dumps(output, ensure_ascii=False))
    return output


def load_command(args, cwd=None):
    return json.loads(run(args, cwd))


def inspect_preflight(dispatch_path, report_path, receipt_path):
    """重验 preflight 原始来源，保持 controller 的目录、schema、receipt 和 hash 检查。"""
    d = evidence.read(dispatch_path)
    require(d["role"] == "preflight", "需要 preflight dispatch")
    directory = Path(dispatch_path).resolve().parent
    for path in (report_path, receipt_path):
        require(Path(path).resolve().parent == directory, "报告和回执必须位于 dispatch 证据目录")
    result = verifier("preflight", "--check-report", report_path, receipt_path, "--expected", dispatch_path)
    report = evidence.read(report_path)
    require(evidence.digest(report_path) == result["report_sha256"], "验收期间报告发生变化")
    return d, report, result


def reviewer(option, *args):
    result = load_command([sys.executable, "-B", SCRIPTS / "verify-worker.py", option, "reviewer", *args])
    if option == "--check-report":
        require(result.get("ok") is True, "reviewer 验收失败：" + json.dumps(result, ensure_ascii=False))
    return result


def implementer(option, *args):
    result = json.loads(run([sys.executable, '-B', SCRIPTS / 'verify-worker.py', option, 'implementer', *args]))
    if option == '--check-report':
        require(result.get('ok'), 'implementer 报告校验失败：' + json.dumps(result, ensure_ascii=False))
    return result


def inspect_report(dispatch_path, report_path, receipt_path):
    """读取固定角色报告并检查同目录及 schema/receipt；调用者继续重验业务事实。"""
    d = evidence.read(dispatch_path)
    directory = Path(dispatch_path).resolve().parent
    for path in (report_path, receipt_path):
        require(Path(path).resolve().parent == directory, "报告和回执必须位于 dispatch 证据目录")
    role = d['role']
    extra = [] if role == 'executor' else ['--expected', dispatch_path]
    result = verifier(role, '--check-report', report_path, receipt_path, *extra)
    return d, evidence.read(report_path), result

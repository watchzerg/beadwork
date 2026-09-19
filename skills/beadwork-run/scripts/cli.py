"""统一 argparse 路由、JSON 输出和错误边界。"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

import batch_evidence
import batch_initialize
import controller
import executor_operations
import graph
import phase_validation
import plan_operations
import preflight_operations
import run_verification
import tracker_operations
import verify_ticket
import worker_validation

Handler = Callable[[argparse.Namespace], Any]


class _FirstChoicePair(argparse.Action):
    """校验二元参数的首项，同时保留现有 CLI 参数形状。"""

    def __init__(self, *args, first_choices: tuple[str, ...], **kwargs):
        self.first_choices = first_choices
        super().__init__(*args, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        if values[0] not in self.first_choices:
            parser.error(
                f"argument {option_string}: invalid choice: {values[0]!r} "
                f"(choose from {', '.join(map(repr, self.first_choices))})"
            )
        setattr(namespace, self.dest, values)


def _leaf(subparsers, name: str, handler: Handler, help_text: str = ""):
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(_handler=handler)
    return parser


def _required(parser, *names: str) -> None:
    for name in names:
        parser.add_argument("--" + name, required=True)


def _controller(subparsers) -> None:
    parser = subparsers.add_parser("controller", help="controller 确定性操作")
    commands = parser.add_subparsers(dest="command", required=True)
    p = _leaf(commands, "prepare", controller.execute)
    p.add_argument("role", choices=("preflight", "executor", "finalizer"))
    _required(p, "input")
    p = _leaf(commands, "update-main", controller.execute)
    _required(p, "repository-root")
    for name in ("sync-main", "sync-final"):
        p = _leaf(commands, name, controller.execute)
        _required(p, "input")
    p = _leaf(commands, "adapt-plan", controller.execute)
    _required(p, "dispatch", "input")
    p = _leaf(commands, "accept", controller.execute)
    _required(p, "dispatch", "report", "receipt", "output")
    p.add_argument("--closure")
    p = _leaf(commands, "comment", controller.execute)
    _required(p, "acceptance", "summary", "output")
    p.add_argument("--evidence", action="append", default=[])
    p = _leaf(commands, "merge", controller.execute)
    _required(p, "acceptance", "comment-id", "output")
    p = _leaf(commands, "cleanup", controller.execute)
    _required(p, "merge-record")


def _executor(subparsers) -> None:
    parser = subparsers.add_parser("executor", help="executor 与 worker 操作")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("context-add", "ticket-stage", "ticket-adapt-plan", "final-gates", "final-stage"):
        p = _leaf(commands, name, executor_operations.execute)
        _required(p, "dispatch", "input")
    p = _leaf(commands, "handoff-close", executor_operations.execute)
    _required(p, "dispatch", "report", "input")
    for name in ("ticket-deliver", "final-deliver"):
        p = _leaf(commands, name, executor_operations.execute)
        _required(p, "dispatch", "output")
    for name in (
        "ticket-assemble",
        "implementer-assemble",
        "fixer-assemble",
        "final-assemble",
    ):
        p = _leaf(commands, name, executor_operations.execute)
        _required(p, "dispatch", "draft", "output")
    for name in ("implementer-check", "fixer-check", "check"):
        p = _leaf(commands, name, executor_operations.execute)
        _required(p, "dispatch", "report")
    for name in ("implementer-accept", "fixer-accept"):
        p = _leaf(commands, name, executor_operations.execute)
        _required(p, "dispatch", "report", "receipt")
        p.add_argument("--closure")
    p = _leaf(commands, "begin-gate-repair", executor_operations.execute)
    _required(p, "dispatch", "failure")
    p = _leaf(commands, "inspect", executor_operations.execute)
    _required(p, "dispatch")
    p = _leaf(commands, "check-layer", executor_operations.execute)
    _required(p, "dispatch", "input")
    p = _leaf(commands, "review-prepare", executor_operations.execute)
    _required(p, "dispatch")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--evidence")
    p = _leaf(commands, "review-collect", executor_operations.execute)
    _required(p, "round", "input", "output")
    p = _leaf(commands, "assemble", executor_operations.execute)
    _required(p, "dispatch", "draft", "output")
    p.add_argument("--review", action="append", default=[])
    p.add_argument("--verification-dispatch", action="append", default=[])


def _preflight(subparsers) -> None:
    parser = subparsers.add_parser("preflight", help="preflight 事实采集与报告组装")
    commands = parser.add_subparsers(dest="command", required=True)
    p = _leaf(commands, "collect", preflight_operations.execute)
    _required(p, "dispatch")
    p = _leaf(commands, "assemble", preflight_operations.execute)
    _required(p, "dispatch", "facts-sha256", "draft", "output")


def _plan(subparsers) -> None:
    parser = subparsers.add_parser("plan", help="串行执行计划操作")
    commands = parser.add_subparsers(dest="command", required=True)
    p = _leaf(commands, "prepare", plan_operations.execute)
    _required(p, "input", "output")
    p = _leaf(commands, "publish", plan_operations.execute)
    _required(p, "intent")
    p = _leaf(commands, "adopt", plan_operations.execute)
    _required(p, "input")
    p = _leaf(commands, "inspect", plan_operations.execute)
    _required(p, "repository-root", "parent")


def _graph(subparsers) -> None:
    parser = subparsers.add_parser("graph", help="只读 Beads 图查询")
    commands = parser.add_subparsers(dest="command", required=True)
    p = _leaf(commands, "check-flat", graph.execute)
    p.add_argument("parent_id")
    p = _leaf(commands, "next", graph.execute)
    p.add_argument("parent_id")
    p.add_argument("expected_child_id", nargs="+")


def _run_verification(subparsers) -> None:
    p = _leaf(subparsers, "run-verification", run_verification.execute, "采集一个 just 验证运行")
    _required(p, "dispatch", "recipe")
    p.add_argument("--delivery", action="store_true")
    p.add_argument("parameters", nargs=argparse.REMAINDER)


def _verify_ticket(args):
    selected = bool(args.schema) + bool(args.receipt_schema) + bool(args.check_report)
    if selected > 1 or ((args.schema or args.receipt_schema) and args.delivery):
        raise ValueError("ticket verifier 的 schema、报告检查与 delivery 参数不能混用")
    if args.emit_receipt and not args.check_report:
        raise ValueError("--emit-receipt 仅用于报告自检")
    if args.check_report:
        if len(args.delivery) > 1:
            raise ValueError("receipt 参数过多")
        args.receipt = args.delivery[0] if args.delivery else None
        args.delivery = []
    else:
        args.receipt = None
    return verify_ticket.execute(args)


def _verify_phase(args):
    selected = bool(args.schema) + bool(args.receipt_schema) + bool(args.check_report)
    if selected != 1:
        raise ValueError("phase verifier 必须选择一个操作")
    if args.emit_receipt and not args.check_report:
        raise ValueError("--emit-receipt 仅用于报告自检")
    if args.check_report:
        args.phase, args.check_report = args.check_report
    return phase_validation.execute(args)


def _verify_worker(args):
    selected = bool(args.schema) + bool(args.receipt_schema) + bool(args.check_report)
    if selected != 1:
        raise ValueError("worker verifier 必须选择一个操作")
    if args.emit_receipt and not args.check_report:
        raise ValueError("--emit-receipt 仅用于报告自检")
    if args.check_report:
        args.role, args.check_report = args.check_report
        if not args.expected:
            raise ValueError("worker 报告检查需要 --expected")
    return worker_validation.execute(args)


def _verify(subparsers) -> None:
    parser = subparsers.add_parser("verify", help="报告与交付校验")
    kinds = parser.add_subparsers(dest="verify_kind", required=True)
    p = _leaf(kinds, "ticket", _verify_ticket)
    p.add_argument("--schema", action="store_true")
    p.add_argument("--receipt-schema", action="store_true")
    p.add_argument("--check-report")
    p.add_argument("--emit-receipt", action="store_true")
    p.add_argument("delivery", nargs="*")
    p = _leaf(kinds, "phase", _verify_phase)
    p.add_argument("--schema", choices=phase_validation.PHASES)
    p.add_argument("--receipt-schema", choices=phase_validation.PHASES)
    p.add_argument(
        "--check-report",
        nargs=2,
        metavar=("PHASE", "REPORT"),
        action=_FirstChoicePair,
        first_choices=phase_validation.PHASES,
    )
    p.add_argument("receipt", nargs="?")
    p.add_argument("--expected")
    p.add_argument("--emit-receipt", action="store_true")
    p = _leaf(kinds, "worker", _verify_worker)
    p.add_argument("--schema", choices=worker_validation.ROLES)
    p.add_argument("--receipt-schema", choices=worker_validation.ROLES)
    p.add_argument(
        "--check-report",
        nargs=2,
        metavar=("ROLE", "REPORT"),
        action=_FirstChoicePair,
        first_choices=worker_validation.ROLES,
    )
    p.add_argument("receipt", nargs="?")
    p.add_argument("--expected")
    p.add_argument("--emit-receipt", action="store_true")


def _tracker(subparsers) -> None:
    parser = subparsers.add_parser("tracker", help="controller 专用 tracker intent")
    commands = parser.add_subparsers(dest="command", required=True)
    p = _leaf(commands, "prepare", tracker_operations.execute_command)
    _required(p, "input", "output")
    p = _leaf(commands, "execute", tracker_operations.execute_command)
    _required(p, "intent")


def _batch_initialize(subparsers) -> None:
    parser = subparsers.add_parser("batch-initialize", help="批次初始化与恢复")
    commands = parser.add_subparsers(dest="command", required=True)
    p = _leaf(commands, "prepare", batch_initialize.execute_command)
    _required(p, "input", "output")
    p = _leaf(commands, "execute", batch_initialize.execute_command)
    _required(p, "intent")
    p.add_argument("--recovery")


def _batch_evidence(subparsers) -> None:
    parser = subparsers.add_parser("batch-evidence", help="批次事实与来源汇总")
    parser.add_argument("--output", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    p = _leaf(commands, "inspect", batch_evidence.execute)
    _required(p, "repository-root", "parent-id")
    for name in ("manifest", "summary"):
        p = _leaf(commands, name, batch_evidence.execute)
        _required(p, "input")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beadwork.py", description=__doc__)
    subparsers = parser.add_subparsers(dest="group", required=True)
    for register in (
        _controller,
        _executor,
        _preflight,
        _plan,
        _graph,
        _run_verification,
        _verify,
        _tracker,
        _batch_initialize,
        _batch_evidence,
    ):
        register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = None
    try:
        args = build_parser().parse_args(argv)
        result = args._handler(args)
        if isinstance(result, tuple):
            result, exit_code = result
        else:
            exit_code = 1 if isinstance(result, dict) and result.get("ok") is False else 0
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return exit_code
    except (ValueError, KeyError, OSError, TypeError) as error:
        recorder = args is not None and args.group == "run-verification"
        payload = (
            {"outcome": "recorder_error", "error": str(error)}
            if recorder
            else {"error": str(error)}
        )
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 2 if recorder else 1
    except Exception as error:  # noqa: BLE001 - CLI 顶层必须把操作失败转换为稳定边界
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2

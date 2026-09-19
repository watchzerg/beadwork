#!/usr/bin/env python3
"""controller 的确定性操作；用 --help 查看入口。只使用标准库。"""

from __future__ import annotations

from pathlib import Path
import argparse
import json
import re
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True

import dispatch_contract
import evidence
import draft_contracts
import execution_plan
import finalization
import handoff
import report_io
import repository
import ticket_execution
import ticket_reports
import workflow_policy


SCRIPTS = Path(__file__).resolve().parent


require = repository.require
read = evidence.read
digest = evidence.digest
write = evidence.write
run = repository.run
git = repository.git
status = repository.status
sha = repository.sha
primary = repository.primary
topology = repository.topology
verifier = report_io.verifier


# 阶段 0 为首次实现，1..5 为修复；矩阵是派发模型的单一来源。
MODEL_LEVELS = workflow_policy.MODEL_LEVELS
STAGE_MODELS = workflow_policy.STAGE_MODELS
FINAL_STAGE_MODELS = workflow_policy.FINAL_STAGE_MODELS
MODEL_ROLES = workflow_policy.MODEL_ROLES
check_stage_report_core = ticket_reports.check_stage_report_core
check_stage_report = ticket_reports.check_stage_report


def sync_main(args):
    import main_sync
    return main_sync.sync(args)


def sync_final(args):
    import main_sync
    return main_sync.sync(args, final=True)


def prepare(args):
    d = read(args.input)
    d.pop("primary_snapshot_path", None)
    fields = ["repository_root", "parent_id", "rules_paths"]
    if args.role == "executor":
        fields += ["ticket_id", "mode", "test_mode", "approved_seams", "testing_seams_doc", "linked_spec", "required_boundary_gates"]
    elif args.role == "finalizer":
        fields += ["expected_children", "linked_spec", "ticket_evidence", "required_boundary_gates", "prior_finalization", "reviewed_main"]
    require(all(k in d for k in fields), "准备输入缺少必填字段")
    root = primary(d["repository_root"])
    parent = d["parent_id"]
    require(isinstance(parent, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parent) and parent not in (".", ".."), "parent ID 无效")
    branch = "implement/" + parent
    git(root, "check-ref-format", "--branch", branch)
    git(root, "check-ignore", "-q", "--", ".worktrees/probe")
    if args.role != 'preflight':
        require(isinstance(d['linked_spec'], str) and d['linked_spec'].strip(), '需要明确 linked_spec，parent 即 spec 时填写 parent ID')
        require(isinstance(d['required_boundary_gates'], list) and all(isinstance(g, str) and g.startswith('gate-') for g in d['required_boundary_gates']), '需要显式 boundary gate 列表，允许空列表')
        d['required_boundary_gates'] = list(dict.fromkeys(
            gate for gate in d['required_boundary_gates'] if gate not in ('gate-core', 'gate-full')))
    d["execution_contract"] = 2
    d['gate_contract_version'] = 1
    d.update(repository_root=root, parent_id=parent, branch=branch,
             worktree=str(Path(root) / ".worktrees" / parent), skill_dir=str(SCRIPTS.parent), role=args.role)
    if args.role != "preflight":
        topology(d)
        head = sha(d["worktree"], "HEAD")
        if args.role == "executor":
            require(d.get("ticket_id"), "缺少 ticket_id")
            require(d.get("mode") in ("new", "resume"), "必须显式指定 mode=new 或 resume")
            if d["mode"] == "new":
                require(not status(d["worktree"]), "新 ticket 必须从干净 worktree 开始")
                import main_sync
                require(d.get("sync_result"), "新 ticket 需要 sync-main 返回的 sync_result")
                main_sync.check_result(d, d["sync_result"])
                d["base_commit"] = head
                handoff.preflight_input(d)
            else:
                require(re.fullmatch(r"[0-9a-f]{40}", d.get("base_commit", "")), "恢复必须提供 start comment 中的完整 BASE")
                sha(d["worktree"], d["base_commit"])
                git(d["worktree"], "merge-base", "--is-ancestor", d["base_commit"], head)
            if d["mode"] == "resume" and d.get("previous_dispatch"):
                previous = read(d["previous_dispatch"])
                if previous.get('ticket_execution_version'):
                    require(previous.get('gate_contract_version') == 1, '旧 gate 活动现场与当前契约不匹配；保留原 BASE、stage 和证据并停止')
                validate_plan(previous)
                if previous.get("plan_adjustment"):
                    require(d["test_mode"] == previous["test_mode"] and d["approved_seams"] == previous["approved_seams"], "恢复须沿用已调整计划；改模式使用 adapt-plan")
                    d["plan_adjustment"] = previous["plan_adjustment"]
                    d["required_boundary_gates"] = list(dict.fromkeys(previous.get("required_boundary_gates", []) + d.get("required_boundary_gates", [])))
                d["verification_dispatches"] = list(dict.fromkeys(previous.get("verification_dispatches", []) + [d["previous_dispatch"]]))
            plan = {"mode": d["test_mode"], "approved_seams": d["approved_seams"]}
            require(plan["mode"] in ("TDD", "direct_verification"), "test mode 无效")
            seams = plan["approved_seams"]
            require(isinstance(seams, list) and all(isinstance(s, str) and s for s in seams) and len(set(seams)) == len(seams), "seams 无效")
            require(plan["mode"] != "TDD" or bool(seams), "TDD 需要 approved seams")
            if d["mode"] == "resume":
                require(d.get("previous_dispatch"), "恢复需要原 executor root dispatch")
                return ticket_execution.resume_root(d)
            ticket_execution.root_fields(d)
        else:
            require(isinstance(d["reviewed_main"], str) and re.fullmatch(r"[0-9a-f]{40}", d["reviewed_main"]), "需要已合入的完整 reviewed_main SHA")
            git(d["worktree"], "merge-base", "--is-ancestor", d["reviewed_main"], head)
            d["start_head"] = head
            require("prior_finalization" in d, "必须明确 prior_finalization，首次为 null")
            if d['prior_finalization'] and d['prior_finalization'].get('stage_path'):
                previous = read(d['prior_finalization']['stage_path'])
                require(previous.get('gate_contract_version') == 1,
                        '旧 gate 活动现场与当前契约不匹配；保留原 attempt、stage 和证据并停止')
            finalization.prepare_attempt(d, head)
            if d.get('final_sync_result') and not d.get('resume_stage'):
                import main_sync
                main_sync.check_result(d, d['final_sync_result'], final=True)
                d['environment_evidence'] = list(d.get('environment_evidence', [])) + [evidence.binding(d['final_sync_result'])]
    else:
        d.update(expected_branch=branch, expected_worktree=d["worktree"])
    directory = Path(root) / ".worktrees" / ".evidence" / parent
    if args.role != "executor":
        directory /= "preflight" if args.role == "preflight" else "final-review"
    directory /= uuid.uuid4().hex
    require(directory.resolve() == directory, "证据路径不能经过 symlink")
    directory.mkdir(parents=True, exist_ok=False)
    d.update(dispatch_path=str(directory / "dispatch.json"), report_path=str(directory / "report.json"))
    if args.role == "finalizer":
        d.setdefault("attempt_id", directory.name)
        d.setdefault("attempt_path", str(directory))
    if args.role == "executor":
        d["expected_plan_path"] = str(directory / "expected-plan.json")
        write(d["expected_plan_path"], plan)
    d["report_schema_path"] = str(directory / "report-schema.json")
    d["receipt_schema_path"] = str(directory / "receipt-schema.json")
    write(d["report_schema_path"], verifier(args.role, "--schema"))
    write(d["receipt_schema_path"], verifier(args.role, "--receipt-schema"))
    if args.role == "preflight":
        d["self_check_argv"] = [sys.executable, "-B", str(SCRIPTS / "verify-phase.py"), "--check-report", "preflight", d["report_path"], "--expected", d["dispatch_path"], "--emit-receipt"]
    if args.role == 'preflight':
        draft_contracts.publish(d, 'preflight')
    write(d["dispatch_path"], d)
    return {"repository_root": root, "worktree": d["worktree"], "branch": branch,
            "dispatch_path": d["dispatch_path"], "report_path": d["report_path"],
            "report_schema_path": str(directory / "report-schema.json"), "receipt_schema_path": str(directory / "receipt-schema.json"),
            "base_commit": d.get("base_commit"), "start_head": d.get("start_head"), "reviewed_main": d.get("reviewed_main"),
            **({"coordinator_model": d["coordinator_model"]} if args.role == "executor" else {}),
            **({"draft_schema_path": d["draft_schema_path"]} if args.role == "preflight" else {})}


adapt_plan = ticket_execution.adapt_plan_dispatch
validate_plan = dispatch_contract.validate_plan
check_batch_beads = repository.check_batch_beads


def inspect(dispatch_path, report_path, receipt_path):
    d = read(dispatch_path)
    if d["role"] == "finalizer":
        return finalization.inspect_delivery(dispatch_path, report_path, receipt_path)
    directory = Path(dispatch_path).resolve().parent
    for path in (report_path, receipt_path):
        require(Path(path).resolve().parent == directory, "报告和回执必须位于 dispatch 证据目录")
    role = d["role"]
    extra = [] if role == "executor" else ["--expected", dispatch_path]
    result = verifier(role, "--check-report", report_path, receipt_path, *extra)
    r = read(report_path)
    if role == "executor":
        if d.get("ticket_execution_version"):
            require(d.get("ticket_scope") == "root", "controller 只验收整票 root")
        d_plan = check_stage_report(d, r) or d
        topology(d)
        head = r["head_commit"] or sha(d["worktree"], "HEAD")
        checked = json.loads(run([sys.executable, "-B", SCRIPTS / "verify-ticket.py", d["branch"], d["base_commit"], head, r["status"], report_path, d_plan["expected_plan_path"]], d["worktree"]))
        require(checked.get("ok") and checked["report_sha256"] == result["report_sha256"], "Git 验收失败：" + json.dumps(checked, ensure_ascii=False))
    require(digest(report_path) == result["report_sha256"], "验收期间报告发生变化")
    return d, r, result


def accept(args):
    require(Path(args.output).resolve().parent == Path(args.dispatch).resolve().parent, "验收记录必须留在 dispatch 证据目录")
    d, r, result = inspect(args.dispatch, args.report, args.receipt)
    closure = handoff.closure_binding(read(args.closure)) if getattr(args, 'closure', None) else None
    handoff.check_close(str(args.dispatch), str(args.report), closure,
                        required=d.get('finalization_version') == 2 or bool(d.get('preflight_acceptance')))
    record = {"kind": "mechanical_acceptance", "role": d["role"], "status": r["status"],
              "dispatch_path": str(Path(args.dispatch).resolve()), "dispatch_sha256": digest(args.dispatch),
              "report_path": str(Path(args.report).resolve()), "report_sha256": result["report_sha256"],
              "receipt_path": str(Path(args.receipt).resolve()), "receipt_sha256": digest(args.receipt)}
    if d['role'] == 'preflight' and r['status'] == 'READY':
        require(evidence.read(evidence.bound(r['gate_plan_source'])) == r['gate_plan'],
                'gate-plan 来源已变化或与报告不符')
        _, children, _, value = execution_plan.live(d['repository_root'], d['parent_id'])
        require(value == r['execution_plan'] and set(value['ticket_order']) == set(r['expected_children']),
                '执行计划或 children 在 preflight 后变化')
        execution_plan.check_selected(d['repository_root'], d['parent_id'], value, children, required=False)
        record['execution_plan_source'] = execution_plan.adopt(d['repository_root'], d['parent_id'], value,
            children, [evidence.binding(args.dispatch), evidence.binding(args.report), evidence.binding(args.receipt)],
            '首次 READY preflight 接纳；已有计划保持原来源')
    if closure:
        record['closure_source'] = closure
    write(args.output, record)
    return record


def accepted(path):
    a = read(path)
    require(Path(path).resolve().parent == Path(a["dispatch_path"]).resolve().parent, "验收记录不属于 dispatch 目录")
    require(a.get("kind") == "mechanical_acceptance", "需要机械验收记录")
    for kind in ("dispatch", "report", "receipt"):
        require(digest(a[kind + "_path"]) == a[kind + "_sha256"], "已验收证据发生变化：" + kind)
    d, r, _ = inspect(a["dispatch_path"], a["report_path"], a["receipt_path"])
    handoff.check_close(a['dispatch_path'], a['report_path'], a.get('closure_source'),
                        required=d.get('finalization_version') == 2 or bool(d.get('preflight_acceptance')))
    require(r["status"] in ("DONE", "READY_TO_MERGE"), "只有成功报告可生成完成记录或合入")
    return a, d, r


def comment(args):
    a, d, r = accepted(args.acceptance)
    require(Path(args.output).resolve().parent == Path(a["dispatch_path"]).resolve().parent, "comment 文件必须留在 dispatch 证据目录")
    final = d["role"] == "finalizer"
    require(d["role"] in ("executor", "finalizer"), "该角色没有完成 comment")
    pair = r["review_rounds"][-1] if final else r["review"]["final"]
    metadata = {"kind": "integration-ready" if final else "ticket-completion", "parent_id": d["parent_id"],
                "reviewed_main": r["reviewed_main"] if final else r["base_commit"], "reviewed_head": r["head_commit"],
                "acceptance_path": str(Path(args.acceptance).resolve()), "report_sha256": a["report_sha256"]}
    lines = ["## " + metadata["kind"], args.summary, "", "```json", json.dumps(metadata, ensure_ascii=False), "```", "",
             "提交范围：`" + metadata["reviewed_main"] + ".." + metadata["reviewed_head"] + "`",
             "Review：PASS；轮次：" + str(len(r["review_rounds"]) if final else r["review"]["attempts"])]
    if metadata["reviewed_main"] == metadata["reviewed_head"]:
        lines += ["受审行为已在基线满足；本次无新增提交。"]
    if not final:
        if d.get("ticket_execution_version"):
            d = read(evidence.bound(r["execution"]["stage_dispatch"]))
            gates = list(d.get("required_boundary_gates", []))
            for item in r["execution"]["implementers"]:
                implementation = read(evidence.bound(item["report"]))
                gates += implementation["required_boundary_gates"]
            lines += ["Boundary gates：" + json.dumps(list(dict.fromkeys(gates)), ensure_ascii=False),
                      "阶段与实现来源：" + json.dumps(r["execution"], ensure_ascii=False)]
        if d.get("plan_adjustment"):
            adjustment = read(evidence.bound(d["plan_adjustment"]))
            lines += ["执行计划调整：" + adjustment["original_plan"]["mode"] + " → " + adjustment["effective_plan"]["mode"],
                      "调整原因：" + adjustment["reason"], "调整证据：" + json.dumps(d["plan_adjustment"], ensure_ascii=False)]
        if "stage" in d:
            lines += ["交付阶段：" + str(d["stage"]) + "（0 为首次实现）",
                      "本阶段模型：" + json.dumps(d["models"], ensure_ascii=False)]
        lines += ["Test mode：" + r["test_plan"]["mode"], "Approved seams：" + json.dumps(r["test_plan"]["approved_seams"], ensure_ascii=False),
                  "Commits：" + ", ".join(c["sha"] for c in r["implementation_commits"])]
    lines += ["", "验证记录：", "```json", json.dumps(r["verification"], ensure_ascii=False, indent=2), "```",
              "", "残留非阻塞 smells：", "```json", json.dumps([f for axis in pair.values() for f in axis["findings"] if f["kind"] == "smell"], ensure_ascii=False, indent=2), "```",
              "", "证据：", a["report_path"], a["receipt_path"], str(Path(args.acceptance).resolve())]
    if final:
        if "stage" in r:
            lines += ["交付阶段：" + str(r["stage"]), "阶段证据：", json.dumps(r["stage_sources"], ensure_ascii=False)]
        lines.extend(r["sources"])
    for evidence_path in args.evidence:
        require(Path(evidence_path).is_file(), "补证文件不存在")
        lines.append(str(Path(evidence_path).resolve()))
    write(args.output, "\n".join(lines) + "\n")
    return {"comment_path": str(Path(args.output).resolve()), "metadata": metadata}


def bd(root, *args):
    return json.loads(run(["bd", *args, "--readonly", "--json"], root))


primary_writable = repository.primary_writable


def update_main(args):
    root = primary(args.repository_root)
    primary_writable(root)
    fetched = subprocess.run(["git", "-C", root, "fetch", "origin"], capture_output=True, text=True)
    target = sha(root, "refs/remotes/origin/main")
    primary_writable(root)
    git(root, "merge", "--ff-only", target)
    return {"repository_root": root, "main_commit": sha(root, "refs/heads/main"),
            "fetch_failed": fetched.returncode != 0,
            "note": "fetch 失败，以本地 ref 为准" if fetched.returncode else ""}


def merge(args):
    a, d, r = accepted(args.acceptance)
    require(Path(args.output).resolve().parent == Path(a["dispatch_path"]).resolve().parent, "合入记录必须留在 dispatch 证据目录")
    require(d["role"] == "finalizer", "合入需要 finalizer 验收")
    root, wt = d["repository_root"], d["worktree"]
    comments = bd(root, "comments", d["parent_id"])
    matches = [c for c in comments if str(c.get("id")) == args.comment_id]
    require(len(matches) == 1, "integration-ready comment 不存在或不唯一")
    body = matches[0].get("text", matches[0].get("body", ""))
    blocks = re.findall(r"```json\s*\n(.*?)\n```", body, re.S)
    metadata = [json.loads(b) for b in blocks]
    require(any(isinstance(m, dict) and m.get("kind") == "integration-ready" and m.get("parent_id") == d["parent_id"] and m.get("reviewed_main") == r["reviewed_main"] and m.get("reviewed_head") == r["head_commit"] and m.get("report_sha256") == a["report_sha256"] and m.get("acceptance_path") == str(Path(args.acceptance).resolve()) for m in metadata), "integration-ready comment 未绑定本次证据")
    topology(d)
    primary_writable(root)
    require(not status(wt), "合入前 implementation worktree 不干净")
    current_main = sha(root, "HEAD")
    require(current_main == r["reviewed_main"] or (Path(args.output).exists() and current_main == r["head_commit"]), "main 已移动，必须重新最终集成")
    require(sha(wt, "HEAD") == r["head_commit"], "受审 HEAD 已移动")
    record = {"kind": "merge_checkpoint", **{k: d[k] for k in ("repository_root", "worktree", "branch", "parent_id")},
              "reviewed_head": r["head_commit"], "integration_comment_id": args.comment_id,
              "acceptance_path": str(Path(args.acceptance).resolve())}
    if Path(args.output).exists():
        require(read(args.output) == record, "已有合入 checkpoint 与本次操作不符")
    else:
        write(args.output, record)
    if current_main != r["head_commit"]:
        git(root, "merge", "--ff-only", r["head_commit"])
    require(sha(root, "HEAD") == r["head_commit"], "合入后 HEAD 不符")
    return {**record, "merged": True}


def cleanup(args):
    d = read(args.merge_record)
    require(d.get("kind") == "merge_checkpoint", "需要合入 checkpoint")
    topology(d, allow_missing=True)
    root, wt = d["repository_root"], Path(d["worktree"])
    parents = bd(root, "show", d["parent_id"])
    require(len(parents) == 1 and parents[0]["id"] == d["parent_id"] and parents[0]["status"] == "closed", "parent 尚未关闭")
    git(root, "merge-base", "--is-ancestor", d["reviewed_head"], "main")
    refs = git(root, "for-each-ref", "--format=%(refname)", "refs/heads/" + d["branch"]).splitlines()
    branch_exists = "refs/heads/" + d["branch"] in refs
    if branch_exists:
        require(sha(root, "refs/heads/" + d["branch"]) == d["reviewed_head"], "implementation branch 已移动")
    if wt.exists():
        require(not status(wt), "implementation worktree 不干净")
        git(root, "worktree", "remove", str(wt))
    if branch_exists:
        git(root, "branch", "-d", d["branch"])
    return {"cleaned": True, "parent_id": d["parent_id"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare"); p.add_argument("role", choices=("preflight", "executor", "finalizer")); p.add_argument("--input", required=True)
    p = commands.add_parser("update-main"); p.add_argument("--repository-root", required=True)
    p = commands.add_parser("sync-main"); p.add_argument("--input", required=True)
    p = commands.add_parser("sync-final"); p.add_argument("--input", required=True)
    p = commands.add_parser("adapt-plan")
    p.add_argument("--dispatch", required=True); p.add_argument("--input", required=True)
    p = commands.add_parser("accept")
    p.add_argument("--closure", help="收尾来源 path/sha256 JSON")
    for name in ("dispatch", "report", "receipt", "output"): p.add_argument("--" + name, required=True)
    p = commands.add_parser("comment")
    for name in ("acceptance", "summary", "output"): p.add_argument("--" + name, required=True)
    p.add_argument("--evidence", action="append", default=[])
    p = commands.add_parser("merge")
    for name in ("acceptance", "comment-id", "output"): p.add_argument("--" + name, required=True)
    p = commands.add_parser("cleanup"); p.add_argument("--merge-record", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(globals()[args.command.replace("-", "_")](args), ensure_ascii=False))
    except (ValueError, KeyError, OSError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

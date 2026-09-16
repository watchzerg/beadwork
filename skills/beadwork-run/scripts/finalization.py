"""最终集成的阶段准备和证据校验；只写证据，源码和 Git 引用只读。"""
from pathlib import Path
import sys
import uuid
import controller as c
import final_state as fs
import final_verification as fv


def ops():
    return c.executor_ops()


def same_attempt(a, b):
    keys = ("repository_root", "worktree", "branch", "parent_id", "reviewed_main", "attempt_id")
    c.require(all(a.get(k) == b.get(k) for k in keys)
              and a["expected_children"] == b["expected_children"], "最终阶段不属于同一集成尝试")


def prepare_attempt(d, head):
    prior = d["prior_finalization"]
    # 调用输入可以沿用旧 dispatch，但身份只由显式恢复来源继承。
    for key in ("attempt_id", "attempt_path", "resume_stage", "stage", "models"):
        d.pop(key, None)
    previous = None
    if prior and "stage_path" in prior:
        previous = c.read(prior["stage_path"])
        c.require(previous.get("finalization_version") in (1, 2), "需要有效的旧最终阶段")
        for key in ("repository_root", "worktree", "branch", "parent_id", "expected_children"):
            c.require(previous[key] == d[key], "恢复批次身份变化")
        if fs.strict(previous):
            _, selection = fs.selected(previous)
            d['required_boundary_gates'] = list(dict.fromkeys(d['required_boundary_gates'] + selection['gates']))
        changed_main = previous["reviewed_main"] != d["reviewed_main"]
        if not changed_main and not d.get("new_attempt_reason"):
            d.update(attempt_id=previous["attempt_id"], attempt_path=previous["attempt_path"],
                     start_head=previous["start_head"], resume_stage=prior["stage_path"])
            c.git(d["worktree"], "merge-base", "--is-ancestor", previous["stage_base"], head)
            c.require(set(previous["required_boundary_gates"]) <= set(d["required_boundary_gates"]), "恢复不得减少 gates")
            c.require(not c.status(d["worktree"]) or previous["stage"] > 0, "仅修复阶段可接续 dirty 现场")
        else:
            c.require(not c.status(d["worktree"]), "新集成尝试必须从干净现场开始")
            d['historical_finalization'] = prior
            d['prior_finalization'] = None
    elif prior:
        # 保留旧调用契约；导入时再核对原始报告和 fixer/collection 来源。
        c.require(all(k in prior for k in ("fix_used", "review_rounds_used", "report_path")), "旧恢复信息不完整")
        c.require(not c.status(d["worktree"]) or prior["fix_used"] is True, "旧 dirty 现场须有已派发 fixer")
        old = c.read(prior["report_path"])
        c.require(old.get("parent_id") == d["parent_id"] and old.get("reviewed_main") == d["reviewed_main"]
                  and old.get("start_head"), "旧最终集成身份不完整")
        d["start_head"] = old["start_head"]
    else:
        c.require(not c.status(d["worktree"]), "首次最终验收需要干净现场")
    if "attempt_id" not in d:
        evidence = Path(d["repository_root"]) / ".worktrees/.evidence" / d["parent_id"] / "final-review"
        if not d.get("new_attempt_reason") and previous is None and not prior:
            for path in evidence.glob("*/stage-*/dispatch.json"):
                old = c.read(path)
                c.require(old.get("reviewed_main") != d["reviewed_main"],
                          "已有同基线最终阶段，重新调用须提供 prior_finalization.stage_path")
    d["finalization_version"] = 2


def read_stage_report(stage, report_path, receipt_path):
    o = ops()
    for path in (report_path, receipt_path):
        c.require(Path(path).resolve().parent == Path(stage["dispatch_path"]).parent, "阶段报告必须位于原目录")
    c.verifier("finalizer", "--check-report", report_path, receipt_path, "--expected", stage["dispatch_path"])
    report = c.read(report_path)
    check_report(stage, report)
    return report


def models(stage, previous, facts):
    levels = dict(zip(("fixer", "standards", "spec"), c.FINAL_STAGE_MODELS[stage]))
    if previous:
        for role, model in previous.get("models", {}).items():
            if role in levels:
                levels[role] = max(levels[role], c.MODEL_LEVELS.index(model))
    changes = facts.get("model_overrides", {})
    c.require(isinstance(changes, dict) and set(changes) <= set(levels), "模型角色无效")
    if changes:
        c.require(facts.get("model_override_reason"), "模型升级需要理由")
        for role, model in changes.items():
            c.require(model in c.MODEL_LEVELS and c.MODEL_LEVELS.index(model) >= levels[role], "模型不能降档")
            levels[role] = c.MODEL_LEVELS.index(model)
    return {role: c.MODEL_LEVELS[level] for role, level in levels.items()}


def prepare_stage(dispatch_path, facts):
    o = ops()
    root = o.dispatch(dispatch_path)
    c.require(root["role"] == "finalizer" and root.get("finalization_version") in (1, 2), "需要新版 finalizer dispatch")
    c.topology(root)
    head = c.sha(root["worktree"], "HEAD")
    c.git(root["worktree"], "merge-base", "--is-ancestor", root["reviewed_main"], head)
    if fs.strict(root):
        value, _, _ = fs.state(root)
        if value['current'] is not None:
            chosen = value['stages'][str(value['current'])]
            path = str(o.bound(chosen['dispatch']))
            c.require(not facts.get('previous_stage') or facts['previous_stage'] == path, '必须恢复当前最终阶段')
            old = o.dispatch(path)
            if facts.get('continuation', 'resume') == 'resume':
                if chosen['report']:
                    prior = c.read(o.bound(chosen['report']['report']))
                    c.require(prior['outcome'] in ('blocked', 'interrupted'), '已完成或代码失败阶段不能作为中断恢复')
                return fs.result(old)
            c.require(chosen['report'], '推进阶段需要明确选中的报告')
            facts = dict(facts, previous_stage=path,
                         previous_report=str(o.bound(chosen['report']['report'])),
                         previous_receipt=str(o.bound(chosen['report']['receipt'])))
        elif root.get('prior_finalization'):
            c.require(root.get('resume_stage') and c.read(root['resume_stage']).get('finalization_version') == 2,
                      '历史 attempt 缺少严格检查点；保留原件，需补齐可证明的选择与验证来源后恢复')
    previous_path = facts.get("previous_stage", root.get("resume_stage"))
    continuation = facts.get("continuation", "resume")
    c.require(continuation in ("resume", "repair"), "continuation 必须为 resume 或 repair")
    previous = report = None
    stage, base, reviews, fixes, history = 0, head, [], [], []
    verification, gate_sources = [], []
    if previous_path:
        previous = o.dispatch(previous_path)
        same_attempt(root, previous)
        for path in Path(root["attempt_path"]).glob("stage-*/dispatch.json"):
            later = c.read(path)
            c.require(not any(source["path"] == str(previous_path) for source in later.get("previous_stages", [])),
                      "已有后续阶段，必须从最近 dispatch 恢复")
        stage, base = previous["stage"], previous["stage_base"]
        history = previous["previous_stages"] + [o.binding(previous_path)]
        reviews, fixes = previous["prior_reviews"], previous["prior_fixes"]
        verification, gate_sources = previous["prior_verification"], previous["prior_gate_sources"]
        c.require(bool(facts.get("previous_report")) == bool(facts.get("previous_receipt")), "报告和回执须成对提供")
        if facts.get("previous_report"):
            report = read_stage_report(previous, facts["previous_report"], facts["previous_receipt"])
            c.require(report["stopped_tasks"], "前阶段任务未确认停止")
            c.require(report["status"] != "READY_TO_MERGE", "已通过阶段应交付 controller")
            if report["head_commit"]:
                c.require(head == report["head_commit"], "阶段交接 HEAD 已变化")
            reviews, fixes = report["review_sources"], report["fix_sources"]
            verification, gate_sources = report["verification"], report["gate_sources"]
        else:
            c.require(not list(Path(previous_path).parent.glob("result-*.json")), "已有阶段结果，必须显式选择报告和回执")
        if continuation == "repair":
            c.require(report is not None and report["outcome"] == "code_failure", "下一修复阶段需要 code_failure 证据")
            stage += 1
            base = head
        elif report:
            c.require(report["outcome"] in ("interrupted", "blocked"), "代码失败必须进入下一阶段")
    else:
        c.require(not list(Path(root["attempt_path"]).glob("stage-*/dispatch.json")), "已有阶段，不能重新从阶段 0 开始")
        prior = root.get("prior_finalization")
        if prior and "fix_used" in prior:
            legacy = c.read(prior["report_path"])
            c.require(facts.get("legacy_dispatch") and facts.get("legacy_receipt"), "导入须提供旧 dispatch 和 receipt")
            old_dispatch = o.dispatch(facts["legacy_dispatch"])
            c.require(old_dispatch["role"] == "finalizer" and not old_dispatch.get("finalization_version"), "需要旧格式 finalizer 来源")
            for key in ("parent_id", "branch", "repository_root", "worktree", "reviewed_main", "start_head", "expected_children"):
                c.require(old_dispatch[key] == root[key] and (key not in legacy or legacy[key] == root[key]), "旧最终集成范围不符")
            c.verifier("finalizer", "--check-report", prior["report_path"], facts["legacy_receipt"], "--expected", facts["legacy_dispatch"])
            c.require(legacy.get("parent_id") == root["parent_id"] and legacy.get("reviewed_main") == root["reviewed_main"], "旧报告身份不符")
            c.require(legacy["status"] == "BLOCKED", "旧成功报告应验收交付")
            c.require(type(prior["fix_used"]) is bool and prior["fix_used"] == legacy["fix"]["used"], "旧修复额度不符")
            stage = int(prior["fix_used"])
            paths = facts.get("legacy_reviews", [])
            c.require(len(paths) == prior["review_rounds_used"] == len(legacy["review_rounds"]), "必须提供全部旧 review 来源")
            for path, pair in zip(paths, legacy["review_rounds"]):
                c.require(o.collection(path, dispatch_path)[0] == pair, "旧 review 来源不符")
            reviews = [o.binding(path) for path in paths]
            fixes = facts.get("legacy_fixes", [])
            if stage:
                fixer = c.read(facts["legacy_fixer_dispatch"])
                c.require(fixer["parent_id"] == root["parent_id"] and fixer["branch"] == root["branch"], "旧 fixer 身份不符")
                base = fixer["base_commit"]
            verification, gate_sources = legacy["verification"], legacy["gate_sources"]
            imported_commits = []
            for source in fixes:
                _, _, commits = read_fixer(source, dict(root, stage=stage))
                imported_commits += [commit for commit in commits if commit not in imported_commits]
            c.require(imported_commits == legacy["fix"]["commits"], "旧修复提交缺少完整 fixer 来源")
            if len(reviews) == stage + 1 and legacy["review_rounds"] and any(
                finding["blocking"] for axis in legacy["review_rounds"][-1].values() for finding in axis["findings"]
            ):
                c.require(continuation == "repair", "旧完整 blocking review 必须进入下一阶段")
            if continuation == "repair":
                c.require(facts.get("legacy_code_failure_reason"), "旧报告进入下一修复阶段需代码失败依据")
                stage += 1
                base = head
        else:
            c.require(continuation == "resume", "首次验收不能跳过阶段 0")
    c.require(0 <= stage <= 3, "四阶段已用尽，停止并保留现场")
    c.require(not c.status(root["worktree"]) or stage > 0, "首次验收不能包含 dirty 现场")
    c.git(root["worktree"], "merge-base", "--is-ancestor", base, head)
    gates = list(root['required_boundary_gates'])
    if fs.strict(root) and previous:
        _, selected = fs.selected(previous)
        gates = list(dict.fromkeys(gates + selected['gates']))
    directory = Path(root["attempt_path"]) / ("stage-" + uuid.uuid4().hex)
    directory.mkdir()
    d = {**root, "required_boundary_gates": gates, "stage": stage, "stage_base": base, "previous_stages": history,
         "prior_reviews": reviews, "prior_fixes": fixes, "prior_verification": verification,
         "prior_gate_sources": gate_sources, "models": models(stage, previous, facts),
         "dispatch_path": str(directory / "dispatch.json"), "report_path": str(directory / "report.json"),
         "report_schema_path": str(directory / "report-schema.json"),
         "receipt_schema_path": str(directory / "receipt-schema.json"),
         "previous_result": o.binding(facts["previous_report"]) if report else None,
         "previous_receipt": o.binding(facts["previous_receipt"]) if report else None}
    import gate_repair
    gate_repair.inherit(d, previous)
    if facts.get("model_overrides"):
        d["model_override_reason"] = facts["model_override_reason"]
    c.write(d["report_schema_path"], c.verifier("finalizer", "--schema"))
    c.write(d["receipt_schema_path"], c.verifier("finalizer", "--receipt-schema"))
    c.write(d["dispatch_path"], d)
    # 已通过 fixer 的同阶段恢复只接续验证/review，不再派 writer。
    fixer_done = False
    for source in fixes:
        worker, result, _ = read_fixer(source, d)
        if worker.get("stage", 1) == stage and result["status"] == "DONE" and result["head_commit"] == head:
            fixer_done = True
    fixer_path = None
    if stage > 0 and not fixer_done:
        folder = directory / "fixer"
        folder.mkdir()
        fd = {**d, "role": "fixer", "base_commit": base, "stage_dispatch": o.binding(d["dispatch_path"]),
              "model": d["models"]["fixer"]["model"], "reasoning_effort": d["models"]["fixer"]["reasoning_effort"],
              "resume": bool(previous and previous["stage"] == stage),
              "dispatch_path": str(folder / "dispatch.json"), "report_path": str(folder / "report.json"),
              "report_schema_path": str(folder / "report-schema.json"), "receipt_schema_path": str(folder / "receipt-schema.json")}
        for name, flag in (("report_schema_path", "--schema"), ("receipt_schema_path", "--receipt-schema")):
            c.write(fd[name], o.load_command([sys.executable, "-B", c.SCRIPTS / "verify-worker.py", flag, "fixer"]))
        fd["self_check_argv"] = [sys.executable, "-B", str(c.SCRIPTS / "verify-worker.py"), "--check-report", "fixer", fd["report_path"], "--expected", fd["dispatch_path"], "--emit-receipt"]
        if fs.strict(d):
            fd['self_check_argv'] = [sys.executable, '-B', str(c.SCRIPTS / 'executor-operations.py'),
                                    'fixer-check', '--dispatch', fd['dispatch_path'], '--report', fd['report_path']]
        c.write(fd["dispatch_path"], fd)
        fixer_path = fd["dispatch_path"]
    if fs.strict(d):
        fs.start(d, fixer_path)
        return fs.result(d)
    return {"stage_path": d["dispatch_path"], "stage": stage, "models": d["models"], "fixer_dispatch": fixer_path}


def read_fixer(source, current, tolerate_verification=False):
    o = ops()
    paths = {key: str(o.bound(source[key])) for key in ("dispatch", "report", "receipt")}
    d, r = c.read(paths["dispatch"]), c.read(paths["report"])
    for key in ("parent_id", "branch"):
        c.require(d[key] == current[key], "fixer 来源属于其他批次")
    if "attempt_id" in d:
        same_attempt(d, current)
        c.require(d["stage"] <= current["stage"], "fixer 来源阶段超前")
        stage_dispatch = c.read(o.bound(d["stage_dispatch"]))
        c.require(stage_dispatch["stage_base"] == d["base_commit"], "fixer BASE 与阶段不符")
    for key in ("report", "receipt"):
        c.require(Path(paths[key]).parent == Path(paths["dispatch"]).parent, "fixer 报告不在派发目录")
    checked = o.load_command([sys.executable, "-B", c.SCRIPTS / "verify-worker.py", "--check-report", "fixer",
                             paths["report"], paths["receipt"], "--expected", paths["dispatch"]])
    verification_failed = not checked['ok']
    c.require(checked['ok'] or (tolerate_verification and checked.get('failures')
        and all(f.startswith('fixer_verification: ') for f in checked['failures'])), 'fixer 验收失败')
    if r['status'] == 'DONE' or r.get('outcome') == 'code_failure':
        c.require(r["stopped_tasks"], "fixer 交付必须确认任务停止")
    if fs.strict(current):
        c.require(fs.strict(d), '严格阶段不能复用未校验运行来源的 fixer')
        if not verification_failed:
            fv.check(d, r)
        import handoff
        _, selection = fs.selected(stage_dispatch, current=False)
        handoff.check_close(paths['dispatch'], paths['report'], selection['closures'].get(source['report']['sha256']))
    head = r["head_commit"]
    commits = r.get("fix_commits", [r["fix_commit"]] if r.get("fix_commit") else [])
    if head:
        c.git(current["worktree"], "merge-base", "--is-ancestor", d["base_commit"], head)
        actual = c.git(current["worktree"], "rev-list", "--reverse", d["base_commit"] + ".." + head).splitlines()
        c.require(commits == actual, "fixer 提交列表与实际阶段范围不符")
    return d, r, commits


def check_report(expected, report):
    if expected.get("finalization_version") not in (1, 2):
        return
    o = ops()
    c.require(report.get("attempt_id") == expected["attempt_id"] and report.get("stage_sources"), "缺少最终阶段身份或来源")
    stages = [o.dispatch(str(o.bound(source))) for source in report["stage_sources"]]
    d = stages[-1]
    same_attempt(expected, d)
    if fs.strict(expected):
        c.require(fs.strict(d), '最终交付协议版本不符')
        fs.check_sources(d, report)
        fv.check(d, report)
        if 'stage' not in expected:
            fs.check_delivery(expected, report)
    c.require(report["stage"] == d["stage"], "阶段编号不符")
    if "stage" in expected:
        c.require(expected["dispatch_path"] == d["dispatch_path"], "报告不属于指定阶段")
    c.require(d["previous_stages"] == report["stage_sources"][:-1], "阶段历史丢失或重排")
    for index, current in enumerate(stages):
        same_attempt(expected, current)
        c.require(current["previous_stages"] == report["stage_sources"][:index], "阶段历史链不完整")
    for a, b in zip(stages, stages[1:]):
        c.require(b["stage"] in (a["stage"], a["stage"] + 1), "阶段跳跃或重置")
        if b.get("previous_result"):
            previous_report = str(o.bound(b["previous_result"]))
            previous_receipt = str(o.bound(b["previous_receipt"]))
            c.verifier("finalizer", "--check-report", previous_report, previous_receipt, "--expected", a["dispatch_path"])
            prior = c.read(previous_report)
            c.require(prior["stopped_tasks"], "历史任务未确认停止")
            c.require(b["prior_reviews"] == prior["review_sources"] and b["prior_fixes"] == prior["fix_sources"], "阶段交接丢失报告来源")
            c.require(prior["outcome"] == "code_failure" if b["stage"] > a["stage"] else prior["outcome"] in ("blocked", "interrupted"), "阶段交接结果不符")
            if b["stage"] > a["stage"]:
                c.require(b["stage_base"] == prior["head_commit"], "新修复阶段 BASE 不符")
        else:
            c.require(b["stage"] == a["stage"] and b["prior_reviews"] == a["prior_reviews"]
                      and b["prior_fixes"] == a["prior_fixes"], "无结果恢复不能推进或重写历史")
        if b["stage"] == a["stage"]:
            c.require(b["stage_base"] == a["stage_base"], "同阶段恢复改变 BASE")
    reviews, fixes = report["review_sources"], report["fix_sources"]
    c.require(reviews[:len(d["prior_reviews"])] == d["prior_reviews"], "丢失历史 review")
    c.require(fixes[:len(d["prior_fixes"])] == d["prior_fixes"], "丢失历史 fixer 交付")
    historical_verification = d['prior_verification']
    if fs.strict(d) and report.get('verification_issues'):
        unavailable_dirs = {Path(issue['dispatch']['path']).parent for issue in report['verification_issues']}
        historical_verification = [v for v in historical_verification if Path(v['log_path']).parent.parent not in unavailable_dirs]
    c.require(report['verification'][:len(historical_verification)] == historical_verification, '丢失历史验证')
    c.require(all(g in report["gate_sources"] for g in d["prior_gate_sources"]), "丢失 gate 来源")
    c.require(len(reviews) == len(report["review_rounds"]) <= 4, "review 历史数量不符")
    c.require(len(reviews) <= len(d["prior_reviews"]) + 1, "每阶段最多新增一轮 review")
    previous_head = d["reviewed_main"]
    previous_review_stage = -1
    for index, (source, pair) in enumerate(zip(reviews, report["review_rounds"])):
        actual, gate = o.collection(str(o.bound(source)), d["dispatch_path"])
        c.require(actual == pair, "review 与原始来源不符")
        head = pair["spec"]["reviewed_head"]
        c.git(d["worktree"], "merge-base", "--is-ancestor", previous_head, head)
        c.require(head != previous_head or (index == 0 and d.get("execution_contract") == 2), "review HEAD 重复")
        previous_head = head
        collection = c.read(o.bound(source))
        origin = c.read(o.bound(c.read(o.bound(collection["round"]))["dispatch"]))
        review_stage = origin.get("stage", index)
        c.require(previous_review_stage < review_stage <= d["stage"], "同阶段重复 review 或阶段顺序不符")
        previous_review_stage = review_stage
    if len(reviews) > len(d["prior_reviews"]):
        item = c.read(o.bound(reviews[-1]))
        origin = c.read(o.bound(c.read(o.bound(item["round"]))["dispatch"]))
        c.require(origin.get("stage") == d["stage"], "新增 review 不属于当前阶段")
        if any(f["blocking"] for axis in report["review_rounds"][-1].values() for f in axis["findings"]):
            c.require(report["outcome"] in ("code_failure", "blocked"), "完整 BLOCKED review 必须明确代码失败或非代码阻塞")
    code_failure_evidence = any(not item["passed"] and item["head_commit"] == report["head_commit"]
                                for item in report["verification"][len(d["prior_verification"]):])
    if len(reviews) > len(d["prior_reviews"]):
        code_failure_evidence |= any(f["blocking"] for axis in report["review_rounds"][-1].values() for f in axis["findings"])
    commits = []
    for source in fixes:
        fd, fr, fc = read_fixer(source, d, tolerate_verification=report['outcome'] in ('blocked', 'interrupted'))
        if source not in d["prior_fixes"] and fr.get("outcome") == "code_failure":
            code_failure_evidence = True
            c.require(report["outcome"] == "code_failure", "fixer 代码失败不能伪装成中断")
        for commit in fc:
            if commit not in commits:
                commits.append(commit)
        unavailable = any(issue['dispatch'] == source['dispatch'] for issue in report.get('verification_issues', []))
        c.require(unavailable or all(v in report["verification"] for v in fr["verification"]), "遗漏 fixer 验证")
    if fs.strict(d) and report['outcome'] == 'code_failure':
        new_blocking = len(reviews) > len(d['prior_reviews']) and any(f['blocking'] for axis in report['review_rounds'][-1].values() for f in axis['findings'])
        if not new_blocking:
            if d['stage'] == 0:
                rows = fv.check(d, report)
                code_failure_evidence = any(row[4] and row[3]['exit_code'] > 0
                    and row[2]['dispatch_path'] == d['dispatch_path'] and row[2]['before']['head'] == report['head_commit'] for row in rows)
            else:
                code_failure_evidence = bool(fixes and c.read(o.bound(fixes[-1]['dispatch']))['stage'] == d['stage']
                    and c.read(o.bound(fixes[-1]['report']))['outcome'] == 'code_failure')
    if report["outcome"] == "code_failure":
        c.require(code_failure_evidence, "代码失败须有当前阶段失败验证或 blocking review/fixer 依据")
    c.require(report["fix"]["commits"] == commits, "最终 fix commits 与原始报告不符")
    if report["head_commit"]:
        actual = c.git(d["worktree"], "rev-list", "--reverse", d["start_head"] + ".." + report["head_commit"]).splitlines()
        c.require(actual == commits, "集成后提交遗漏或超出修复来源")
    if report["outcome"] == "passed":
        c.require(report["status"] == "READY_TO_MERGE", "passed 必须 READY_TO_MERGE")
        c.require(reviews and report["review_rounds"][-1]["spec"]["reviewed_head"] == report["head_commit"], "最终 review 未覆盖 HEAD")
    else:
        c.require(report["status"] == "BLOCKED", "未通过必须 BLOCKED")


def assemble(dispatch_path, draft_path, output_path, reviews, fixes):
    o = ops()
    d = o.dispatch(dispatch_path)
    c.require(d.get("finalization_version") in (1, 2) and "stage" in d, "需要最终阶段 dispatch")
    r = c.read(draft_path)
    head = c.sha(d["worktree"], "HEAD")
    r.update(parent_id=d["parent_id"], expected_children=d["expected_children"], reviewed_main=d["reviewed_main"],
             start_head=d["start_head"], head_commit=head, required_gates=d["required_boundary_gates"],
             stage=d["stage"], attempt_id=d["attempt_id"], stage_sources=d["previous_stages"] + [o.binding(dispatch_path)],
             review_sources=[o.binding(path) for path in reviews], fix_sources=fixes,
             review_rounds=[o.collection(path, dispatch_path)[0] for path in reviews],
             workspace={"branch": d["branch"], "observed_head": head, "clean": not c.status(d["worktree"])})
    if fs.strict(d):
        fs.gates(d, r['boundary_gates'], r['gate_sources'])
        _, chosen = fs.selected(d)
        r['boundary_gates'] = chosen['gates']
        r['gate_sources'] = chosen['gate_sources']
    current_verification = r["verification"]
    r["verification"] = list(d["prior_verification"])
    for item in d["prior_gate_sources"]:
        if item not in r["gate_sources"]:
            r["gate_sources"].append(item)
    commits, dispositions = [], []
    for source in fixes:
        _, fr, fc = read_fixer(source, d, tolerate_verification=r['outcome'] in ('blocked', 'interrupted'))
        commits += [commit for commit in fc if commit not in commits]
        dispositions += [item["source"] + "：" + item["action"] for item in fr["dispositions"]]
        for v in fr["verification"]:
            if v not in r["verification"]:
                r["verification"].append(v)
        for g in fr["gate_sources"]:
            if g not in r["gate_sources"]:
                r["gate_sources"].append(g)
        r["boundary_gates"] = list(dict.fromkeys(r["boundary_gates"] + fr["boundary_gates"]))
    r["verification"].extend(current_verification)
    r["fix"] = {"used": d["stage"] > 0, "commits": commits, "dispositions": dispositions}
    if fs.strict(d):
        inherited = []
        for source in fixes:
            fr = c.read(o.bound(source['report']))
            inherited += [s for s in fr['verification_sources'] if s not in inherited]
            r.setdefault('verification_notes', {}).update(fr.get('verification_notes', {}))
        if d.get('previous_result'):
            prior = c.read(o.bound(d['previous_result']))
            inherited = prior['verification_sources'] + [s for s in inherited if s not in prior['verification_sources']]
            r.setdefault('verification_notes', {}).update(prior.get('verification_notes', {}))
        fv.populate(d, r, inherited)
    check_report(d, r)
    output = o.output_path(output_path, Path(dispatch_path).parent)
    c.write(output, r)
    checked = c.verifier("finalizer", "--check-report", output, "--expected", dispatch_path)
    result = {"status": r["status"], "report_path": str(output), "report_sha256": checked["report_sha256"]}
    receipt_path = output.parent / ("result-" + uuid.uuid4().hex + ".json")
    c.write(receipt_path, result)
    if fs.strict(d):
        fs.select_report(d, output, receipt_path)
    return result


def require_writer(d):
    stage = c.read(ops().bound(d['stage_dispatch']))
    _, item = fs.selected(stage)
    c.require(item['fixer'] == ops().binding(d['dispatch_path']), '不是当前 fixer')
    c.require(not item['round_path'], 'review 已开始，fixer 不可继续写入')
    if item['fixes'] and item['fixes'][-1]['dispatch'] == item['fixer']:
        prior = c.read(ops().bound(item['fixes'][-1]['report']))
        c.require(prior['outcome'] in ('blocked', 'interrupted'), 'fixer 已交付终态')
        c.require(prior['stopped_tasks'], '旧 fixer 任务未确认停止')


def fixer_check(dispatch_path, report_path, receipt_path=None, live=True):
    o = ops()
    d = o.dispatch(dispatch_path)
    c.require(d['role'] == 'fixer' and fs.strict(d), '需要新版 fixer dispatch')
    c.require(Path(report_path).parent == Path(dispatch_path).parent, 'fixer 报告目录不符')
    argv = [sys.executable, '-B', str(c.SCRIPTS / 'verify-worker.py'), '--check-report', 'fixer', report_path]
    if receipt_path:
        c.require(Path(receipt_path).parent == Path(dispatch_path).parent, 'fixer 回执目录不符')
        argv.append(receipt_path)
    checked = o.load_command(argv + ['--expected', dispatch_path])
    c.require(checked['ok'], 'fixer 报告校验失败：' + str(checked.get('failures')))
    r = c.read(report_path)
    fv.check(d, r, live)
    actual = c.git(d['worktree'], 'rev-list', '--reverse', d['base_commit'] + '..' + r['head_commit']).splitlines()
    c.require(actual == r['fix_commits'], 'fixer 提交列表不完整')
    c.check_batch_beads(d['worktree'], d['base_commit'], r['head_commit'])
    if live:
        c.topology(d)
        c.require(c.sha(d['worktree'], 'HEAD') == r['head_commit'], 'fixer 交付 HEAD 已变化')
        c.require(r['status'] != 'DONE' or not c.status(d['worktree']), 'fixer 成功需要干净现场')
    return {'status': r['status'], 'report_path': str(report_path), 'report_sha256': c.digest(report_path)}


def fixer_assemble(dispatch_path, draft_path, output):
    d = ops().dispatch(dispatch_path)
    c.require(d['role'] == 'fixer' and fs.strict(d), '需要新版 fixer dispatch')
    r = c.read(draft_path)
    head = c.sha(d['worktree'], 'HEAD')
    r.update(stage=d['stage'], attempt_id=d['attempt_id'], parent_id=d['parent_id'], branch=d['branch'],
             base_commit=d['base_commit'], head_commit=head,
             fix_commits=c.git(d['worktree'], 'rev-list', '--reverse', d['base_commit'] + '..' + head).splitlines(),
             worktree_clean=not c.status(d['worktree']))
    r.pop('fix_commit', None)
    fv.populate(d, r)
    target = ops().output_path(output, Path(dispatch_path).parent)
    c.write(target, r)
    return fixer_check(dispatch_path, str(target))


def accept_fixer(stage_path, report_path, receipt_path, closure=None):
    d = ops().dispatch(stage_path)
    value, item = fs.selected(d)
    c.require(item['fixer'], '本阶段没有 fixer')
    path = str(ops().bound(item['fixer']))
    fixer_check(path, report_path, receipt_path)
    import handoff
    handoff.check_close(path, report_path, closure)
    source = {k: ops().binding(str(p)) for k, p in
              (('dispatch', path), ('report', report_path), ('receipt', receipt_path))}
    if source in item['fixes']:
        return {'accepted': True, 'source': source}
    c.require(not item['round_path'], 'review 后不能重新选择 fixer')
    r = c.read(report_path)
    if item['fixes'] and item['fixes'][-1]['dispatch'] == item['fixer']:
        prior = c.read(ops().bound(item['fixes'][-1]['report']))
        if prior['outcome'] in ('passed', 'code_failure'):
            c.require(prior['head_commit'] == r['head_commit'] and prior['outcome'] == r['outcome'], 'fixer 终态不能改报中断或改变 HEAD')
    item['fixes'].append(source)
    item['closures'][source['report']['sha256']] = closure
    item['report'] = None
    fs.save(d, value)
    fs.gates(d, r['boundary_gates'], r['gate_sources'])
    return {'accepted': True, 'source': source}


def review_ready(d):
    _, item = fs.selected(d)
    c.require(item['round'] is None, '本阶段已有 review；复用原 round')
    head = c.sha(d['worktree'], 'HEAD')
    if d['stage']:
        c.require(item['fixes'], 'review 需要已验收 fixer')
        source = item['fixes'][-1]
        fd, report, _ = read_fixer(source, d)
        c.require(fd['stage'] == d['stage'] and report['status'] == 'DONE' and report['head_commit'] == head,
                  '当前 fixer 未通过或 HEAD 不符')
    # 同 HEAD 的 finalizer 补充验证与 fixer 验证共同形成覆盖。
    r = {'status': 'READY_TO_MERGE', 'outcome': 'passed', 'head_commit': head,
         'boundary_gates': item['gates'], 'stage_sources': d['previous_stages'] + [ops().binding(d['dispatch_path'])],
         'fix_sources': item['fixes'], 'verification_notes': {}}
    inherited = []
    for source in item['fixes']:
        fr = c.read(ops().bound(source['report']))
        inherited += [s for s in fr['verification_sources'] if s not in inherited]
        r['verification_notes'].update(fr.get('verification_notes', {}))
    fv.populate(d, r, inherited)
    fv.check(d, r, live=True)


def deliver(root_path, output):
    root = ops().dispatch(root_path)
    c.require(fs.strict(root) and 'stage' not in root, 'final-deliver 需要 root dispatch')
    value, _, _ = fs.state(root)
    c.require(value['current'] is not None, '尚无最终阶段')
    source = value['stages'][str(value['current'])]['report']
    c.require(source, '尚无已选阶段报告')
    report = ops().bound(source['report'])
    stage = ops().dispatch(str(ops().bound(source['dispatch'])))
    read_stage_report(stage, str(report), str(ops().bound(source['receipt'])))
    r = c.read(report)
    c.require(r['outcome'] != 'code_failure' or r['stage'] == 3, '代码失败需在四阶段用尽后交付 controller')
    check_report(root, r)
    c.require(c.sha(root['worktree'], 'HEAD') == r['head_commit'], '交付 HEAD 已变化')
    target = ops().output_path(output, Path(root_path).parent)
    target.write_bytes(report.read_bytes())
    receipt = {'status': r['status'], 'report_path': str(target), 'report_sha256': c.digest(target)}
    receipt_path = target.with_name(target.stem + '-receipt.json')
    c.write(receipt_path, receipt)
    c.inspect(root_path, str(target), str(receipt_path))
    return receipt

"""单票阶段编排与交付选择；只写证据，不派发 agent。"""

from pathlib import Path
import sys
import uuid

import dispatch_contract
import evidence
import draft_contracts
import gate_repair
import handoff
import implementer_reports
import report_io
import repository
import review_evidence
import ticket_reports
import ticket_state
import ticket_verification
import workflow_policy

VERSION = 1
ROLES = ('implementer', 'standards', 'spec')


source = ticket_state.source
resolve_source = ticket_state.resolve_source
root = ticket_state.root
same_ticket = dispatch_contract.same_ticket
checkpoints = ticket_state.checkpoints
state_digest = ticket_state.state_digest
checkpoint = ticket_state.checkpoint


def root_fields(d):
    repository.require(not any(d.get(k) for k in ('previous_report', 'previous_receipt', 'continuation', 'stage', 'models')),
              'controller 只准备整票；阶段输入由 ticket-stage 管理')
    d.update(ticket_execution_version=VERSION, ticket_scope='root', start_head=d['base_commit'],
             coordinator_model=workflow_policy.MODEL_LEVELS[2 if d.get('complex_ticket') else 0])


def resume_root(d):
    previous = evidence.read(evidence.absolute(d['previous_dispatch']))
    repository.require(previous.get('ticket_scope') == 'root' and previous.get('ticket_execution_version') == VERSION,
              '恢复需要当前单票 root dispatch')
    same_ticket(previous, d)
    repository.topology(previous)
    repository.git(d['worktree'], 'merge-base', '--is-ancestor', d['base_commit'], 'HEAD')
    repository.require(d.get('continuation', 'resume') == 'resume', 'controller 不推进 stage；使用原 root 恢复 executor')
    state, _, _ = checkpoints(previous)
    if state['selected_stage']:
        _, report = resolve_source(state['selected_stage'])
        repository.require(report['status'] != 'DONE', '整票已完成，应验收关闭')
    return dict(previous, context_sources=handoff.contexts(previous))


def save_dispatch(d, folder, role):
    folder.mkdir(parents=True)
    d = dict(d, role=role, dispatch_path=str(folder / 'dispatch.json'), report_path=str(folder / 'report.json'),
             report_schema_path=str(folder / 'report-schema.json'), receipt_schema_path=str(folder / 'receipt-schema.json'))
    if role == 'implementer':
        for kind in ('schema', 'receipt-schema'):
            evidence.write(d['report_schema_path' if kind == 'schema' else 'receipt_schema_path'], worker('--' + kind))
        d['self_check_argv'] = [sys.executable, '-B', str(report_io.SCRIPTS / 'executor-operations.py'),
                               'implementer-check', '--dispatch', d['dispatch_path'], '--report', d['report_path']]
    else:
        evidence.write(d['report_schema_path'], report_io.verifier('executor', '--schema'))
        evidence.write(d['receipt_schema_path'], report_io.verifier('executor', '--receipt-schema'))
    draft_contracts.publish(d, role)
    evidence.write(d['dispatch_path'], d)
    return d


worker = report_io.implementer


def stage_result(d, state):
    selected = state['implementer_sources'][-1] if state['implementer_sources'] else None
    writer = evidence.read(evidence.bound(d['implementer_dispatch']))
    return {'context_sources': handoff.contexts(d), 'stage': d['stage'], 'stage_dispatch': d['dispatch_path'], 'implementer_dispatch': writer['dispatch_path'],
            'models': d['models'], 'prior_implementer': selected, 'selected_stage': state['selected_stage'],
            'selected_review': state['selected_review'],
            'required_boundary_gates': state['required_boundary_gates'],
            'gate_sources': state['gate_sources'],
            'review_round': state['review_round_path'],
            'review_started': (Path(d['gate_repair_root']) / 'gate-review-started.json').exists()}


def recover_unregistered_gate_repair(previous, report, state, reason):
    repository.require(report['outcome'] == 'blocked' and report['execution']['stopped_tasks'],
              '未登记 gate 修正恢复需要已停止的 blocked 阶段')
    repository.require(isinstance(reason, str) and reason.strip(), '未登记 gate 修正恢复需要记录原因')
    p = gate_repair.root(previous)
    repository.require(not state['selected_review'] and not (p / 'gate-review-started.json').exists()
              and not any(x.is_dir() for x in p.glob('review-*')), 'review 已开始，不能恢复未登记 gate 修正')
    used = gate_repair.used_repairs(p)
    repository.require(used > 0, '没有可恢复的 gate 修正候选')
    candidate_path = gate_repair.repair_path(p, used, candidate=True)
    repository.require(candidate_path.exists(), 'gate 修正候选尚未绑定')
    candidate = evidence.read(candidate_path)
    head = repository.sha(previous['worktree'], 'HEAD')
    repository.require(not repository.status(previous['worktree']) and head == report['head_commit']
              and head != candidate['head'], '恢复需要报告绑定的不同干净 HEAD')
    repository.git(previous['worktree'], 'merge-base', '--is-ancestor', candidate['head'], head)
    recovery = {
        'version': 1,
        'kind': 'unregistered-gate-repair',
        'stage': previous['stage'],
        'selected_stage': state['selected_stage'],
        'gate_repair': evidence.binding(str(gate_repair.repair_path(p, used))),
        'previous_candidate': evidence.binding(str(candidate_path)),
        'recovered_head': head,
        'reason': reason.strip(),
    }
    target = p / 'unregistered-gate-repair-recovery.json'
    gate_repair.record(target, recovery)
    return evidence.binding(str(target))


def prepare_stage(root_path, facts):
    r = dispatch_contract.dispatch(root_path)
    repository.require(r.get('ticket_scope') == 'root', 'ticket-stage 需要 executor root dispatch')
    repository.require(set(facts) <= {'continuation', 'model_overrides', 'model_override_reason', 'recovery_reason',
                                      'additional_stages', 'extension_reason'}, 'stage 输入字段无效')
    repository.topology(r)
    state, _, _ = checkpoints(r)
    continuation = facts.get('continuation', 'resume')
    repository.require(continuation in ('resume', 'repair', 'recover', 'extend'), 'continuation 无效')
    previous = None
    recovery = None
    extension = None
    stage_limit = len(workflow_policy.STAGE_MODELS) - 1
    if state['stage_dispatch']:
        previous = evidence.read(evidence.bound(state['stage_dispatch']))
        if continuation == 'resume':
            repository.require(not facts.get('model_overrides'), '已有 stage 沿用模型；提前升级在新 stage 准备时指定')
            repository.require('recovery_reason' not in facts, 'resume 不接受 recovery_reason')
            repository.require(not {'additional_stages', 'extension_reason'}.intersection(facts), 'resume 不接受额度扩展字段')
            if state['selected_stage']:
                _, report = resolve_source(state['selected_stage'])
                repository.require(report['outcome'] in ('interrupted', 'blocked'), '已完成或代码失败阶段不可作为中断恢复')
            return stage_result(previous, state)
        repository.require(state['selected_stage'], '推进 stage 需要已验收的阶段报告')
        old, report = resolve_source(state['selected_stage'])
        check_stage(old, report)
        stage_limit = previous.get('stage_limit', stage_limit)
        if continuation == 'repair':
            repository.require(report['outcome'] == 'code_failure', '只有 code_failure 使用 repair 推进 stage')
            repository.require(report['execution']['stopped_tasks'], '旧任务未确认停止')
            repository.require('recovery_reason' not in facts, 'repair 不接受 recovery_reason')
            repository.require(not {'additional_stages', 'extension_reason'}.intersection(facts), 'repair 不接受额度扩展字段')
        elif continuation == 'recover':
            repository.require(not {'additional_stages', 'extension_reason'}.intersection(facts), 'recover 不接受额度扩展字段')
            recovery = recover_unregistered_gate_repair(previous, report, state, facts.get('recovery_reason'))
        else:
            additional = facts.get('additional_stages')
            reason = facts.get('extension_reason')
            repository.require(previous['stage'] == stage_limit and report['outcome'] == 'code_failure'
                      and report['execution']['stopped_tasks'], '只有已耗尽的 code_failure 可追加 stage')
            repository.require(type(additional) is int and 1 <= additional <= workflow_policy.MAX_STAGE_EXTENSION,
                      '单次最多追加五个 stage')
            repository.require(isinstance(reason, str) and reason.strip(), '追加 stage 需要用户授权原因')
            stage_limit += additional
            record = {'version': 1, 'kind': 'authorized-stage-extension', 'stage': previous['stage'],
                      'selected_stage': state['selected_stage'], 'additional_stages': additional,
                      'new_stage_limit': stage_limit, 'reason': reason.strip()}
            target = Path(previous['gate_repair_root']) / 'ticket-stage-extension.json'
            gate_repair.record(target, record)
            extension = evidence.binding(str(target))
        number = previous['stage'] + 1
    else:
        repository.require(continuation == 'resume', '初次 stage 只接受 resume')
        repository.require('recovery_reason' not in facts, 'resume 不接受 recovery_reason')
        repository.require(not {'additional_stages', 'extension_reason'}.intersection(facts), 'resume 不接受额度扩展字段')
        number = 0
    repository.require(number <= stage_limit, 'stage 额度已用尽，停止并保留现场')
    if previous:
        state['stage_sources'] = state['stage_sources'] + [state['selected_stage']]
    head = repository.sha(r['worktree'], 'HEAD')
    if previous:
        repository.require(head == report['head_commit'], '阶段交付后 HEAD 已变化')
    else:
        repository.require(head == r['base_commit'] and not repository.status(r['worktree']), 'stage 0 需要原 BASE 的干净现场')
    levels = dict(zip(ROLES, workflow_policy.STAGE_MODELS[min(number, len(workflow_policy.STAGE_MODELS) - 1)]))
    if r.get('complex_ticket'):
        levels['implementer'] = max(levels['implementer'], 2)
        levels['standards'] = max(levels['standards'], 1)
    if previous:
        for role in ROLES:
            levels[role] = max(levels[role], workflow_policy.MODEL_LEVELS.index(previous['models'][role]))
    overrides = facts.get('model_overrides', {})
    repository.require(isinstance(overrides, dict) and set(overrides) <= set(ROLES), '模型角色无效')
    if overrides:
        repository.require(isinstance(facts.get('model_override_reason'), str) and facts['model_override_reason'].strip(), '提前升级需记录理由')
    for role, model in overrides.items():
        repository.require(model in workflow_policy.MODEL_LEVELS and workflow_policy.MODEL_LEVELS.index(model) >= levels[role], '模型只能升级')
        levels[role] = workflow_policy.MODEL_LEVELS.index(model)
    folder = Path(r['dispatch_path']).parent / ('stage-' + str(number) + '-' + uuid.uuid4().hex)
    inherited = previous or r
    d = dict(inherited, ticket_scope='stage', ticket_root=evidence.binding(root_path), stage=number,
             stage_base=head, start_head=head, mode='resume',
             models={role: workflow_policy.MODEL_LEVELS[level] for role, level in levels.items()},
             model_override_reason=facts.get('model_override_reason'), gate_repair_root=str(folder),
             prior_reviews=(report.get('review') or {}).get('sources', []) if previous else [],
             prior_stages=state['stage_sources'], previous_stage=state['selected_stage'],
             verification_dispatches=[])
    if recovery:
        d['stage_recovery'] = recovery
    if extension:
        d['stage_extension'] = extension
        d['stage_limit'] = stage_limit
    d['required_boundary_gates'] = list(state['required_boundary_gates'])
    d.pop('implementer_dispatch', None)
    folder.mkdir()
    w = save_dispatch(dict(d, ticket_scope='implementer'), folder / 'implementer', 'implementer')
    d['implementer_dispatch'] = evidence.binding(w['dispatch_path'])
    d = save_dispatch(d, folder / 'coordinator', 'executor')
    new_state = dict(state, stage_dispatch=evidence.binding(d['dispatch_path']), implementer_sources=[],
                     selected_stage=None, selected_review=None,
                     review_round_path=None, review_round=None)
    checkpoint(r, new_state)
    return stage_result(d, new_state)


require_writer = ticket_state.require_writer
implementer_schema = implementer_reports.implementer_schema
implementer_errors = implementer_reports.implementer_errors
runs = ticket_verification.runs
verification_snapshot = ticket_verification.verification_snapshot
collect_verification = ticket_verification.collect_verification
check_implementation = implementer_reports.check_implementation
implementer_check = implementer_reports.implementer_check
implementer_assemble = implementer_reports.implementer_assemble


def accept_implementer(stage_path, report_path, receipt_path, closure=None):
    d = dispatch_contract.dispatch(stage_path)
    state, _, _ = checkpoints(d)
    repository.require(state['stage_dispatch'] == evidence.binding(stage_path), '不是当前 stage')
    wpath = evidence.bound(d['implementer_dispatch'])
    item = source(wpath, report_path, receipt_path)
    w, report = resolve_source(item)
    implementer_check(str(wpath), report_path)
    handoff.check_close(str(wpath), report_path, closure, required=bool(d.get('preflight_acceptance')))
    if report['status'] == 'DONE' or report['outcome'] == 'code_failure':
        repository.require(report['stopped_tasks'], 'implementer 任务尚未停止')
    if state['implementer_sources'] and state['implementer_sources'][-1] == item:
        return {'accepted': True, 'source': item}
    if state['selected_stage']:
        _, selected = resolve_source(state['selected_stage'])
        repository.require(selected['outcome'] in ('interrupted', 'blocked'), '阶段已封存，不能用新实现报告覆盖')
    if state['implementer_sources']:
        _, prior = resolve_source(state['implementer_sources'][-1])
        repository.require(prior['head_commit'] == report['head_commit'] or prior['outcome'] in ('interrupted', 'blocked'), '实现已交付，报告更正不能改变 HEAD')
        if prior['outcome'] in ('passed', 'code_failure'):
            repository.require(report['outcome'] == prior['outcome'], '已验收实现终态不能改报中断或外部阻塞')
    repository.require(not (Path(d['gate_repair_root']) / 'gate-review-started.json').exists(), 'review 后只能更正审查/阶段报告')
    state.setdefault('closures', {})[item['report']['sha256']] = closure
    state['implementer_sources'].append(item)
    for gate in report['required_boundary_gates']:
        if gate not in state['required_boundary_gates']:
            state['required_boundary_gates'].append(gate)
        marker = {'gate': gate, 'report': item['report']}
        if marker not in state['gate_sources']:
            state['gate_sources'].append(marker)
    state['selected_stage'] = None
    checkpoint(d, state)
    return {'accepted': True, 'source': item}


def review_ready(d):
    state, _, _ = checkpoints(d)
    repository.require(state['stage_dispatch'] == evidence.binding(d['dispatch_path']) and state['implementer_sources'], 'review 需要当前 stage 已验收的 implementer')
    w, report = resolve_source(state['implementer_sources'][-1])
    worker('--check-report', state['implementer_sources'][-1]['report']['path'],
           state['implementer_sources'][-1]['receipt']['path'], '--expected', w['dispatch_path'])
    check_implementation(w, report, live=True)
    repository.require(report['status'] == 'DONE' and report['stopped_tasks'], '实现未通过，不能 review')
    repository.require(state['review_round'] is None, '每 stage 只准备一轮 review；恢复使用原 round')


reserve_review = ticket_state.reserve_review
bind_review_round = ticket_state.bind_review_round
select_review = ticket_state.select_review
check_selected_review = ticket_state.check_selected_review
check_stage = ticket_reports.check_stage
check_ticket = ticket_reports.check_ticket


def deliver(root_path, output):
    d = dispatch_contract.dispatch(root_path)
    state, _, _ = checkpoints(d)
    repository.require(state['selected_stage'], '需要先组装阶段报告')
    _, report = resolve_source(state['selected_stage'])
    check_ticket(d, report)
    target = dispatch_contract.output_path(output, Path(root_path).parent)
    evidence.write(target, Path(evidence.bound(state['selected_stage']['report'])).read_text())
    return ticket_reports.check_report(root_path, str(target))


def adapt_plan(args):
    d = dispatch_contract.dispatch(args.dispatch)
    repository.require(d.get('ticket_scope') == 'stage', '执行计划由当前 stage executor 核准')
    state, _, _ = checkpoints(d)
    repository.require(state['stage_dispatch'] == evidence.binding(args.dispatch), '不是当前执行上下文')
    repository.require(not (Path(d['gate_repair_root']) / 'gate-review-started.json').exists(), 'review 后不能适配计划')
    facts = evidence.read(args.input)
    repository.require(set(state['required_boundary_gates']).issubset(facts.get('boundary_gates', [])),
              '计划适配不得丢失累计 boundary gates')
    adjusted = adapt_plan_dispatch(args)
    old_writer = evidence.read(evidence.bound(d['implementer_dispatch']))
    adjusted['verification_dispatches'] = []
    folder = Path(adjusted['dispatch_path']).parent / 'adapted'
    writer = dict(adjusted, ticket_scope='implementer',
                  verification_dispatches=list(dict.fromkeys(old_writer.get('verification_dispatches', []) + [old_writer['dispatch_path']])))
    writer = save_dispatch(writer, folder / 'implementer', 'implementer')
    adjusted['implementer_dispatch'] = evidence.binding(writer['dispatch_path'])
    adjusted = save_dispatch(adjusted, folder / 'coordinator', 'executor')
    state.update(stage_dispatch=evidence.binding(adjusted['dispatch_path']), selected_stage=None)
    checkpoint(d, state)
    return stage_result(adjusted, state)


def assemble_stage(args):
    d, state, receipt = ticket_reports.assemble_stage(args)
    receipt_path = Path(args.output).with_name(Path(args.output).stem + '-receipt.json')
    evidence.write(receipt_path, receipt)
    item = source(args.dispatch, args.output, receipt_path)
    state['selected_stage'] = item
    checkpoint(d, state)
    return receipt


def adapt_plan_dispatch(args):
    """记录已核准的执行计划；新单票由 ticket-adapt-plan 调用并更新检查点。"""
    d = dispatch_contract.dispatch(args.dispatch)
    repository.require(d["role"] == "executor" and d.get("execution_contract") == 2, "需要新契约 executor")
    if d.get("ticket_execution_version"):
        repository.require(d.get("ticket_scope") == "stage", "整票 root 不适配计划；由 executor 使用 ticket-adapt-plan 更新当前 stage")
    repository.workspace(d)
    directory = Path(args.dispatch).parent
    repository.require(not (directory / "gate-review-started.json").exists()
            and not any(x.is_dir() for x in directory.glob("review-*")) and not Path(d["report_path"]).exists(),
            "计划适配须在当前阶段 review/交付前完成")
    facts = evidence.read(args.input)
    repository.require(set(facts) == {"reason", "acceptance", "verification", "boundary_gates", "mode"}, "计划适配字段不符")
    repository.require(isinstance(facts["reason"], str) and facts["reason"].strip(), "需要基线适配原因")
    repository.require(facts["mode"] in ("TDD", "direct_verification"), "执行模式无效")
    old_plan = evidence.read(d["expected_plan_path"])
    repository.require(facts["mode"] != old_plan["mode"], "执行模式未变化")
    for key, fields in (("acceptance", {"criterion", "evidence"}), ("verification", {"command", "result"})):
        repository.require(isinstance(facts[key], list) and facts[key] and all(
            isinstance(x, dict) and set(x) == fields and all(isinstance(v, str) and v.strip() for v in x.values())
            for x in facts[key]), key + " 需要实测证据")
    repository.require(isinstance(facts["boundary_gates"], list) and all(isinstance(x, str) and x.startswith("gate-") for x in facts["boundary_gates"]), "boundary gates 无效")
    repository.require(set(d.get("required_boundary_gates", [])).issubset(facts["boundary_gates"]), "计划调整丢失 gate 下限")
    repository.require(facts["mode"] != "TDD" or bool(old_plan["approved_seams"]), "恢复 TDD 需要既有 approved seams")
    target = directory.parent / uuid.uuid4().hex
    target.mkdir()
    record = {**facts, "kind": "execution-plan-adjustment", "dispatch": evidence.binding(args.dispatch),
              "base_commit": d["base_commit"], "observed_head": repository.sha(d["worktree"], "HEAD"),
              "original_plan": old_plan, "effective_plan": {**old_plan, "mode": facts["mode"]}}
    evidence.write(target / "plan-adjustment.json", record)
    result = dict(d, mode="resume", dispatch_path=str(target / "dispatch.json"), report_path=str(target / "report.json"),
                  report_schema_path=str(target / "report-schema.json"), receipt_schema_path=str(target / "receipt-schema.json"),
                  expected_plan_path=str(target / "expected-plan.json"), test_mode=facts["mode"],
                  plan_adjustment=evidence.binding(str(target / "plan-adjustment.json")),
                  required_boundary_gates=facts["boundary_gates"],
                  verification_dispatches=list(dict.fromkeys(d.get("verification_dispatches", []) + [args.dispatch])))
    # 保留 BASE、stage、models、prior_reviews；不是新的 writer 或阶段。
    evidence.write(result["expected_plan_path"], record["effective_plan"])
    evidence.write(result["report_schema_path"], report_io.verifier("executor", "--schema"))
    evidence.write(result["receipt_schema_path"], report_io.verifier("executor", "--receipt-schema"))
    evidence.write(result["dispatch_path"], result)
    return result

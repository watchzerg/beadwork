"""持久化必要上下文及直接派发者观察，不替代宿主任务结束确认。"""
from pathlib import Path
import uuid

import controller as c


def preflight_input(d):
    o = c.executor_ops()
    source = d.get('preflight_acceptance')
    c.require(source, '新 ticket 必须提供 preflight_acceptance 来源')
    accepted = c.read(o.bound(source))
    c.require(accepted.get('kind') == 'mechanical_acceptance' and accepted.get('role') == 'preflight'
              and accepted.get('status') == 'READY', '需要已验收 READY preflight')
    for key in ('dispatch', 'report', 'receipt'):
        c.require(c.digest(accepted[key + '_path']) == accepted[key + '_sha256'], 'preflight 来源已变化')
    pd, report, _ = c.inspect(accepted['dispatch_path'], accepted['report_path'], accepted['receipt_path'])
    c.require(pd['parent_id'] == d['parent_id'] and pd['repository_root'] == d['repository_root'], 'preflight 批次身份不符')
    plan = next((t['test_plan'] for t in report['tickets'] if t['id'] == d['ticket_id']), None)
    c.require(plan and plan['mode'] == d['test_mode'] and plan['approved_seams'] == d['approved_seams'], 'ticket 计划与 preflight 不符')
    c.require(set(plan['boundary_gates']) <= set(d['required_boundary_gates']), '派发遗漏 preflight gates')
    c.require(report['linked_spec'] == d['linked_spec'], 'linked spec 与 preflight 不符')
    d['plan_source'] = {'report': o.binding(accepted['report_path']), 'ticket_id': d['ticket_id']}
    d['environment_evidence'] = list(d.get('environment_evidence', [])) + [o.binding(d['sync_result'])]
    for item in d['environment_evidence']:
        o.bound(item)


def context_root(d):
    if d.get('ticket_root'):
        return Path(c.executor_ops().bound(d['ticket_root'])).parent
    return Path(d.get('attempt_path', Path(d['dispatch_path']).parent))


def contexts(d):
    o = c.executor_ops()
    root = context_root(d)
    previous = None
    sources = []
    for number, path in enumerate(sorted(root.glob('context-add-*.json')), 1):
        value = c.read(path)
        c.require(path.name == f'context-add-{number:06d}.json' and value['previous'] == previous, '上下文补充链不连续')
        for item in value['sources']:
            o.bound(item)
        sources.append(o.binding(str(path)))
        previous = sources[-1]
    return sources


def add_context(dispatch_path, facts):
    d = c.executor_ops().dispatch(dispatch_path)
    c.require(set(facts) == {'sources', 'reason'} and isinstance(facts['reason'], str) and facts['reason'].strip(),
              '上下文补充只接收来源与原因，不修改需求或派发身份')
    c.require(isinstance(facts['sources'], list) and facts['sources'], '缺少补充事实来源')
    for item in facts['sources']:
        c.executor_ops().bound(item)
    previous = contexts(d)
    path = context_root(d) / f'context-add-{len(previous) + 1:06d}.json'
    c.write(path, dict(facts, previous=previous[-1] if previous else None))
    return {'context_source': c.executor_ops().binding(str(path)), 'dispatch_path': dispatch_path}


def review_inputs(d, axis):
    o = c.executor_ops()
    writer = None
    prior = d.get('prior_reviews', [])
    if d.get('ticket_execution_version'):
        import ticket_execution
        value, _, _ = ticket_execution.checkpoints(d)
        writer = value['implementer_sources'][-1] if value['implementer_sources'] else None
    elif d.get('finalization_version') == 2:
        import final_state
        _, final_selection = final_state.selected(d)
        writer = final_selection['fixes'][-1] if final_selection['fixes'] else None
    previous_axis = None
    if prior:
        collection = c.read(o.bound(prior[-1]))
        previous_axis = collection['sources'][axis]
        for item in previous_axis.values():
            o.bound(item)
    if writer:
        for item in writer.values():
            o.bound(item)
        wd, report = c.read(o.bound(writer['dispatch'])), c.read(o.bound(writer['report']))
        c.require(wd['worktree'] == d['worktree'] and report['head_commit'] == c.sha(d['worktree'], 'HEAD'), 'review writer 现场不符')
    verification = list(report.get('verification_sources', [])) if writer else []
    gates = list(d.get('required_boundary_gates', []))
    gate_sources = []
    if writer:
        gates = list(dict.fromkeys(gates + report.get('required_boundary_gates', report.get('boundary_gates', []))))
    if d.get('finalization_version') == 2:
        import final_verification
        verification += [s for s in final_verification.snapshot(d) if s not in verification]
        gates, gate_sources = final_selection['gates'], final_selection['gate_sources']
    return {'writer_source': writer, 'prior_axis_source': previous_axis,
            'plan_source': d.get('plan_source'), 'plan_adjustment': d.get('plan_adjustment'),
            'expected_children': d.get('expected_children', []), 'context_sources': contexts(d),
            'verification_sources': verification,
            'stage_source': o.binding(d['dispatch_path']), 'required_boundary_gates': gates, 'gate_sources': gate_sources,
            'scope': 'ticket' if d['role'] == 'executor' else 'batch'}


def close(dispatch_path, report_path, facts):
    o = c.executor_ops()
    c.read(dispatch_path)
    c.require(Path(report_path).parent == Path(dispatch_path).parent, '收尾报告目录不符')
    required = {'task_id', 'stopped', 'observed_at', 'evidence', 'unresolved'}
    c.require(set(facts) == required and type(facts['stopped']) is bool and isinstance(facts['unresolved'], list), '收尾记录字段无效')
    c.require(all(isinstance(facts[k], str) and facts[k].strip() for k in ('task_id', 'observed_at', 'evidence')), '收尾观察缺少具体来源')
    c.require(not facts['stopped'] or not facts['unresolved'], '仍有未结束事项，不能确认 stopped')
    report = c.read(report_path)
    self_stopped = report.get('stopped_tasks', report.get('execution', {}).get('stopped_tasks'))
    c.require(self_stopped is not False or not facts['stopped'], '子 agent 与派发者停止事实矛盾，需先更正来源')
    path = Path(dispatch_path).parent / ('closure-' + uuid.uuid4().hex + '.json')
    c.write(path, dict(facts, dispatch=o.binding(dispatch_path), report=o.binding(report_path)))
    return {'closure_source': o.binding(str(path))}


def check_close(dispatch_path, report_path, source, required=True):
    c.require(source or not required, '缺少直接派发者的收尾确认来源')
    if not source:
        return None
    o = c.executor_ops()
    record = c.read(o.bound(source))
    c.require(type(record.get('stopped')) is bool and isinstance(record.get('unresolved'), list)
              and all(isinstance(record.get(k), str) and record[k].strip()
                      for k in ('task_id', 'observed_at', 'evidence')), '收尾观察字段无效')
    c.require(record['dispatch'] == o.binding(dispatch_path) and record['report'] == o.binding(report_path), '收尾来源与交付不符')
    report = c.read(report_path)
    advance = report.get('status', 'COMPLETED') in ('DONE', 'READY', 'READY_TO_MERGE', 'COMPLETED') or report.get('outcome') == 'code_failure'
    if advance:
        c.require(record['stopped'] and not record['unresolved'], '未确认任务停止，不能推进')
    return record

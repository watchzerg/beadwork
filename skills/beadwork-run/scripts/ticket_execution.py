"""单票协调、阶段检查点与 implementer 交付；只写证据，不派发 agent。"""
from pathlib import Path
from types import SimpleNamespace
import importlib.util
import hashlib
import json
import sys
import uuid
import controller as c

VERSION = 1
ROLES = ('implementer', 'standards', 'spec')


def ops():
    return c.executor_ops()


def source(dispatch, report, receipt):
    return {k: ops().binding(str(v)) for k, v in
            (('dispatch', dispatch), ('report', report), ('receipt', receipt))}


def resolve_source(item):
    c.require(set(item) == {'dispatch', 'report', 'receipt'}, '来源必须含 dispatch/report/receipt')
    paths = {k: ops().bound(v) for k, v in item.items()}
    c.require(all(paths[k].parent == paths['dispatch'].parent for k in ('report', 'receipt')), '来源目录不符')
    d, r, receipt = (ops().load(paths[k]) for k in ('dispatch', 'report', 'receipt'))
    c.require(receipt == {'status': r['status'], 'report_path': str(paths['report']),
                         'report_sha256': c.digest(paths['report'])}, '来源回执不符')
    c.require(d['dispatch_path'] == str(paths['dispatch']), '来源 dispatch 路径不符')
    return d, r


def root(d):
    if d.get('ticket_scope') == 'root':
        return d
    return ops().load(ops().bound(d['ticket_root']))


def same_ticket(a, b):
    keys = ('repository_root', 'worktree', 'branch', 'parent_id', 'ticket_id', 'base_commit')
    c.require(all(a.get(k) == b.get(k) for k in keys), '来源不属于同票同 BASE')


def checkpoints(d):
    r = root(d)
    folder = Path(r['dispatch_path']).parent
    files = sorted(folder.glob('checkpoint-*.json'))
    previous = None
    state = {'stage_dispatch': None, 'implementer_sources': [], 'stage_sources': [],
             'selected_stage': None, 'selected_review': None}
    for i, path in enumerate(files, 1):
        c.require(path.name == f'checkpoint-{i:06d}.json', '单票检查点不连续')
        entry = ops().load(path)
        c.require(entry['previous'] == previous and entry['root'] == ops().binding(r['dispatch_path']), '检查点链路或 root 已变化')
        c.require(entry['state_sha256'] == state_digest(entry['state']), '检查点状态已变化')
        state = entry['state']
        previous = ops().binding(str(path))
    return state, previous, len(files)


def state_digest(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def checkpoint(d, state):
    _, previous, count = checkpoints(d)
    r = root(d)
    path = Path(r['dispatch_path']).parent / f'checkpoint-{count + 1:06d}.json'
    c.write(path, {'root': ops().binding(r['dispatch_path']), 'previous': previous, 'state': state, 'state_sha256': state_digest(state)})
    return str(path)


def root_fields(d):
    c.require(not any(d.get(k) for k in ('previous_report', 'previous_receipt', 'continuation', 'stage', 'models')),
              'controller 只准备整票；阶段输入由 ticket-stage 管理')
    d.update(ticket_execution_version=VERSION, ticket_scope='root', start_head=d['base_commit'],
             coordinator_model=c.MODEL_LEVELS[2 if d.get('complex_ticket') else 0])


def resume_root(d):
    previous = ops().load(ops().absolute(d['previous_dispatch']))
    c.require(previous.get('ticket_scope') == 'root' and previous.get('ticket_execution_version') == VERSION,
              '恢复需要当前单票 root dispatch')
    same_ticket(previous, d)
    c.topology(previous)
    c.git(d['worktree'], 'merge-base', '--is-ancestor', d['base_commit'], 'HEAD')
    c.require(d.get('continuation', 'resume') == 'resume', 'controller 不推进 stage；使用原 root 恢复 executor')
    state, _, _ = checkpoints(previous)
    if state['selected_stage']:
        _, report = resolve_source(state['selected_stage'])
        c.require(report['status'] != 'DONE', '整票已完成，应验收关闭')
    return previous


def save_dispatch(d, folder, role):
    folder.mkdir(parents=True)
    d = dict(d, role=role, dispatch_path=str(folder / 'dispatch.json'), report_path=str(folder / 'report.json'),
             report_schema_path=str(folder / 'report-schema.json'), receipt_schema_path=str(folder / 'receipt-schema.json'))
    if role == 'implementer':
        for kind in ('schema', 'receipt-schema'):
            c.write(d['report_schema_path' if kind == 'schema' else 'receipt_schema_path'], worker('--' + kind))
        d['self_check_argv'] = [sys.executable, '-B', str(c.SCRIPTS / 'executor-operations.py'),
                               'implementer-check', '--dispatch', d['dispatch_path'], '--report', d['report_path']]
    else:
        c.write(d['report_schema_path'], c.verifier('executor', '--schema'))
        c.write(d['receipt_schema_path'], c.verifier('executor', '--receipt-schema'))
    c.write(d['dispatch_path'], d)
    return d


def worker(option, *args):
    result = json.loads(c.run([sys.executable, '-B', c.SCRIPTS / 'verify-worker.py', option, 'implementer', *args]))
    if option == '--check-report':
        c.require(result.get('ok'), 'implementer 报告校验失败：' + json.dumps(result, ensure_ascii=False))
    return result


def stage_result(d, state):
    selected = state['implementer_sources'][-1] if state['implementer_sources'] else None
    writer = ops().load(ops().bound(d['implementer_dispatch']))
    rounds = list(Path(d['dispatch_path']).parent.glob('review-*/round.json'))
    c.require(len(rounds) <= 1, '同 stage 出现多个 review round')
    return {'stage': d['stage'], 'stage_dispatch': d['dispatch_path'], 'implementer_dispatch': writer['dispatch_path'],
            'models': d['models'], 'prior_implementer': selected, 'selected_stage': state['selected_stage'],
            'selected_review': state['selected_review'],
            'review_round': str(rounds[0]) if rounds else None,
            'review_started': (Path(d['gate_repair_root']) / 'gate-review-started.json').exists()}


def prepare_stage(root_path, facts):
    r = ops().dispatch(root_path)
    c.require(r.get('ticket_scope') == 'root', 'ticket-stage 需要 executor root dispatch')
    c.require(set(facts) <= {'continuation', 'model_overrides', 'model_override_reason'}, 'stage 输入字段无效')
    c.topology(r)
    state, _, _ = checkpoints(r)
    continuation = facts.get('continuation', 'resume')
    c.require(continuation in ('resume', 'repair'), 'continuation 无效')
    previous = None
    if state['stage_dispatch']:
        previous = ops().load(ops().bound(state['stage_dispatch']))
        if continuation == 'resume':
            c.require(not facts.get('model_overrides'), '已有 stage 沿用模型；提前升级在新 stage 准备时指定')
            if state['selected_stage']:
                _, report = resolve_source(state['selected_stage'])
                c.require(report['outcome'] in ('interrupted', 'blocked'), '已完成或代码失败阶段不可作为中断恢复')
            return stage_result(previous, state)
        c.require(state['selected_stage'], '推进 stage 需要已验收的阶段报告')
        old, report = resolve_source(state['selected_stage'])
        check_stage(old, report)
        c.require(report['outcome'] == 'code_failure', '只有 code_failure 推进 stage')
        c.require(report['execution']['stopped_tasks'], '旧任务未确认停止')
        number = previous['stage'] + 1
    else:
        c.require(continuation == 'resume', '初次 stage 不接受 repair')
        number = 0
    c.require(number < 4, '四阶段已用尽，停止并保留现场')
    if previous:
        state['stage_sources'] = state['stage_sources'] + [state['selected_stage']]
    head = c.sha(r['worktree'], 'HEAD')
    if previous:
        c.require(head == report['head_commit'], '阶段交付后 HEAD 已变化')
    else:
        c.require(head == r['base_commit'] and not c.status(r['worktree']), 'stage 0 需要原 BASE 的干净现场')
    levels = dict(zip(ROLES, c.STAGE_MODELS[number]))
    if r.get('complex_ticket'):
        levels['implementer'] = max(levels['implementer'], 2)
        levels['standards'] = max(levels['standards'], 1)
    if previous:
        for role in ROLES:
            levels[role] = max(levels[role], c.MODEL_LEVELS.index(previous['models'][role]))
    overrides = facts.get('model_overrides', {})
    c.require(isinstance(overrides, dict) and set(overrides) <= set(ROLES), '模型角色无效')
    if overrides:
        c.require(isinstance(facts.get('model_override_reason'), str) and facts['model_override_reason'].strip(), '提前升级需记录理由')
    for role, model in overrides.items():
        c.require(model in c.MODEL_LEVELS and c.MODEL_LEVELS.index(model) >= levels[role], '模型只能升级')
        levels[role] = c.MODEL_LEVELS.index(model)
    folder = Path(r['dispatch_path']).parent / ('stage-' + str(number) + '-' + uuid.uuid4().hex)
    inherited = previous or r
    d = dict(inherited, ticket_scope='stage', ticket_root=ops().binding(root_path), stage=number,
             stage_base=head, start_head=head, mode='resume',
             models={role: c.MODEL_LEVELS[level] for role, level in levels.items()},
             model_override_reason=facts.get('model_override_reason'), gate_repair_root=str(folder),
             prior_reviews=(report.get('review') or {}).get('sources', []) if previous else [],
             prior_stages=state['stage_sources'], previous_stage=state['selected_stage'],
             verification_dispatches=[])
    if previous:
        for item in state['implementer_sources']:
            _, implementation = resolve_source(item)
            d['required_boundary_gates'] = list(dict.fromkeys(d.get('required_boundary_gates', []) + implementation['required_boundary_gates']))
    d.pop('implementer_dispatch', None)
    folder.mkdir()
    w = save_dispatch(dict(d, ticket_scope='implementer'), folder / 'implementer', 'implementer')
    d['implementer_dispatch'] = ops().binding(w['dispatch_path'])
    d = save_dispatch(d, folder / 'coordinator', 'executor')
    new_state = dict(state, stage_dispatch=ops().binding(d['dispatch_path']), implementer_sources=[],
                     selected_stage=None, selected_review=None)
    checkpoint(r, new_state)
    return stage_result(d, new_state)


def require_writer(d):
    """只允许当前未冻结阶段的 implementer 使用写入前检查和验证入口。"""
    c.require(d.get('role') == 'implementer', '单票源码 writer 必须为 implementer')
    state, _, _ = checkpoints(d)
    c.require(state['stage_dispatch'], '单票尚未建立 stage')
    stage = ops().load(ops().bound(state['stage_dispatch']))
    c.require(stage['implementer_dispatch'] == ops().binding(d['dispatch_path']), '不是当前 implementer dispatch')
    c.require(not (Path(stage['gate_repair_root']) / 'gate-review-started.json').exists(), 'review 已开始，writer 保持冻结')
    if state['selected_stage']:
        _, report = resolve_source(state['selected_stage'])
        c.require(report['outcome'] in ('interrupted', 'blocked'), '阶段已封存，不能继续旧 writer')
    if state['implementer_sources']:
        _, report = resolve_source(state['implementer_sources'][-1])
        c.require(report['outcome'] in ('interrupted', 'blocked'), '实现已交付，等待 executor 的 review 或下一 stage')


def implementer_schema(v):
    schema = v.executor_schema(v.axis_report_schema())
    schema['properties'].pop('review')
    schema['properties'].pop('execution')
    schema['required'].remove('review')
    schema.pop('allOf')
    schema['properties'].update(role={'const': 'implementer'}, ticket_id=v.TEXT,
        stage_base=v.SHA, stopped_tasks={'type': 'boolean'},
        verification_notes={'type': 'object', 'additionalProperties': {'type': 'string'}},
        verification_sources={'type': 'array', 'items': {'type': 'object'}},
        required_boundary_gates={'type': 'array', 'items': v.TEXT, 'uniqueItems': True})
    schema['required'] += ['role', 'ticket_id', 'stage', 'outcome', 'stage_base', 'stopped_tasks',
                           'verification_notes', 'required_boundary_gates']
    return schema


def implementer_errors(report, d, v):
    errors = v.schema_errors(report, implementer_schema(v))
    if errors:
        return errors
    for key in ('ticket_id', 'base_commit', 'stage', 'stage_base'):
        if report[key] != d.get(key):
            errors.append(key + ' 与 dispatch 不符')
    if d.get('role') != 'implementer' or d.get('ticket_scope') != 'implementer':
        errors.append('需要 implementer dispatch')
    if report['outcome'] in ('code_failure', 'interrupted') and report['status'] != 'BLOCKED':
        errors.append('代码失败和中断必须为 BLOCKED')
    if (report['outcome'] == 'passed') != (report['status'] == 'DONE'):
        errors.append('implementer 状态与 outcome 不符')
    if report['status'] == 'DONE':
        if not report['acceptance'] or not report['verification'] or report['blockers'] or report['requested_context'] or not report['stopped_tasks']:
            errors.append('成功交付缺少证据或仍有阻塞/运行任务')
        plan = report['test_plan']
        if not plan or (plan['mode'] == 'TDD' and not plan['red_evidence']):
            errors.append('成功交付缺少 test plan 或行为 red')
    elif not (report['blockers'] or report['requested_context']):
        errors.append('未完成交付需要原因')
    if report['test_plan'] and {k: report['test_plan'][k] for k in ('mode', 'approved_seams')} != ops().load(d['expected_plan_path']):
        errors.append('test plan 与执行计划不符')
    if not set(d.get('required_boundary_gates', [])).issubset(report['required_boundary_gates']):
        errors.append('丢失 boundary gate 下限')
    return errors


def verification_module():
    spec = importlib.util.spec_from_file_location('verification', c.SCRIPTS / 'run-verification.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def runs(d):
    paths = list(dict.fromkeys(d.get('verification_dispatches', []) + [d['dispatch_path']]))
    for path in paths:
        old = ops().load(path)
        same_ticket(d, old)
        for folder in sorted(Path(path).parent.glob('verification-*')):
            start = ops().load(folder / 'started.json')
            end = folder / 'result.json'
            if end.exists():
                yield start, ops().load(end), end


def verification_snapshot(d):
    entries = []
    for path in list(dict.fromkeys(d.get('verification_dispatches', []) + [d['dispatch_path']])):
        for folder in sorted(Path(path).parent.glob('verification-*')):
            start, result = folder / 'started.json', folder / 'result.json'
            entries.append({'started': ops().binding(str(start)),
                            'result': ops().binding(str(result)) if result.exists() else None})
    return entries


def check_implementation(d, report, live=False):
    c.validate_plan(d)
    snapshot = report.get('verification_sources')
    if live and snapshot is not None:
        c.require(snapshot == verification_snapshot(d), '实现交付须包含当前全部验证来源')
    rows = verification_module().collect(d['dispatch_path'], d.get('verification_dispatches', []),
                                         report['verification_notes'], report['status'], snapshot)
    c.require(report['verification'][:len(rows)] == rows, 'implementer 丢失或改写验证历史')
    head = report['head_commit']
    c.require(head, '实现报告需要当前 HEAD')
    c.git(d['worktree'], 'merge-base', '--is-ancestor', d['stage_base'], head)
    commits = c.git(d['worktree'], 'log', '--reverse', '--format=%H %s', d['base_commit'] + '..' + head).splitlines()
    expected = [dict(zip(('sha', 'subject'), line.split(' ', 1))) for line in commits]
    c.require(report['implementation_commits'] == expected, '实现提交列表不完整')
    c.check_batch_beads(d['worktree'], d['base_commit'], head)
    if live:
        c.topology(d)
        c.require(c.sha(d['worktree'], 'HEAD') == head, '实现交付 HEAD 已变化')
        c.require(not c.git(d['worktree'], 'status', '--porcelain=v1', '--untracked-files=all', '--', '.beads'), '.beads 有改动')
        if report['status'] == 'DONE':
            c.require(not c.status(d['worktree']), '实现通过需要干净现场')
    if report['status'] == 'DONE':
        required = {'gate-unit', *report['required_boundary_gates']}
        latest = {}
        for start, end, _ in sorted(runs(d), key=lambda row: row[0]['started_ns']):
            if start.get('delivery_attempt') is not None and start['before']['head'] == head:
                latest[start['argv'][3]] = (start, end)
        passed = {recipe for recipe, (start, end) in latest.items()
                  if start['before'] == end['after'] == {'head': head, 'status': ''}
                  and end['outcome'] == 'exited' and end['exit_code'] == 0
                  and end['process_group_gone'] is True}
        c.require(required <= passed, '交付 HEAD 缺少成功 gates：' + ', '.join(sorted(required - passed)))
    if report['outcome'] == 'code_failure':
        import gate_repair
        c.require(gate_repair.used_repairs(gate_repair.root(d)) == 3, '代码 gate 失败必须先用尽三次修复')
        c.require(any(start.get('delivery_attempt') == 3 and start['before'] == end['after']
                      and start['before'] == {'head': head, 'status': ''} and end['outcome'] == 'exited'
                      and type(end['exit_code']) is int and end['exit_code'] > 0 and end['process_group_gone'] is True
                      for start, end, _ in runs(d)), '缺少第三次修复后候选失败证据')


def implementer_check(dispatch_path, report_path):
    d = ops().dispatch(dispatch_path)
    c.require(d['role'] == 'implementer', '需要 implementer dispatch')
    c.require(Path(report_path).parent == Path(dispatch_path).parent, '实现报告目录不符')
    checked = worker('--check-report', report_path, '--expected', dispatch_path)
    report = ops().load(report_path)
    check_implementation(d, report, live=True)
    return {'status': report['status'], 'report_path': str(report_path), 'report_sha256': checked['report_sha256']}


def implementer_assemble(args):
    d = ops().dispatch(args.dispatch)
    report = ops().load(args.draft)
    fields = {'status', 'outcome', 'test_plan', 'acceptance', 'verification', 'requested_context', 'blockers', 'concerns',
              'verification_notes', 'stopped_tasks', 'required_boundary_gates'}
    c.require(set(report) == fields, 'implementer draft 字段不符')
    report['verification_sources'] = verification_snapshot(d)
    rows = verification_module().collect(args.dispatch, d.get('verification_dispatches', []), report['verification_notes'], report['status'], report['verification_sources'])
    report['verification'] = rows + report['verification']
    if report['test_plan'] is not None:
        c.require(set(report['test_plan']) == {'decision_source', 'red_evidence'}, 'test_plan 只填写判断依据与 red 证据')
        report['test_plan'] = {**ops().load(d['expected_plan_path']), **report['test_plan']}
    head = c.sha(d['worktree'], 'HEAD')
    commits = c.git(d['worktree'], 'log', '--reverse', '--format=%H %s', d['base_commit'] + '..' + head)
    report.update(role='implementer', ticket_id=d['ticket_id'], stage=d['stage'], stage_base=d['stage_base'],
                  base_commit=d['base_commit'], head_commit=head,
                  implementation_commits=[dict(zip(('sha', 'subject'), line.split(' ', 1))) for line in commits.splitlines()],
                  delivery_kind=('already_satisfied' if head == d['base_commit'] else 'changed') if report['status'] == 'DONE' else None)
    output = ops().output_path(args.output, Path(args.dispatch).parent)
    c.write(output, report)
    return implementer_check(args.dispatch, str(output))


def accept_implementer(stage_path, report_path, receipt_path):
    d = ops().dispatch(stage_path)
    state, _, _ = checkpoints(d)
    c.require(state['stage_dispatch'] == ops().binding(stage_path), '不是当前 stage')
    wpath = ops().bound(d['implementer_dispatch'])
    item = source(wpath, report_path, receipt_path)
    w, report = resolve_source(item)
    implementer_check(str(wpath), report_path)
    c.require(report['stopped_tasks'], 'implementer 任务尚未停止')
    if state['implementer_sources'] and state['implementer_sources'][-1] == item:
        return {'accepted': True, 'source': item}
    if state['selected_stage']:
        _, selected = resolve_source(state['selected_stage'])
        c.require(selected['outcome'] in ('interrupted', 'blocked'), '阶段已封存，不能用新实现报告覆盖')
    if state['implementer_sources']:
        _, prior = resolve_source(state['implementer_sources'][-1])
        c.require(prior['head_commit'] == report['head_commit'] or prior['outcome'] in ('interrupted', 'blocked'), '实现已交付，报告更正不能改变 HEAD')
        if prior['outcome'] in ('passed', 'code_failure'):
            c.require(report['outcome'] == prior['outcome'], '已验收实现终态不能改报中断或外部阻塞')
    c.require(not (Path(d['gate_repair_root']) / 'gate-review-started.json').exists(), 'review 后只能更正审查/阶段报告')
    state['implementer_sources'].append(item)
    state['selected_stage'] = None
    checkpoint(d, state)
    return {'accepted': True, 'source': item}


def review_ready(d):
    state, _, _ = checkpoints(d)
    c.require(state['stage_dispatch'] == ops().binding(d['dispatch_path']) and state['implementer_sources'], 'review 需要当前 stage 已验收的 implementer')
    w, report = resolve_source(state['implementer_sources'][-1])
    worker('--check-report', state['implementer_sources'][-1]['report']['path'],
           state['implementer_sources'][-1]['receipt']['path'], '--expected', w['dispatch_path'])
    check_implementation(w, report, live=True)
    c.require(report['status'] == 'DONE' and report['stopped_tasks'], '实现未通过，不能 review')
    c.require(not any(Path(d['dispatch_path']).parent.glob('review-*/round.json')), '每 stage 只准备一轮 review；恢复使用原 round')


def select_review(d, collection_path):
    """完整审查先写入检查点；同 round 更正使旧阶段交付失效。"""
    state, _, _ = checkpoints(d)
    c.require(state['stage_dispatch'] == ops().binding(d['dispatch_path']), '只能选择当前 stage 的 review')
    item = ops().binding(str(collection_path))
    collection = ops().load(ops().bound(item))
    round_path = ops().bound(collection['round'])
    record = ops().load(round_path)
    c.require(record['dispatch'] == state['stage_dispatch']
              and round_path.parent.parent == Path(d['dispatch_path']).parent,
              'review round 不属于当前 stage')
    if state['selected_review']:
        previous = ops().load(ops().bound(state['selected_review']))
        c.require(previous['round'] == collection['round'], 'review 更正必须沿用同一 round 和 BASE/HEAD')
    if state['selected_review'] != item:
        state.update(selected_review=item, selected_stage=None)
        checkpoint(d, state)


def check_selected_review(d, sources):
    """只约束当前交付；历史阶段仍按各自绑定的原始证据校验。"""
    state, _, _ = checkpoints(d)
    if state['stage_dispatch'] == ops().binding(d['dispatch_path']):
        expected = d['prior_reviews'] + ([state['selected_review']] if state['selected_review'] else [])
        c.require(sources == expected, '阶段报告必须保留检查点选中的完整 review；更正后需重新组装')


def check_stage(d, report):
    c.require(d.get('ticket_scope') == 'stage', '需要阶段 dispatch')
    execution = report.get('execution')
    c.require(execution and execution['stage_dispatch'] == ops().binding(d['dispatch_path'])
              and execution['root'] == d['ticket_root'], '阶段报告缺少绑定身份')
    c.require(execution['previous_stages'] == d['prior_stages'], '阶段报告丢失历史')
    check_selected_review(d, (report.get('review') or {}).get('sources', []))
    previous = None
    for item in d['prior_stages']:
        old, prior = resolve_source(item)
        same_ticket(d, old)
        c.require(old['stage'] == (0 if previous is None else previous + 1), '历史 stage 不连续')
        check_stage(old, prior)
        c.require(prior['outcome'] == 'code_failure', '只有代码失败可推进阶段')
        previous = old['stage']
    c.require(d['stage'] == (0 if previous is None else previous + 1), 'stage 计数不符')
    c.require(d['stage_base'] == (resolve_source(d['prior_stages'][-1])[1]['head_commit'] if d['prior_stages'] else d['base_commit']), 'stage 起始 HEAD 与前序交付不符')
    sources = execution['implementers']
    for item in sources:
        w, implementation = resolve_source(item)
        same_ticket(d, w)
        c.require(w['stage'] == d['stage'] and w['gate_repair_root'] == d['gate_repair_root'], '实现来源不属于本阶段')
        worker('--check-report', item['report']['path'], item['receipt']['path'], '--expected', w['dispatch_path'])
        check_implementation(w, implementation)
    if sources:
        c.require(implementation['head_commit'] == report['head_commit'], '阶段 HEAD 与最后实现交付不符')
        c.require(all(row in report['verification'] for row in implementation['verification']), '阶段报告丢失实现验证')
    new_review = len((report.get('review') or {}).get('sources', [])) > len(d['prior_reviews'])
    if new_review:
        c.require(all(axis['reviewed_head'] == report['head_commit'] for axis in report['review']['final'].values()), '当前 review 未覆盖本阶段交付 HEAD')
    if report['status'] == 'DONE' or new_review:
        c.require(sources and implementation['status'] == 'DONE', 'review/完成需要实现通过')
    if sources and implementation['outcome'] == 'code_failure' and not new_review:
        c.require(report['outcome'] == 'code_failure', 'implementer 代码失败不能改报中断或外部阻塞')
    if report['outcome'] == 'code_failure' and not new_review:
        c.require(sources and implementation['outcome'] == 'code_failure', '缺少 implementer gate 失败交付')
    if report['status'] == 'DONE' or report['outcome'] == 'code_failure':
        c.require(execution['stopped_tasks'], '成功或阶段推进必须确认任务结束')
    c.check_stage_report_core(d, report)


def assemble_stage(args):
    d = ops().dispatch(args.dispatch)
    state, _, _ = checkpoints(d)
    c.require(state['stage_dispatch'] == ops().binding(args.dispatch), '不是当前 stage')
    check_selected_review(d, [ops().binding(str(path)) for path in args.review])
    report = ops().load(args.draft)
    stopped = report.pop('stopped_tasks')
    c.require(type(stopped) is bool, 'stopped_tasks 必须为布尔值')
    extra = {'execution': {'root': d['ticket_root'], 'stage_dispatch': ops().binding(args.dispatch),
                          'previous_stages': d['prior_stages'], 'implementers': state['implementer_sources'],
                          'stopped_tasks': stopped}}
    # 原组装器仍负责 Git、plan 与双轴原始证据；实现日志由已验收报告注入。
    verification = []
    for item in d['prior_stages']:
        _, prior = resolve_source(item)
        verification += prior['verification']
    for item in state['implementer_sources']:
        _, implementation = resolve_source(item)
        verification += implementation['verification']
    report['verification'] = list({json.dumps(row, sort_keys=True): row for row in verification + report['verification']}.values())
    draft = Path(args.dispatch).parent / ('assembly-draft-' + uuid.uuid4().hex + '.json')
    c.write(draft, report)
    receipt = ops().assemble(SimpleNamespace(dispatch=args.dispatch, draft=str(draft), output=args.output,
                                             review=args.review, verification_dispatch=[], report_extra=extra))
    receipt_path = Path(args.output).with_name(Path(args.output).stem + '-receipt.json')
    c.write(receipt_path, receipt)
    item = source(args.dispatch, args.output, receipt_path)
    state['selected_stage'] = item
    checkpoint(d, state)
    return receipt


def check_ticket(d, report):
    c.require(d.get('ticket_scope') == 'root', 'controller 只验收整票 root')
    state, _, _ = checkpoints(d)
    c.require(state['selected_stage'], '整票没有已验收的阶段交付')
    stage, selected = resolve_source(state['selected_stage'])
    c.require(selected == report, 'root 报告必须原样引用选中的阶段报告')
    c.require(state['stage_dispatch'] == ops().binding(stage['dispatch_path']), '选中阶段不是当前阶段')
    c.require(report['execution']['implementers'] == state['implementer_sources'], '实现来源不完整')
    check_stage(stage, report)
    if report['outcome'] == 'code_failure':
        c.require(stage['stage'] == 3, '未耗尽 stage 的代码失败由 executor 内部处理')
    return stage


def deliver(root_path, output):
    d = ops().dispatch(root_path)
    state, _, _ = checkpoints(d)
    c.require(state['selected_stage'], '需要先组装阶段报告')
    _, report = resolve_source(state['selected_stage'])
    check_ticket(d, report)
    target = ops().output_path(output, Path(root_path).parent)
    c.write(target, Path(ops().bound(state['selected_stage']['report'])).read_text())
    return ops().check_report(root_path, str(target))


def adapt_plan(args):
    d = ops().dispatch(args.dispatch)
    c.require(d.get('ticket_scope') == 'stage', '执行计划由当前 stage executor 核准')
    state, _, _ = checkpoints(d)
    c.require(state['stage_dispatch'] == ops().binding(args.dispatch), '不是当前执行上下文')
    c.require(not (Path(d['gate_repair_root']) / 'gate-review-started.json').exists(), 'review 后不能适配计划')
    adjusted = c.adapt_plan(args)
    old_writer = ops().load(ops().bound(d['implementer_dispatch']))
    adjusted['verification_dispatches'] = []
    folder = Path(adjusted['dispatch_path']).parent / 'adapted'
    writer = dict(adjusted, ticket_scope='implementer',
                  verification_dispatches=list(dict.fromkeys(old_writer.get('verification_dispatches', []) + [old_writer['dispatch_path']])))
    writer = save_dispatch(writer, folder / 'implementer', 'implementer')
    adjusted['implementer_dispatch'] = ops().binding(writer['dispatch_path'])
    adjusted = save_dispatch(adjusted, folder / 'coordinator', 'executor')
    state.update(stage_dispatch=ops().binding(adjusted['dispatch_path']), selected_stage=None)
    checkpoint(d, state)
    return stage_result(adjusted, state)

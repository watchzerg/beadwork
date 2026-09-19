"""最终验收的明确选择；检查点只追加，宿主任务收尾由派发者确认。"""

from pathlib import Path
import hashlib
import json
import uuid

import evidence
import handoff
import repository
import workflow_contract


def strict(d):
    return workflow_contract.current(d) and d.get('role') in ('finalizer', 'fixer') and 'attempt_id' in d


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def state(d):
    previous = None
    value = {'current': None, 'stages': {}, 'context_sources': []}
    files = sorted(Path(d['attempt_path']).glob('checkpoint-*.json'))
    for number, path in enumerate(files, 1):
        item = evidence.read(path)
        repository.require(path.name == f'checkpoint-{number:06d}.json' and item['previous'] == previous,
                  '最终检查点链不连续')
        repository.require(item['attempt_id'] == d['attempt_id'] and item['state_sha256'] == digest(item['state']),
                  '最终检查点身份或状态已变化')
        value = item['state']
        previous = evidence.binding(str(path))
    return value, previous, len(files)


def save(d, value):
    _, previous, number = state(d)
    evidence.write(Path(d['attempt_path']) / f'checkpoint-{number + 1:06d}.json',
            {'attempt_id': d['attempt_id'], 'previous': previous, 'state': value, 'state_sha256': digest(value)})


def selected(d, current=True):
    value, _, _ = state(d)
    item = value['stages'].get(str(d.get('stage')))
    repository.require(item is not None, '缺少最终阶段检查点')
    repository.require(item['dispatch'] == evidence.binding(d['dispatch_path']), '阶段 dispatch 与检查点不符')
    if current:
        repository.require(value['current'] == d['stage'], '旧最终阶段已封存')
    return value, item


def start(d, fixer):
    value, _, _ = state(d)
    repository.require(str(d['stage']) not in value['stages'], '最终阶段已存在')
    gates = list(d['required_boundary_gates'])
    sources = list(d['prior_gate_sources'])
    if value['current'] is not None:
        old = value['stages'][str(value['current'])]
        gates = list(dict.fromkeys(gates + old['gates']))
        sources += [s for s in old['gate_sources'] if s not in sources]
    value['current'] = d['stage']
    value['stages'][str(d['stage'])] = {
        'dispatch': evidence.binding(d['dispatch_path']),
        'fixer': evidence.binding(fixer) if fixer else None,
        'fixes': list(d['prior_fixes']), 'round_path': None, 'round': None,
        'review': None, 'report': None, 'closures': {}, 'gates': gates, 'gate_sources': sources}
    save(d, value)


def gates(d, names, sources):
    value, item = selected(d)
    repository.require(isinstance(names, list) and all(isinstance(g, str) and g.startswith('gate-') for g in names),
              'boundary gates 无效')
    repository.require(set(names) <= {s['gate'] for s in sources} | set(item['gates']), '新增 gate 缺少来源')
    item['gates'] = list(dict.fromkeys(item['gates'] + names))
    item['gate_sources'] += [s for s in sources if s not in item['gate_sources']]
    save(d, value)


def reserve_review(d, resume=False):
    value, item = selected(d)
    if item['round_path']:
        repository.require(resume and item['round'] is None, '本阶段已有 review；复用原 round 或更正报告')
        return Path(item['round_path']).parent
    repository.require(not resume, '没有待恢复的 review 准备')
    folder = Path(d['dispatch_path']).parent / ('review-' + uuid.uuid4().hex)
    item['round_path'] = str(folder / 'round.json')
    item['report'] = None
    save(d, value)
    return folder


def bind_round(d, path):
    value, item = selected(d)
    repository.require(item['round_path'] == str(path), 'review round 未获当前阶段选择')
    item['round'] = evidence.binding(str(path))
    save(d, value)


def select_review(d, path):
    value, item = selected(d)
    collection = evidence.read(path)
    repository.require(item['round'] == collection['round'], '只能选择原 round 的审查或更正')
    item['review'] = evidence.binding(str(path))
    item['report'] = None
    save(d, value)


def select_report(d, report, receipt):
    value, item = selected(d)
    item['report'] = {k: evidence.binding(str(p)) for k, p in
                      (('dispatch', d['dispatch_path']), ('report', report), ('receipt', receipt))}
    # review 准备/更正会清除阶段选择，但已核对的运行收尾说明仍需用于后续验收。
    item['verification_notes_source'] = item['report']['report']
    save(d, value)


def check_sources(d, report):
    _, item = selected(d, current=False)
    reviews = list(d['prior_reviews']) + ([item['review']] if item['review'] else [])
    repository.require(report['review_sources'] == reviews, '阶段报告必须保留已选 review；更正后需重新组装')
    repository.require(report['fix_sources'] == item['fixes'], '阶段报告必须保留已验收 fixer 来源')
    repository.require(set(item['gates']) <= set(report['boundary_gates']), '报告丢失累计 boundary gates')
    repository.require(all(s in report['gate_sources'] for s in item['gate_sources']), '报告丢失累计 gate 来源')


def check_delivery(root, report):
    value, _, _ = state(root)
    repository.require(value['current'] == report['stage'], '交付不是当前最终阶段')
    chosen = value['stages'][str(value['current'])]['report']
    repository.require(chosen is not None, '缺少已选阶段报告或更正后尚未组装')
    repository.require(evidence.read(evidence.bound(chosen['report'])) == report, '交付不是明确选中的阶段报告')


def result(d):
    _, item = selected(d)
    writer = item['fixer']
    current_fix = None
    if item['fixes'] and evidence.read(evidence.bound(item['fixes'][-1]['dispatch']))['stage'] == d['stage']:
        current_fix = evidence.read(evidence.bound(item['fixes'][-1]['report']))
    if item['round_path'] or (current_fix and (current_fix['status'] == 'DONE' or not current_fix['stopped_tasks'])):
        writer = None
    return {'stage_path': d['dispatch_path'], 'stage': d['stage'], 'models': d['models'],
            'fixer_dispatch': str(evidence.bound(writer)) if writer else None,
            'selected_fixer': item['fixes'][-1] if item['fixes'] else None,
            'review_round': item['round_path'], 'selected_review': item['review'], 'selected_stage': item['report'],
            'context_sources': handoff.contexts(d)}


def require_writer(d):
    stage = evidence.read(evidence.bound(d['stage_dispatch']))
    _, item = selected(stage)
    repository.require(item['fixer'] == evidence.binding(d['dispatch_path']), '不是当前 fixer')
    repository.require(not item['round_path'], 'review 已开始，fixer 不可继续写入')
    if item['fixes'] and item['fixes'][-1]['dispatch'] == item['fixer']:
        prior = evidence.read(evidence.bound(item['fixes'][-1]['report']))
        repository.require(prior['outcome'] in ('blocked', 'interrupted'), 'fixer 已交付终态')
        repository.require(prior['stopped_tasks'], '旧 fixer 任务未确认停止')

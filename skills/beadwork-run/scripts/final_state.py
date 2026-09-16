"""最终验收的明确选择；检查点只追加，宿主任务收尾由派发者确认。"""
import hashlib
import json
from pathlib import Path
import uuid

import controller as c


def strict(d):
    return d.get('finalization_version') == 2


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def state(d):
    previous = None
    value = {'current': None, 'stages': {}, 'context_sources': []}
    files = sorted(Path(d['attempt_path']).glob('checkpoint-*.json'))
    for number, path in enumerate(files, 1):
        item = c.read(path)
        c.require(path.name == f'checkpoint-{number:06d}.json' and item['previous'] == previous,
                  '最终检查点链不连续')
        c.require(item['attempt_id'] == d['attempt_id'] and item['state_sha256'] == digest(item['state']),
                  '最终检查点身份或状态已变化')
        value = item['state']
        previous = c.executor_ops().binding(str(path))
    return value, previous, len(files)


def save(d, value):
    _, previous, number = state(d)
    c.write(Path(d['attempt_path']) / f'checkpoint-{number + 1:06d}.json',
            {'attempt_id': d['attempt_id'], 'previous': previous, 'state': value, 'state_sha256': digest(value)})


def selected(d, current=True):
    value, _, _ = state(d)
    item = value['stages'].get(str(d.get('stage')))
    c.require(item is not None, '缺少最终阶段检查点')
    c.require(item['dispatch'] == c.executor_ops().binding(d['dispatch_path']), '阶段 dispatch 与检查点不符')
    if current:
        c.require(value['current'] == d['stage'], '旧最终阶段已封存')
    return value, item


def start(d, fixer):
    value, _, _ = state(d)
    c.require(str(d['stage']) not in value['stages'], '最终阶段已存在')
    gates = list(d['required_boundary_gates'])
    sources = list(d['prior_gate_sources'])
    if value['current'] is not None:
        old = value['stages'][str(value['current'])]
        gates = list(dict.fromkeys(gates + old['gates']))
        sources += [s for s in old['gate_sources'] if s not in sources]
    value['current'] = d['stage']
    value['stages'][str(d['stage'])] = {
        'dispatch': c.executor_ops().binding(d['dispatch_path']),
        'fixer': c.executor_ops().binding(fixer) if fixer else None,
        'fixes': list(d['prior_fixes']), 'round_path': None, 'round': None,
        'review': None, 'report': None, 'closures': {}, 'gates': gates, 'gate_sources': sources}
    save(d, value)


def gates(d, names, sources):
    value, item = selected(d)
    c.require(isinstance(names, list) and all(isinstance(g, str) and g.startswith('gate-') for g in names),
              'boundary gates 无效')
    c.require(set(names) <= {s['gate'] for s in sources} | set(item['gates']), '新增 gate 缺少来源')
    item['gates'] = list(dict.fromkeys(item['gates'] + names))
    item['gate_sources'] += [s for s in sources if s not in item['gate_sources']]
    save(d, value)


def reserve_review(d, resume=False):
    value, item = selected(d)
    if item['round_path']:
        c.require(resume and item['round'] is None, '本阶段已有 review；复用原 round 或更正报告')
        return Path(item['round_path']).parent
    c.require(not resume, '没有待恢复的 review 准备')
    folder = Path(d['dispatch_path']).parent / ('review-' + uuid.uuid4().hex)
    item['round_path'] = str(folder / 'round.json')
    item['report'] = None
    save(d, value)
    return folder


def bind_round(d, path):
    value, item = selected(d)
    c.require(item['round_path'] == str(path), 'review round 未获当前阶段选择')
    item['round'] = c.executor_ops().binding(str(path))
    save(d, value)


def select_review(d, path):
    value, item = selected(d)
    collection = c.read(path)
    c.require(item['round'] == collection['round'], '只能选择原 round 的审查或更正')
    item['review'] = c.executor_ops().binding(str(path))
    item['report'] = None
    save(d, value)


def select_report(d, report, receipt):
    value, item = selected(d)
    item['report'] = {k: c.executor_ops().binding(str(p)) for k, p in
                      (('dispatch', d['dispatch_path']), ('report', report), ('receipt', receipt))}
    save(d, value)


def check_sources(d, report):
    _, item = selected(d, current=False)
    reviews = list(d['prior_reviews']) + ([item['review']] if item['review'] else [])
    c.require(report['review_sources'] == reviews, '阶段报告必须保留已选 review；更正后需重新组装')
    c.require(report['fix_sources'] == item['fixes'], '阶段报告必须保留已验收 fixer 来源')
    c.require(set(item['gates']) <= set(report['boundary_gates']), '报告丢失累计 boundary gates')
    c.require(all(s in report['gate_sources'] for s in item['gate_sources']), '报告丢失累计 gate 来源')


def check_delivery(root, report):
    value, _, _ = state(root)
    c.require(value['current'] == report['stage'], '交付不是当前最终阶段')
    chosen = value['stages'][str(value['current'])]['report']
    c.require(chosen is not None, '缺少已选阶段报告或更正后尚未组装')
    c.require(c.read(c.executor_ops().bound(chosen['report'])) == report, '交付不是明确选中的阶段报告')


def result(d):
    _, item = selected(d)
    writer = item['fixer']
    current_fix = None
    if item['fixes'] and c.read(c.executor_ops().bound(item['fixes'][-1]['dispatch']))['stage'] == d['stage']:
        current_fix = c.read(c.executor_ops().bound(item['fixes'][-1]['report']))
    if item['round_path'] or (current_fix and (current_fix['status'] == 'DONE' or not current_fix['stopped_tasks'])):
        writer = None
    return {'stage_path': d['dispatch_path'], 'stage': d['stage'], 'models': d['models'],
            'fixer_dispatch': str(c.executor_ops().bound(writer)) if writer else None,
            'selected_fixer': item['fixes'][-1] if item['fixes'] else None,
            'review_round': item['round_path'], 'selected_review': item['review'], 'selected_stage': item['report'],
            'context_sources': __import__('handoff').contexts(d)}

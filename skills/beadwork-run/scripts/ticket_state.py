"""单票检查点、当前 writer 与 review 选择；不执行阶段或报告验收。"""

from pathlib import Path
import hashlib
import json
import uuid

import evidence
import repository

def source(dispatch, report, receipt):
    return {k: evidence.binding(str(v)) for k, v in
            (('dispatch', dispatch), ('report', report), ('receipt', receipt))}


def resolve_source(item):
    repository.require(set(item) == {'dispatch', 'report', 'receipt'}, '来源必须含 dispatch/report/receipt')
    paths = {k: evidence.bound(v) for k, v in item.items()}
    repository.require(all(paths[k].parent == paths['dispatch'].parent for k in ('report', 'receipt')), '来源目录不符')
    d, r, receipt = (evidence.read(paths[k]) for k in ('dispatch', 'report', 'receipt'))
    repository.require(receipt == {'status': r['status'], 'report_path': str(paths['report']),
                         'report_sha256': evidence.digest(paths['report'])}, '来源回执不符')
    repository.require(d['dispatch_path'] == str(paths['dispatch']), '来源 dispatch 路径不符')
    return d, r


def root(d):
    if d.get('ticket_scope') == 'root':
        return d
    return evidence.read(evidence.bound(d['ticket_root']))


def checkpoints(d):
    r = root(d)
    folder = Path(r['dispatch_path']).parent
    files = sorted(folder.glob('checkpoint-*.json'))
    previous = None
    state = {'stage_dispatch': None, 'implementer_sources': [], 'stage_sources': [],
             'selected_stage': None, 'selected_review': None,
             'review_round_path': None, 'review_round': None}
    for i, path in enumerate(files, 1):
        repository.require(path.name == f'checkpoint-{i:06d}.json', '单票检查点不连续')
        entry = evidence.read(path)
        repository.require(entry['previous'] == previous and entry['root'] == evidence.binding(r['dispatch_path']), '检查点链路或 root 已变化')
        repository.require(entry['state_sha256'] == state_digest(entry['state']), '检查点状态已变化')
        state = entry['state']
        previous = evidence.binding(str(path))
    # v1 早期 checkpoint 没有累计 gate 字段；从已绑定来源确定性补齐，
    # 下一次追加 checkpoint 时写入新状态，不改写历史文件。
    state = dict(state)
    gates = list(state.get('required_boundary_gates', r.get('required_boundary_gates', [])))
    gate_sources = list(state.get('gate_sources', []))
    sources = list(state.get('stage_sources', [])) + list(state.get('implementer_sources', []))
    for source_item in sources:
        _, report = resolve_source(source_item)
        for gate in report.get('required_boundary_gates', report.get('boundary_gates', [])):
            if gate not in gates:
                gates.append(gate)
            marker = {'gate': gate, 'report': source_item['report']}
            if marker not in gate_sources:
                gate_sources.append(marker)
    state['required_boundary_gates'] = gates
    state['gate_sources'] = gate_sources
    state.setdefault('review_round_path', None)
    state.setdefault('review_round', None)
    return state, previous, len(files)


def state_digest(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def checkpoint(d, state):
    _, previous, count = checkpoints(d)
    r = root(d)
    path = Path(r['dispatch_path']).parent / f'checkpoint-{count + 1:06d}.json'
    evidence.write(path, {'root': evidence.binding(r['dispatch_path']), 'previous': previous, 'state': state, 'state_sha256': state_digest(state)})
    return str(path)


def require_writer(d):
    """只允许当前未冻结阶段的 implementer 使用写入前检查和验证入口。"""
    repository.require(d.get('role') == 'implementer', '单票源码 writer 必须为 implementer')
    state, _, _ = checkpoints(d)
    repository.require(state['stage_dispatch'], '单票尚未建立 stage')
    stage = evidence.read(evidence.bound(state['stage_dispatch']))
    repository.require(stage['implementer_dispatch'] == evidence.binding(d['dispatch_path']), '不是当前 implementer dispatch')
    repository.require(not (Path(stage['gate_repair_root']) / 'gate-review-started.json').exists(), 'review 已开始，writer 保持冻结')
    if state['selected_stage']:
        _, report = resolve_source(state['selected_stage'])
        repository.require(report['outcome'] in ('interrupted', 'blocked'), '阶段已封存，不能继续旧 writer')
    if state['implementer_sources']:
        _, report = resolve_source(state['implementer_sources'][-1])
        repository.require(report['outcome'] in ('interrupted', 'blocked'), '实现已交付，等待 executor 的 review 或下一 stage')


def reserve_review(d, resume=False):
    state, _, _ = checkpoints(d)
    repository.require(state['stage_dispatch'] == evidence.binding(d['dispatch_path']), '只能为当前 stage 准备 review')
    if state['review_round_path']:
        repository.require(resume and state['review_round'] is None,
                  '本阶段已有 review；复用原 round 或更正报告')
        return Path(state['review_round_path']).parent
    repository.require(not resume, '没有待恢复的 review 准备')
    folder = Path(d['dispatch_path']).parent / ('review-' + uuid.uuid4().hex)
    state['review_round_path'] = str(folder / 'round.json')
    state['selected_stage'] = None
    checkpoint(d, state)
    return folder


def bind_review_round(d, path):
    state, _, _ = checkpoints(d)
    repository.require(state['stage_dispatch'] == evidence.binding(d['dispatch_path'])
              and state['review_round_path'] == str(path), 'review round 未获当前 stage 选择')
    binding = evidence.binding(str(path))
    if state['review_round'] != binding:
        state['review_round'] = binding
        checkpoint(d, state)


def select_review(d, collection_path):
    """完整审查先写入检查点；同 round 更正使旧阶段交付失效。"""
    state, _, _ = checkpoints(d)
    repository.require(state['stage_dispatch'] == evidence.binding(d['dispatch_path']), '只能选择当前 stage 的 review')
    item = evidence.binding(str(collection_path))
    collection = evidence.read(evidence.bound(item))
    round_path = evidence.bound(collection['round'])
    record = evidence.read(round_path)
    repository.require(record['dispatch'] == state['stage_dispatch']
              and round_path.parent.parent == Path(d['dispatch_path']).parent,
              'review round 不属于当前 stage')
    repository.require(state['review_round'] == collection['round'], '只能选择检查点绑定的 review round')
    if state['selected_review']:
        previous = evidence.read(evidence.bound(state['selected_review']))
        repository.require(previous['round'] == collection['round'], 'review 更正必须沿用同一 round 和 BASE/HEAD')
    if state['selected_review'] != item:
        state.update(selected_review=item, selected_stage=None)
        checkpoint(d, state)


def check_selected_review(d, sources):
    """只约束当前交付；历史阶段仍按各自绑定的原始证据校验。"""
    state, _, _ = checkpoints(d)
    if state['stage_dispatch'] == evidence.binding(d['dispatch_path']):
        expected = d['prior_reviews'] + ([state['selected_review']] if state['selected_review'] else [])
        repository.require(sources == expected, '阶段报告必须保留检查点选中的完整 review；更正后需重新组装')

"""每个逻辑阶段最多三次交付 gate 修正；仅记录事实，不判断代码根因。"""
from pathlib import Path
import json
import controller as c
import workflow_policy

MAX_REPAIRS = workflow_policy.MAX_GATE_REPAIRS


def inherit(d, previous=None):
    # 准备入口覆盖调用者字段；同阶段恢复共用原证据目录。
    d['gate_repair_root'] = (previous.get('gate_repair_root', str(Path(previous['dispatch_path']).parent))
                             if previous and previous.get('stage') == d['stage']
                             else str(Path(d['dispatch_path']).parent))


def root(d):
    p = Path(d.get('gate_repair_root', str(Path(d['dispatch_path']).parent)))
    c.require(p.is_absolute() and p.resolve() == p and p.is_dir(), 'gate 修正证据目录无效')
    return p


def record(path, value):
    try:
        with path.open('x') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    except FileExistsError:
        c.require(c.read(path) == value, '本阶段已有不同的 gate 修正记录')


def repair_path(p, number, candidate=False):
    # 保留第一轮既有路径，恢复旧证据时直接计为已使用一次。
    suffix = '' if number == 1 else f'-{number}'
    kind = '-candidate' if candidate else ''
    return p / f'gate-repair{kind}{suffix}.json'


def used_repairs(p):
    present = [repair_path(p, n).exists() for n in range(1, MAX_REPAIRS + 1)]
    used = sum(present)
    c.require(present == [True] * used + [False] * (MAX_REPAIRS - used), 'gate 修正记录不连续')
    return used


def freeze(d):
    p = root(d)
    used = used_repairs(p)
    if used:
        candidate = repair_path(p, used, candidate=True)
        c.require(candidate.exists() and c.read(candidate)['head'] == c.sha(d['worktree'], 'HEAD'),
                  'review HEAD 必须是当前修正候选')
    record(p / 'gate-review-started.json', {'stage': d['stage']})


def delivery(d, before):
    c.require(d['role'] in ('executor', 'implementer', 'fixer'), '交付验证需要 writer dispatch')
    c.require(not d.get('ticket_execution_version') or d['role'] == 'implementer', '单票交付验证仅由 implementer 执行')
    if d.get('ticket_execution_version'):
        import ticket_execution
        ticket_execution.require_writer(d)
    c.require(not before['status'], '交付验证需要干净 HEAD')
    p = root(d)
    c.require(not (p / 'gate-review-started.json').exists(), 'review 已开始，源码与验证候选保持冻结')
    used = used_repairs(p)
    if used:
        record(repair_path(p, used, candidate=True), {'head': before['head']})
    return used


def begin(args):
    source = Path(args.dispatch).resolve()
    d = c.read(source)
    c.require(d.get('dispatch_path') == str(source) and d['role'] in ('executor', 'implementer', 'fixer'), '需要 writer dispatch')
    c.require(d['role'] != 'fixer' or d.get('stage', 0) > 0, '最终 stage 0 没有 fixer')
    c.require(not d.get('ticket_execution_version') or d['role'] == 'implementer', '单票 gate-fix 仅由 implementer 执行')
    if d.get('ticket_execution_version'):
        import ticket_execution
        ticket_execution.require_writer(d)
    if d.get('finalization_version') == 2 and d['role'] == 'fixer':
        import finalization
        finalization.require_writer(d)
    c.topology(d)
    p = root(d)
    c.require(not (p / 'gate-review-started.json').exists() and not any(x.is_dir() for x in p.glob('review-*')), 'review 已开始，不能就地修正')
    result_path = Path(args.failure).resolve()
    c.require(result_path.name == 'result.json', '需要原始 result.json')
    result = c.read(result_path)
    start_path = result_path.parent / 'started.json'
    start = c.read(start_path)
    origin_path = Path(start['dispatch_path'])
    origin = c.read(origin_path)
    keys = ('role', 'repository_root', 'worktree', 'branch', 'parent_id', 'ticket_id', 'base_commit', 'stage', 'attempt_id')
    c.require(all(d.get(k) == origin.get(k) for k in keys) and root(origin) == p, '失败不属于当前逻辑阶段')
    c.require(result_path.parent.parent == origin_path.parent and result_path.parent.name.startswith('verification-'), '失败证据目录不符')
    log = result_path.parent / 'output.log'
    c.require(start['dispatch_sha256'] == c.digest(origin_path) and result['started_sha256'] == c.digest(start_path)
              and result['log_sha256'] == c.digest(log) and result['log_bytes'] == log.stat().st_size, '失败来源或日志已变化')
    attempt = start.get('delivery_attempt')
    c.require(type(attempt) is int and 0 <= attempt <= MAX_REPAIRS and result['outcome'] == 'exited'
              and type(result['exit_code']) is int and result['exit_code'] > 0
              and result['process_group_gone'] is True and start['before'] == result['after']
              and not start['before']['status'], '仅交付候选的正常代码失败可申请修正；不接受开发 red 或中断')
    c.git(d['worktree'], 'merge-base', '--is-ancestor', start['before']['head'], 'HEAD')
    entry = {'failure': {'path': str(result_path), 'sha256': c.digest(result_path)}, 'stage': d['stage']}
    c.require(attempt < MAX_REPAIRS, '本阶段三次 gate 修正已用尽')
    used = used_repairs(p)
    target = repair_path(p, attempt + 1)
    if not target.exists():
        c.require(attempt == used, '失败不属于当前交付候选')
        if attempt:
            candidate = repair_path(p, attempt, candidate=True)
            c.require(candidate.exists() and c.read(candidate)['head'] == start['before']['head'],
                      '失败 HEAD 不属于当前修正候选')
        c.require(c.sha(d['worktree'], 'HEAD') == start['before']['head'] and not c.status(d['worktree']), '申请修正前须保留失败候选的干净 HEAD')
    record(target, entry)
    return {'allowed': True, 'gate_repair_path': str(target), 'failure_head': start['before']['head'],
            'repair_number': attempt + 1, 'remaining_repairs': MAX_REPAIRS - attempt - 1}

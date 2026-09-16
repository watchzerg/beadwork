"""最终验证报告的运行来源与覆盖；不从文字或退出码判断失败根因。"""
from pathlib import Path
import shlex

import controller as c
import verification_records


def snapshot(d):
    return verification_records.snapshot(d['dispatch_path'])


def records(d, sources, allowed, notes, successful=False):
    o = c.executor_ops()
    rows = []
    seen = set()
    for item in sources:
        path, start, end_path, end, log = verification_records.read(item)
        c.require(str(path) not in seen, '重复验证来源')
        seen.add(str(path))
        source = Path(start['dispatch_path'])
        c.require(o.binding(str(source)) in allowed and path.parent.parent == source.parent,
                  '验证不属于已绑定阶段或 fixer')
        origin = c.read(source)
        import finalization
        finalization.same_attempt(origin, d)
        c.require(start['dispatch_sha256'] == c.digest(source) and start['cwd'] == d['worktree'], '验证身份已变化')
        argv = start['argv']
        c.require(len(argv) >= 4 and argv[:3] == ['just', '--one', '--'], '验证 argv 不符')
        gates = [argv[3]]
        if argv[3] == 'final' and len(argv) > 4:
            contract = origin.get('final_gate_contract')
            if contract:
                o.bound(contract['source'])
                c.require(contract.get('boundary_parameters') is True, 'final 边界参数契约无效')
                c.require(all(g.startswith('gate-') for g in argv[4:]), 'final 边界参数无效')
                gates += list(dict.fromkeys(argv[4:]))
        valid = bool(end and end['outcome'] == 'exited' and end['process_group_gone'] is True
                     and start['before'] == end['after'] and not start['before']['status']
                     and type(end['exit_code']) is int and end['exit_code'] >= 0)
        if successful and not valid:
            c.require(str(path.parent) in notes and str(notes[str(path.parent)]).strip(), '未知或无效验证需要实际收尾说明')
        for gate in gates:
            rows.append((start['started_ns'], str(path), start, end, valid, {
                'gate': gate, 'command': shlex.join(argv), 'head_commit': start['before']['head'],
                'passed': bool(valid and end['exit_code'] == 0),
                'result': ('outcome=' + end['outcome'] + '; exit_code=' + str(end['exit_code'])) if end else '结果未知',
                'log_path': str(path.parent / 'output.log')}))
    return sorted(rows, key=lambda row: (row[0], row[1]))


def allowed(d, report):
    o = c.executor_ops()
    if d['role'] == 'fixer':
        return [o.binding(d['dispatch_path'])]
    return report['stage_sources'] + [s['dispatch'] for s in report['fix_sources']]


def check(d, report, live=False):
    import gate_repair
    sources = report.get('verification_sources')
    c.require(isinstance(sources, list), '缺少验证来源快照')
    issues = report.get('verification_issues', [])
    c.require(not issues or (report['status'] == 'BLOCKED' and report.get('outcome') in ('blocked', 'interrupted')),
              '验证来源损坏只能交付部分 BLOCKED')
    damaged = set()
    for issue in issues:
        origin_path = c.executor_ops().bound(issue['dispatch'])
        c.require(issue['dispatch'] in allowed(d, report), '损坏证据不属于本次交付')
        origin = c.read(origin_path)
        try:
            damaged_sources = issue.get('verification_sources')
            records(d, snapshot(origin) if damaged_sources is None else damaged_sources, [issue['dispatch']], {}, False)
        except (OSError, ValueError, KeyError, TypeError) as error:
            c.require(issue['reason'] == str(error), '验证损坏原因已变化，需更正报告')
        else:
            c.require(False, '不能将有效验证声明为损坏')
        damaged.add(str(origin_path))
    if live:
        own = [s for s in sources if c.read(c.executor_ops().bound(s['started']))['dispatch_path'] == d['dispatch_path']]
        c.require(d['dispatch_path'] in damaged or own == snapshot(d), '交付遗漏当前运行来源')
    passed = report['status'] in ('DONE', 'READY_TO_MERGE')
    rows = records(d, sources, allowed(d, report), report.get('verification_notes', {}), passed)
    c.require(report['verification'] == [row[-1] for row in rows], '验证报告与原始运行不符')
    head = report['head_commit']
    current = [row for row in rows if row[2]['before']['head'] == head]
    latest = {row[-1]['gate']: row for row in current}
    if passed:
        required = {'final', *report['boundary_gates'], *d['required_boundary_gates']}
        c.require(required <= {g for g, row in latest.items() if row[-1]['passed']}, '交付 HEAD 缺少成功最终 gates')
    if report.get('outcome') == 'code_failure' and d['role'] == 'fixer':
        c.require(gate_repair.used_repairs(gate_repair.root(d)) == 3, 'fixer 代码失败须用尽三次修复')
        c.require(any(row[4] and row[3]['exit_code'] > 0 and row[2].get('delivery_attempt') == 3
                      for row in current), '缺少第三次 fixer 候选失败证据')
    return rows


def populate(d, report, inherited=()):
    o = c.executor_ops()
    report['verification_issues'] = []
    sources = []
    for binding in allowed(d, report):
        origin = c.read(o.bound(binding))
        # 历史交付使用固定快照；只有当前执行者收集新增运行。
        selected = [s for s in inherited if Path(s['started']['path']).parent.parent == Path(origin['dispatch_path']).parent]
        captured = selected
        try:
            if origin['dispatch_path'] == d['dispatch_path']:
                captured = None
                selected = snapshot(d)
                captured = selected
            records(d, selected, [binding], {}, False)
        except (OSError, ValueError, KeyError, TypeError) as error:
            c.require(report['status'] == 'BLOCKED' and report.get('outcome') in ('blocked', 'interrupted'),
                      '验证来源损坏；保留现场并以 blocked/interrupted 交付：' + str(error))
            report['verification_issues'].append({'dispatch': binding, 'reason': str(error), 'verification_sources': captured})
            selected = []
        sources += [s for s in selected if s not in sources]
    report['verification_sources'] = sources
    report.setdefault('verification_notes', {})
    report['verification'] = [row[-1] for row in records(d, sources, allowed(d, report), report['verification_notes'])]

"""最终验证报告的运行来源与覆盖；不从文字或退出码判断失败根因。"""

from pathlib import Path
import re
import shlex

import dispatch_contract
import evidence
import gate_plan
import gate_repair
import repository
import verification_records


def snapshot(d):
    return verification_records.snapshot(d['dispatch_path'])


def records(d, sources, allowed, notes, successful=False):
    rows = []
    seen = set()
    for item in sources:
        path, start, end_path, end, log = verification_records.read(item)
        repository.require(str(path) not in seen, '重复验证来源')
        seen.add(str(path))
        source = Path(start['dispatch_path'])
        repository.require(evidence.binding(str(source)) in allowed and path.parent.parent == source.parent,
                  '验证不属于已绑定阶段或 fixer')
        origin = evidence.read(source)
        dispatch_contract.same_attempt(origin, d)
        repository.require(start['dispatch_sha256'] == evidence.digest(source) and start['cwd'] == d['worktree'], '验证身份已变化')
        argv = start['argv']
        repository.require(len(argv) >= 4 and argv[:3] == ['just', '--one', '--'], '验证 argv 不符')
        recipe = argv[3]
        repository.require(recipe in ('test', 'typecheck') or re.fullmatch(r'gate-[A-Za-z0-9_-]+', recipe),
                           '验证 recipe 不符')
        repository.require(len(argv) == 4 or recipe == 'test', '完整 gate 与 typecheck 不接受筛选参数')
        gates = [recipe]
        valid = bool(end and end['outcome'] == 'exited' and end['process_group_gone'] is True
                     and start['before'] == end['after']
                     and (recipe != 'gate-full' or not start['before']['status'])
                     and type(end['exit_code']) is int and end['exit_code'] >= 0)
        if successful and not valid:
            repository.require(str(path.parent) in notes and str(notes[str(path.parent)]).strip(), '未知或无效验证需要实际收尾说明')
        for gate in gates:
            rows.append((start['started_ns'], str(path), start, end, valid, {
                'gate': gate, 'command': shlex.join(argv), 'head_commit': start['before']['head'],
                'passed': bool(valid and end['exit_code'] == 0),
                'result': ('outcome=' + end['outcome'] + '; exit_code=' + str(end['exit_code'])) if end else '结果未知',
                'log_path': str(path.parent / 'output.log')}))
    return sorted(rows, key=lambda row: (row[0], row[1]))


def allowed(d, report):
    if d['role'] == 'fixer':
        return [evidence.binding(d['dispatch_path'])]
    return report['stage_sources'] + [s['dispatch'] for s in report['fix_sources']]


def check(d, report, live=False):
    sources = report.get('verification_sources')
    repository.require(isinstance(sources, list), '缺少验证来源快照')
    issues = report.get('verification_issues', [])
    repository.require(not issues or (report['status'] == 'BLOCKED' and report.get('outcome') in ('blocked', 'interrupted')),
              '验证来源损坏只能交付部分 BLOCKED')
    damaged = set()
    for issue in issues:
        origin_path = evidence.bound(issue['dispatch'])
        repository.require(issue['dispatch'] in allowed(d, report), '损坏证据不属于本次交付')
        origin = evidence.read(origin_path)
        try:
            damaged_sources = issue.get('verification_sources')
            records(d, snapshot(origin) if damaged_sources is None else damaged_sources, [issue['dispatch']], {}, False)
        except (OSError, ValueError, KeyError, TypeError) as error:
            repository.require(issue['reason'] == str(error), '验证损坏原因已变化，需更正报告')
        else:
            repository.require(False, '不能将有效验证声明为损坏')
        damaged.add(str(origin_path))
    if live:
        own = [s for s in sources if evidence.read(evidence.bound(s['started']))['dispatch_path'] == d['dispatch_path']]
        repository.require(d['dispatch_path'] in damaged or own == snapshot(d), '交付遗漏当前运行来源')
    passed = report['status'] in ('DONE', 'READY_TO_MERGE')
    rows = records(d, sources, allowed(d, report), report.get('verification_notes', {}), passed)
    repository.require(report['verification'] == [row[-1] for row in rows], '验证报告与原始运行不符')
    head = report['head_commit']
    current = [row for row in rows if row[2]['before']['head'] == head]
    latest = {row[-1]['gate']: row for row in current}
    if passed:
        repository.require(latest.get('gate-full') and latest['gate-full'][-1]['passed'], '交付 HEAD 缺少成功 gate-full')
        selected = latest['gate-full'][2].get('gate_plan')
        repository.require(selected is not None, 'gate-full 缺少当次 gate-plan 定义')
        repository.require(not any(row[0] > latest['gate-full'][0] and not row[-1]['passed'] for row in current),
                           '完整 gate-full 之后存在失败或无效验证，需重跑 gate-full')
        gate_plan.require_boundaries(selected, list(dict.fromkeys(
            [*report['boundary_gates'], *d['required_boundary_gates']])))
    if report.get('outcome') == 'code_failure' and d['role'] == 'fixer':
        repository.require(gate_repair.used_repairs(gate_repair.root(d)) == 3, 'fixer 代码失败须用尽三次修复')
        repository.require(any(row[-1]['gate'] == 'gate-full' and row[2].get('gate_plan') is not None
                      and row[4] and row[3]['exit_code'] > 0 and row[2].get('delivery_attempt') == 3
                      for row in current), '缺少第三次 fixer 候选失败证据')
    return rows


def populate(d, report, inherited=()):
    report['verification_issues'] = []
    sources = []
    for binding in allowed(d, report):
        origin = evidence.read(evidence.bound(binding))
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
            repository.require(report['status'] == 'BLOCKED' and report.get('outcome') in ('blocked', 'interrupted'),
                      '验证来源损坏；保留现场并以 blocked/interrupted 交付：' + str(error))
            report['verification_issues'].append({'dispatch': binding, 'reason': str(error), 'verification_sources': captured})
            selected = []
        sources += [s for s in selected if s not in sources]
    report['verification_sources'] = sources
    report.setdefault('verification_notes', {})
    report['verification'] = [row[-1] for row in records(d, sources, allowed(d, report), report['verification_notes'])]

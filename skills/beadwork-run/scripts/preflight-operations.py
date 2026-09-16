#!/usr/bin/env python3
"""一次采集 preflight 事实，并从语义草稿组装原有报告；仅写 dispatch 证据目录。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

import controller as c
import graph

RECIPES = ('check-toolchain', 'install', 'typecheck', 'test', 'gate-unit',
           'gate-full', 'env-facts', 'fmt', 'smoke', 'final')
SEMANTIC = ('spec_and_test_plans', 'recovery')


def load_dispatch(path):
    path = Path(path).resolve()
    d = c.read(path)
    c.require(d.get('role') == 'preflight' and d.get('dispatch_path') == str(path),
              '需要当前 preflight dispatch')
    c.require(d['expected_worktree'] == str(Path(d['repository_root']) / '.worktrees' / d['parent_id'])
              and d['expected_branch'] == 'implement/' + d['parent_id'], '固定布局不符')
    return d, path.parent


def collect(args):
    d, directory = load_dispatch(args.dispatch)
    folder = directory / 'facts'
    folder.mkdir()  # 同一 dispatch 只采集一次；部分输出也保留。
    started = time.time()
    bindings, checks, problems = [], [], []

    def save(name, value):
        path = folder / (name + '.json')
        c.write(path, value)
        bindings.append({'path': str(path), 'sha256': c.digest(path)})
        return str(path)

    def run(name, argv, cwd=None):
        begin = time.time()
        try:
            p = subprocess.run([str(x) for x in argv], cwd=cwd or d['repository_root'],
                               capture_output=True, text=True)
            result = dict(argv=list(map(str, argv)), cwd=cwd or d['repository_root'],
                          exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)
        except OSError as error:
            result = dict(argv=list(map(str, argv)), exit_code=None, stdout='', stderr=str(error))
        result['seconds'] = time.time() - begin
        # 只保留本流程要求的两项 Beads 配置。
        if name == 'config' and result['exit_code'] == 0:
            try:
                items = json.loads(result['stdout'])
                c.require(isinstance(items, list), '配置不是数组')
                result['stdout'] = json.dumps([x for x in items if x.get('key') in ('export.auto', 'export.git-add')])
            except (ValueError, AttributeError) as error:
                result.update(exit_code=None, stdout='', stderr=str(error))
        path = save(name, result)
        c.require(result['exit_code'] == 0, '命令失败，见 ' + path)
        return result['stdout'], path

    def bd(name, argv):
        raw, path = run(name, ['bd', *argv, '--readonly', '--json'])
        return graph.parse_bd_json(raw, name), path

    def check(name, operation):
        try:
            evidence = operation()
            checks.append(dict(name=name, passed=True, evidence=evidence))
        except (Exception, SystemExit) as error:
            checks.append(dict(name=name, passed=False, evidence=str(error) or '检查失败，见 facts'))

    parent, children, comments = None, [], []
    child_source = None
    try:
        rows, _ = bd('parent', ['show', d['parent_id']])
        c.require(isinstance(rows, list), 'parent 查询不是数组')
        parent = next(x for x in rows if x.get('id') == d['parent_id'])
    except (Exception, SystemExit) as error:
        problems.append('parent 不可读取：' + str(error))
    try:
        rows, child_source = bd('children', ['list', '--parent', d['parent_id'], '--all', '--limit', '0'])
        c.require(isinstance(rows, list), 'children 查询不是数组')
        for row in rows:
            graph.validate_issue(row, 'child')
        c.require(len({x['id'] for x in rows}) == len(rows), 'children ID 重复')
        children = rows
        if 'expected_children' in d:
            c.require(set(d['expected_children']) == {x['id'] for x in children}, 'children 范围变化')
    except (Exception, SystemExit) as error:
        problems.append('children 不可用于准入：' + str(error))
    try:
        comments, _ = bd('comments', ['comments', d['parent_id']])
        c.require(isinstance(comments, list), 'comments 查询不是数组')
    except (Exception, SystemExit) as error:
        problems.append('恢复 comments 不可读取：' + str(error))

    def require_fact(condition, explanation):
        c.require(condition, explanation)
        return explanation

    check('parent_state', lambda: require_fact(parent is not None and parent.get('status') in ('open', 'in_progress', 'closed'),
          'parent 状态见 facts/parent.json；closed 必须由 recovery 确认仅按合入后恢复规则处理'))
    check('children_nonempty', lambda: require_fact(bool(children), 'direct children 必须非空'))
    check('ready_labels', lambda: require_fact(bool(children) and all(x['status'] == 'closed' or 'ready-for-agent' in x.get('labels', []) for x in children),
          '全部未关闭 child 必须具有 ready-for-agent'))

    def flat():
        edges, _ = bd('parent-child-edges', ['dep', 'list', *(x['id'] for x in children),
                                             '--direction=up', '--type=parent-child'])
        value = graph.flat_result(children, edges)
        path = save('flat', value)
        c.require(value.get('flat') is True, '图未平铺，见 ' + path)
        return path
    check('flat_graph', flat)

    def config():
        rows, path = bd('config', ['config', 'show'])
        values = {x['key']: x['value'] for x in rows}
        c.require(len(rows) == 2 and set(values) == {'export.auto', 'export.git-add'}
                  and all(x is False or x == 'false' for x in values.values()), 'Beads export 配置缺失或非 false')
        return path
    check('beads_config', config)
    check('primary_worktree', lambda: require_fact(c.primary(d['repository_root']) == d['repository_root'], 'primary 必须仍指向 dispatch.repository_root'))
    check('worktree_ignored', lambda: run('ignored', ['git', 'check-ignore', '-q', '--', '.worktrees/probe'])[1])
    check('branch_name', lambda: run('branch-name', ['git', 'check-ref-format', '--branch', d['expected_branch']])[1])

    def beads_clean():
        raw, path = run('beads-status', ['git', 'status', '--short', '--', '.beads'])
        c.require(not raw.strip(), '.beads 有 tracked diff，见 ' + path)
        return path
    check('beads_clean', beads_clean)

    wt = Path(d['expected_worktree'])
    recovery_facts = dict(worktree_exists=wt.exists(), branch_exists=None)
    workspace = dict(primary_worktree=d['repository_root'], implementation_worktree=str(wt),
                     branch=d['expected_branch'], observed_head=None, clean=None)
    try:
        run('primary-status', ['git', 'status', '--porcelain=v1', '--untracked-files=all'])
        run('primary-head', ['git', 'rev-parse', 'HEAD'])
        run('worktrees', ['git', 'worktree', 'list', '--porcelain'])
        raw, _ = run('implementation-ref', ['git', 'for-each-ref', '--format=%(refname)', 'refs/heads/' + d['expected_branch']])
        recovery_facts['branch_exists'] = 'refs/heads/' + d['expected_branch'] in raw.splitlines()
        if wt.exists():
            c.topology(d)
            raw, _ = run('implementation-head', ['git', 'rev-parse', 'HEAD'], str(wt))
            workspace['observed_head'] = raw.strip()
            raw, _ = run('implementation-status', ['git', 'status', '--porcelain=v1', '--untracked-files=all'], str(wt))
            workspace['clean'] = not raw.strip()
    except Exception as error:
        problems.append('Git 恢复现场不可确认：' + str(error))
    checkout = str(wt) if wt.exists() else d['repository_root']
    check('toolchain', lambda: run('toolchain', ['just', '--one', '--', 'check-toolchain'], checkout)[1])
    recipes = []

    def just_recipes():
        nonlocal recipes
        raw, path = run('recipes', ['just', '--summary'], checkout)
        recipes = raw.split()
        c.require(set(RECIPES).issubset(recipes), '缺少 recipes：' + ', '.join(sorted(set(RECIPES) - set(recipes))))
        return path + '；实际边界能力由 spec_and_test_plans 核对'
    check('just_recipes', just_recipes)

    def schemas():
        for script, role in [('verify-ticket.py', None), ('verify-phase.py', 'preflight'), ('verify-phase.py', 'finalizer'),
                             ('verify-worker.py', 'reviewer'), ('verify-worker.py', 'fixer')]:
            raw, _ = run('schema-' + (role or 'executor'), [sys.executable, '-B', c.SCRIPTS / script, '--schema', *([role] if role else [])])
            c.require(isinstance(json.loads(raw), dict), 'schema 不是对象')
        return 'facts/schema-*.json：全部 schema 已生成'
    check('review_schema', schemas)

    # list 已含正文时不重复 show；closed 票只交接状态。
    pending = []
    for row in children:
        if row['status'] == 'closed':
            continue
        if not isinstance(row.get('description'), str):
            try:
                rows, _ = bd('ticket-' + str(len(pending)), ['show', row['id']])
                current = next(x for x in rows if x['id'] == row['id'])
                c.require(current.get('status') == row['status'], '补查正文时 ticket 状态变化')
                row = current
                c.require(isinstance(row.get('description'), str), '缺少 ticket 正文')
            except (Exception, SystemExit) as error:
                problems.append('ticket 正文不可读取：' + str(error))
        pending.append(row)
    inputs = save('semantic-inputs', dict(parent=parent, pending_tickets=pending, comments=comments,
                 recipes=recipes, checkout=checkout, workspace=workspace, recovery_facts=recovery_facts))
    snapshot = dict(dispatch={'path': d['dispatch_path'], 'sha256': c.digest(d['dispatch_path'])},
                    parent={'id': parent.get('id'), 'status': parent.get('status')} if parent else {'id': None, 'status': None},
                    expected_children=[x['id'] for x in children],
                    tickets=[dict(id=x['id'], status=x['status']) for x in children], workspace=workspace, recovery_facts=recovery_facts,
                    checks=checks, blockers=problems, recipes=recipes, inputs=inputs, sources=bindings,
                    collection_started_at=started, collection_finished_at=time.time())
    path = directory / 'facts.json'
    c.write(path, snapshot)
    return dict(facts_path=str(path), facts_sha256=c.digest(path), semantic_inputs_path=inputs,
                pending_ids=[x['id'] for x in pending], expected_children=snapshot['expected_children'],
                failed_checks=[x for x in checks if not x['passed']], blockers=problems,
                collection_seconds=snapshot['collection_finished_at'] - started)


def assemble(args):
    started = time.time()
    d, directory = load_dispatch(args.dispatch)
    facts_path = directory / 'facts.json'
    c.require(c.digest(facts_path) == args.facts_sha256, '采集快照 hash 不符')
    f = c.read(facts_path)
    c.require(f['dispatch'] == {'path': d['dispatch_path'], 'sha256': c.digest(d['dispatch_path'])}, '采集 dispatch 不符')
    for source in f['sources']:
        c.require(Path(source['path']).resolve().parent == directory / 'facts'
                  and c.digest(source['path']) == source['sha256'], '原始采集证据已变化')
    draft = c.read(args.draft)
    fields = {'status', 'plans', 'linked_spec', 'resume_evidence', 'sources', 'suggested_route', 'checks', 'blockers', 'remaining_work'}
    c.require(set(draft) == fields, '语义草稿字段不符')
    c.require({x['name'] for x in draft['checks']} == set(SEMANTIC) and len(draft['checks']) == 2,
              '语义草稿只能填写 spec_and_test_plans 与 recovery')
    unresolved = {x['id'] for x in f['tickets'] if x['status'] != 'closed'}
    c.require(set(draft['plans']).issubset(unresolved), '计划含未知或已关闭 ticket')
    tickets = [dict(x, test_plan=draft['plans'].get(x['id'])) for x in f['tickets']]
    gates = sorted({g for x in tickets if x['test_plan'] for g in x['test_plan']['boundary_gates']})
    blockers = list(f['blockers']) + draft['blockers']
    checks = f['checks'] + draft['checks']
    blockers += [x['name'] + '：' + x['evidence'] for x in checks if not x['passed']]
    missing = set(gates) - set(f['recipes'])
    if missing:
        blockers.append('未知 boundary gates：' + ', '.join(sorted(missing)))
    route, parent_status = draft['suggested_route'], f['parent']['status']
    if route == 'new_batch' and not (parent_status == 'open' and unresolved
            and not any(x['status'] == 'in_progress' for x in f['tickets'])
            and f['recovery_facts'] == {'worktree_exists': False, 'branch_exists': False}):
        blockers.append('new_batch 与 parent/children/branch/worktree 现场不符')
    if parent_status == 'closed' and (unresolved or route != 'post_merge'):
        blockers.append('closed parent 只能在全部 children 关闭后走 post_merge')
    if route in ('finalize', 'post_merge') and unresolved:
        blockers.append('仍有未关闭 child，不能最终集成或合入后收尾')
    if route == 'resume_tickets' and not unresolved:
        blockers.append('children 全部关闭，应核对 finalize/post_merge 路径')
    report = {k: draft[k] for k in ('linked_spec', 'resume_evidence', 'suggested_route', 'remaining_work')}
    report.update(status='BLOCKED' if blockers else draft['status'], parent=f['parent'],
                  expected_children=f['expected_children'], tickets=tickets, boundary_gates=gates,
                  workspace=f['workspace'], checks=checks, blockers=blockers,
                  sources=[str(facts_path), *(s['path'] for s in f['sources']), *draft['sources']])
    output = Path(args.output).resolve()
    c.require(output.parent == directory, '报告必须位于 dispatch 目录')
    c.require(not output.exists() and not output.with_suffix('.timing.json').exists(), '保留已有交付文件，请使用新文件名')
    c.write(output, report)
    receipt = json.loads(c.run([sys.executable, '-B', c.SCRIPTS / 'verify-phase.py', '--check-report', 'preflight',
                               str(output), '--expected', d['dispatch_path'], '--emit-receipt']))
    c.write(output.with_suffix('.timing.json'), dict(
        facts_sha256=args.facts_sha256, report_sha256=receipt['report_sha256'],
        collection_seconds=f['collection_finished_at'] - f['collection_started_at'],
        semantic_and_wait_seconds=max(0, started - f['collection_finished_at']),
        assembly_seconds=time.time() - started))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('collect'); p.add_argument('--dispatch', required=True)
    p = sub.add_parser('assemble'); p.add_argument('--dispatch', required=True)
    p.add_argument('--facts-sha256', required=True); p.add_argument('--draft', required=True); p.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args) if args.command == 'collect' else assemble(args), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

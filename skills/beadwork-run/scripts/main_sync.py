"""新票前同步本地 main；由 controller 调用，保留可恢复的合并和验证证据。"""
from pathlib import Path
import importlib.util
import json
import re
import signal
import subprocess
import time
import uuid

import controller as c


def ancestor(wt, base, head):
    result = subprocess.run(['git', '-C', str(wt), 'merge-base', '--is-ancestor', base, head],
                            capture_output=True, text=True)
    c.require(result.returncode in (0, 1), '无法检查提交 ancestry：' + result.stderr)
    return result.returncode == 0


def clean(d):
    c.topology(d)
    for wt in (d['repository_root'], d['worktree']):
        if wt == d['worktree']:
            c.require(not c.status(wt), '同步要求 implementation worktree 干净：' + wt)
        for name in ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'sequencer'):
            path = c.git(wt, 'rev-parse', '--path-format=absolute', '--git-path', name)
            c.require(not Path(path).exists(), '存在未完成 Git 操作：' + path)


def frontier(d):
    return json.loads(c.run([c.sys.executable, '-B', c.SCRIPTS / 'graph.py', 'next',
                            d['parent_id'], *d['expected_children']], d['worktree']))


def command(d, directory, argv):
    """每次命令独立记录；信号中断收尾专属进程组，恢复不复用缺失的结果。"""
    folder = directory / ('command-' + uuid.uuid4().hex)
    folder.mkdir()
    c.write(folder / 'started.json', {'argv': argv, 'head': c.sha(d['worktree'], 'HEAD')})
    spec = importlib.util.spec_from_file_location('sync_runner', c.SCRIPTS / 'run-verification.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    interrupted, handlers = [], {}
    process = None
    stopped = True
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, lambda value, frame: interrupted.append(value))
        with (folder / 'output.log').open('xb') as log:
            process = subprocess.Popen(argv, cwd=d['worktree'], stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            while process.poll() is None and not interrupted:
                time.sleep(0.05)
            if interrupted or runner.group_exists(process.pid):
                stopped = runner.stop(process)
                interrupted.append(True)
    finally:
        if process is not None and (process.poll() is None or runner.group_exists(process.pid)):
            stopped = runner.stop(process)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    result = {'argv': argv, 'started_sha256': c.digest(folder / 'started.json'),
              'exit_code': process.returncode, 'interrupted': bool(interrupted),
              'process_group_gone': stopped, 'log_sha256': c.digest(folder / 'output.log')}
    c.write(folder / 'result.json', result)
    c.require(not interrupted and stopped and process.returncode == 0,
              '同步命令失败或中断；保留现场，日志：' + str(folder / 'output.log'))
    return str(folder / 'result.json')


def verification_commands(d, intent, head):
    if head == intent['before'] and ancestor(d['worktree'], intent['target_main'], head):
        return []
    install = bool(c.git(d['worktree'], 'diff', '--name-only', intent['before'], head,
                         '--', *intent['install_inputs']))
    recipes = (['install'] if install else []) + ['env-facts', 'smoke']
    return [['just', '--one', '--', recipe] + (intent['gates'] if recipe == 'smoke' else [])
            for recipe in recipes]


def check_result(d, path):
    clean(d)
    p = Path(path)
    root = Path(d['repository_root']) / '.worktrees' / '.evidence' / d['parent_id'] / 'main-sync'
    c.require(p.name == 'ready.json' and p.resolve().is_relative_to(root.resolve()), '同步证据不属于本批次')
    c.require(not any(not (i.parent / 'ready.json').exists() for i in root.glob('*/intent.json')),
              '存在未完成同步，不能使用旧 ready 开新票')
    r = c.read(p)
    intent = c.read(p.parent / 'intent.json')
    c.require(r['intent_sha256'] == c.digest(p.parent / 'intent.json'), '同步意图已变化')
    c.require(all(intent[k] == d[k] for k in ('repository_root', 'worktree', 'branch', 'parent_id')),
              '同步身份不符')
    c.require(r['head'] == c.sha(d['worktree'], 'HEAD'), '同步验证 HEAD 已变化')
    c.require(ancestor(d['worktree'], intent['target_main'], r['head']), '同步目标未合入')
    expected = verification_commands(d, intent, r['head'])
    c.require(len(r['commands']) == len(expected), '同步验证命令不完整')
    for entry, argv in zip(r['commands'], expected):
        c.require(Path(entry['path']).resolve().is_relative_to(p.parent.resolve()), '命令证据不属于本次同步')
        c.require(c.digest(entry['path']) == entry['sha256'], '同步命令证据已变化')
        record = c.read(entry['path'])
        start = Path(entry['path']).parent / 'started.json'
        c.require(record['started_sha256'] == c.digest(start), '同步命令开始记录已变化')
        started = c.read(start)
        c.require(started['head'] == r['head'] and started['argv'] == argv and record['argv'] == argv,
                  '同步验证 HEAD 或命令不符')
        c.require(record['exit_code'] == 0 and not record['interrupted'] and record['process_group_gone'],
                  '同步验证未通过')
        c.require(c.digest(Path(entry['path']).parent / 'output.log') == record['log_sha256'], '同步日志已变化')
    return r


def sync(args):
    data = c.read(args.input)
    root = c.primary(data['repository_root'])
    parent = data['parent_id']
    c.require(isinstance(parent, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', parent)
              and parent not in ('.', '..'), 'parent ID 无效')
    d = dict(data, repository_root=root, worktree=str(Path(root) / '.worktrees' / parent),
             branch='implement/' + parent)
    gates = d['required_boundary_gates']
    paths = d['install_inputs']
    c.require(isinstance(gates, list) and all(isinstance(g, str) and re.fullmatch(r'gate-[A-Za-z0-9_-]+', g) for g in gates),
              '需要有效 boundary gates')
    c.require(isinstance(paths, list) and paths and all(isinstance(p, str) and p and not Path(p).is_absolute()
              and '..' not in Path(p).parts and not p.startswith(':') for p in paths), '需要仓库相对安装输入路径')
    gates = sorted(set(gates) - {'gate-unit'})
    clean(d)
    next_ = frontier(d)
    c.require(next_['next'] == 'claim', '仅在新票可领取时同步：' + json.dumps(next_, ensure_ascii=False))
    directory = Path(root) / '.worktrees' / '.evidence' / parent / 'main-sync'
    directory.mkdir(parents=True, exist_ok=True)
    pending = [p.parent for p in directory.glob('*/intent.json') if not (p.parent / 'ready.json').exists()]
    c.require(len(pending) <= 1, '存在多个未完成同步，需核实现场')
    if pending:
        attempt = pending[0]
        intent = c.read(attempt / 'intent.json')
        c.require(all(intent[k] == d[k] for k in ('repository_root', 'worktree', 'branch', 'parent_id', 'expected_children')),
                  '恢复同步身份或 children 不符')
        c.require(intent['gates'] == gates and intent['install_inputs'] == paths, '恢复须沿用原同步验证输入')
    else:
        attempt = directory / uuid.uuid4().hex
        attempt.mkdir()
        intent = {k: d[k] for k in ('repository_root', 'worktree', 'branch', 'parent_id', 'expected_children')}
        intent.update(before=c.sha(d['worktree'], 'HEAD'), target_main=c.sha(root, 'refs/heads/main'),
                      gates=gates, install_inputs=paths)
        c.write(attempt / 'intent.json', intent)
    print(json.dumps({'sync_path': str(attempt)}, ensure_ascii=False), file=c.sys.stderr, flush=True)
    before, target = intent['before'], intent['target_main']
    head = c.sha(d['worktree'], 'HEAD')
    c.require(ancestor(d['worktree'], before, head), '同步前 HEAD 已不在当前历史中')
    changed = not ancestor(d['worktree'], target, before)
    if not ancestor(d['worktree'], target, head):
        c.require(head == before, '合并未完成且 HEAD 已变化，需核实现场')
        command(d, attempt, ['git', 'merge', '--ff', '--no-edit', target])
        head = c.sha(d['worktree'], 'HEAD')
    clean(d)
    c.require(ancestor(d['worktree'], target, head), '目标 main 未合入')
    commands = []
    for argv in verification_commands(d, intent, head):
        result = command(d, attempt, argv)
        commands.append({'path': result, 'sha256': c.digest(result)})
        clean(d)
        c.require(c.sha(d['worktree'], 'HEAD') == head, '同步验证期间 HEAD 已变化')
    result = {'head': head, 'target_main': target, 'changed': changed or head != before,
              'intent_sha256': c.digest(attempt / 'intent.json'), 'commands': commands}
    clean(d)
    c.require(c.sha(d['worktree'], 'HEAD') == head, '同步完成前 HEAD 已变化')
    pending_result = attempt / ('ready-' + uuid.uuid4().hex + '.pending')
    c.write(pending_result, result)
    pending_result.rename(attempt / 'ready.json')
    return {**result, 'sync_result': str(attempt / 'ready.json'), 'frontier': frontier(d)}

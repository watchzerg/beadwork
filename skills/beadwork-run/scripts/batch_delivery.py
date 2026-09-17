"""固定受审 SHA 的远端交付；每次调用重新推送并保存独立结果。"""

from pathlib import Path
import re
import uuid

import evidence
import operation_commands as commands
import repository
import tracker_operations as tracker

require = repository.require


def policy(value):
    require(isinstance(value, dict) and set(value) == {'git', 'beads'}, '需要 Git 与 Beads 的显式推送决定')
    for decision in value.values():
        require(isinstance(decision, dict) and decision.get('action') in ('push', 'skip'), '无效推送决定')
        if decision['action'] == 'skip':
            require(set(decision) == {'action', 'reason'} and isinstance(decision['reason'], str)
                    and decision['reason'].strip(), 'skip 需要用户限制说明')
        else:
            require(set(decision) == {'action'}, 'push 仅接受 action')
    return value


def argv(name, head):
    return {'git-push': ['git', 'push', 'origin', head + ':refs/heads/main'],
            'git-readback': ['git', 'ls-remote', '--refs', 'origin', 'refs/heads/main'],
            'beads-push': ['bd', 'dolt', 'push', '--no-adopt']}[name]


def remote_head(log):
    matches = re.findall(r'^([0-9a-f]{40})\s+refs/heads/main$', log.read_text(), re.M)
    require(len(matches) == 1, 'Git 远端 main 读回不唯一或缺失')
    return matches[0]


def push(input_path):
    data = evidence.read(input_path)
    require(set(data) == {'merge_record', 'policy'}, '推送输入字段不符')
    selected_policy = policy(data['policy'])
    merge = evidence.read(evidence.bound(data['merge_record']))
    require(merge.get('kind') == 'merge_checkpoint', '推送需要 merge checkpoint')
    root, head = merge['repository_root'], merge['reviewed_head']
    require(repository.primary(root) == root and repository.sha(root, 'HEAD') == head, '本地 main 已偏离受审 HEAD')
    require(tracker.issue(root, merge['parent_id'])['status'] == 'closed', '推送前 parent 必须关闭')
    folder = Path(root) / '.worktrees/.evidence' / merge['parent_id'] / 'delivery' / uuid.uuid4().hex
    folder.mkdir(parents=True)
    evidence.write(folder / 'request.json', data)
    result = {'kind': 'batch_delivery', 'merge_record': data['merge_record'], 'policy': selected_policy,
              'request': evidence.binding(folder / 'request.json'), 'commands': [],
              'git': {'status': 'pending'}, 'beads': {'status': 'pending'}, 'ready': False}
    try:
        for system in ('git', 'beads'):
            if selected_policy[system]['action'] == 'skip':
                result[system] = {'status': 'skipped', 'reason': selected_policy[system]['reason']}
                continue
            names = ('git-push', 'git-readback') if system == 'git' else ('beads-push',)
            for name in names:
                require(repository.sha(root, 'HEAD') == head, '推送期间本地 main 已变化')
                source = commands.run(folder, name, argv(name, head), root, data['merge_record'])
                result['commands'].append({'name': name, 'source': source})
                _, log = commands.require_success(source)
                if name == 'git-readback':
                    require(remote_head(log) == head, 'Git 远端 SHA 不等于受审 HEAD')
            result[system] = {'status': 'pushed'}
            if system == 'git':
                result['git']['remote_head'] = head
        require(repository.sha(root, 'HEAD') == head, '推送结束时本地 main 已变化')
        result['ready'] = True
    except Exception as error:
        result['error'] = str(error)
        raise ValueError('推送未完成，结果：' + str(folder / 'result.json') + '；' + str(error)) from error
    finally:
        evidence.write(folder / 'result.json', result)
    return {'delivery_result': evidence.binding(folder / 'result.json'), **result}


def check(path, merge_path):
    p = evidence.absolute(path)
    value = evidence.read(p)
    require(value.get('kind') == 'batch_delivery' and value.get('ready') is True, '清理需要完成的交付结果')
    require(value['merge_record'] == evidence.binding(merge_path), '交付结果与 merge checkpoint 不符')
    merge = evidence.read(merge_path)
    directory = Path(merge['repository_root']) / '.worktrees/.evidence' / merge['parent_id'] / 'delivery'
    require(p.parent.parent == directory and p.name == 'result.json', '交付结果目录不符')
    decisions = policy(value['policy'])
    require(evidence.read(evidence.bound(value['request'])) == {'merge_record': value['merge_record'], 'policy': decisions}, '交付请求与结果不符')
    expected = []
    for system in ('git', 'beads'):
        if decisions[system]['action'] == 'skip':
            require(value[system] == {'status': 'skipped', 'reason': decisions[system]['reason']}, '跳过结果不符')
        else:
            require(value[system]['status'] == 'pushed', '必要推送未完成')
            expected.extend(('git-push', 'git-readback') if system == 'git' else ('beads-push',))
    require([x['name'] for x in value['commands']] == expected, '推送命令缺失或顺序错误')
    for item in value['commands']:
        require(Path(item['source']['path']).parent.parent == p.parent, '推送命令不属于本次交付')
        started, log = commands.require_success(item['source'])
        require(started == {'argv': argv(item['name'], merge['reviewed_head']),
                            'cwd': merge['repository_root'], 'context': value['merge_record']}, '推送命令身份不符')
        if item['name'] == 'git-readback':
            require(remote_head(log) == merge['reviewed_head'] == value['git']['remote_head'], '远端读回来源不符')
    return value

"""单票验证历史与快照读取；不执行验证 recipe。"""

from pathlib import Path
import shlex

import dispatch_contract
import evidence
import repository
import verification_records

def collect(current_path, prior_paths, notes, report_status, snapshots=None):
    """自动保留本次及显式恢复来源中的全部记录；不推导验证覆盖或 DONE。"""
    current = dispatch_contract.verification_dispatch(current_path)
    selected = None
    if snapshots is not None:
        repository.require(isinstance(snapshots, list), "验证快照必须为列表")
        selected = {}
        for item in snapshots:
            repository.require(set(item) == {"started", "result"}, "验证快照字段不符")
            start = evidence.absolute(item["started"]["path"])
            repository.require(start.name == "started.json" and evidence.digest(start) == item["started"]["sha256"], "验证快照来源已变化")
            key = str(start.parent)
            repository.require(key not in selected, "验证快照重复")
            selected[key] = item
    keys = ("role", "repository_root", "worktree", "branch", "parent_id", "ticket_id", "base_commit", "attempt_id")
    rows = []
    found = set()
    sources = [evidence.absolute(current_path), *(evidence.absolute(p) for p in prior_paths)]
    repository.require(len(set(sources)) == len(sources), "verification dispatch 不得重复")
    repository.require(isinstance(notes, dict) and all(isinstance(k, str) and isinstance(v, str) and v.strip()
                                             for k, v in notes.items()), "verification_notes 必须为路径到说明的映射")
    for source in sources:
        previous = dispatch_contract.verification_dispatch(source)
        repository.require(all(current.get(k) == previous.get(k) for k in keys), "验证记录属于其他 ticket 或 BASE")
        for directory in sorted(source.parent.glob("verification-*")):
            evidence.absolute(directory)
            repository.require(directory.is_dir(), "验证证据必须是目录")
            run_path = str(directory)
            if selected is not None and run_path not in selected:
                continue
            found.add(run_path)
            start_path = evidence.absolute(directory / "started.json")
            start = evidence.read(start_path)
            repository.require(start["dispatch_path"] == str(source) and start["dispatch_sha256"] == evidence.digest(source),
                      "验证 dispatch 身份或内容已变化")
            repository.require(start["cwd"] == current["worktree"], "验证 cwd 不符")
            text = "未完成记录；退出结果未知，需确认旧任务已结束"
            end_path = evidence.absolute(directory / "result.json")
            has_result = end_path.exists() if selected is None else selected[run_path]["result"] is not None
            if has_result:
                if selected is not None:
                    entry = selected[run_path]["result"]
                    repository.require(entry["path"] == str(end_path) and evidence.digest(end_path) == entry["sha256"], "验证快照结果已变化")
                result = evidence.read(end_path)
                log = evidence.absolute(directory / "output.log")
                repository.require(result["started_sha256"] == evidence.digest(start_path)
                          and result["log_sha256"] == evidence.digest(log)
                          and result["log_bytes"] == log.stat().st_size, "验证记录或日志已变化")
                text = (f"outcome={result['outcome']}；exit_code={result['exit_code']}；"
                        f"耗时={result['duration_seconds']}s；result_sha256={evidence.digest(end_path)}")
            elif report_status == "DONE":
                repository.require(run_path in notes, "未完成验证需在 verification_notes 说明收尾确认及后续验证")
            text += (f"；运行 HEAD={start['before']['head']}；"
                     f"有未提交修改={bool(start['before']['status'])}；证据={directory}")
            if run_path in notes:
                text += "；执行者说明：" + notes[run_path]
            rows.append((start["started_ns"], run_path, {"command": shlex.join(start["argv"]), "result": text}))
    repository.require(selected is None or set(selected) == found, "验证快照不属于当前来源")
    repository.require(set(notes).issubset(found), "verification_notes 引用了未收集的运行目录")
    return [row[2] for row in sorted(rows, key=lambda row: (row[0], row[1]))]


def runs(d):
    paths = list(dict.fromkeys(d.get('verification_dispatches', []) + [d['dispatch_path']]))
    for path in paths:
        old = evidence.read(path)
        dispatch_contract.same_ticket(d, old)
        for folder in sorted(Path(path).parent.glob('verification-*')):
            start = evidence.read(folder / 'started.json')
            end = folder / 'result.json'
            if end.exists():
                yield start, evidence.read(end), end


def verification_snapshot(d):
    entries = []
    for path in list(dict.fromkeys(d.get('verification_dispatches', []) + [d['dispatch_path']])):
        entries.extend(verification_records.snapshot(path))
    return entries


def collect_verification(d, snapshot, notes, status):
    rows, issues = [], []
    for item in snapshot:
        run_path = str(Path(evidence.bound(item['started'])).parent)
        selected_notes = {run_path: notes[run_path]} if run_path in notes else {}
        try:
            collected = collect(d['dispatch_path'], d.get('verification_dispatches', []),
                                                  selected_notes, status, [item])
        except (OSError, ValueError, KeyError, TypeError) as error:
            issues.append({'source': item, 'reason': str(error)})
        else:
            started = evidence.read(evidence.bound(item['started']))
            rows.extend((started['started_ns'], run_path, row) for row in collected)
    return [row[2] for row in sorted(rows, key=lambda row: (row[0], row[1]))], issues

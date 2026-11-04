"""Bounded, read-only run inspection. Evidence is data, never permission."""
import json
import fcntl
import math
import os
from pathlib import Path
import re
import stat
import time

METADATA_LIMIT = 1024 * 1024
TASK_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}')


class InspectionError(ValueError):
    pass


def checked_directory(path):
    directory = Path(path).absolute()
    for component in [*reversed(directory.parents), directory]:
        if component.is_symlink():
            raise InspectionError('symlink directories are not inspectable')
    if not directory.is_dir():
        raise InspectionError('run directory not found')
    return directory


def _read(root, parts, limit, tail=False):
    descriptors = []
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(descriptor)
        for component in parts[:-1]:
            descriptor = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            descriptors.append(descriptor)
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        descriptors.append(descriptor)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise InspectionError('evidence must be a regular file')
        truncated = info.st_size > limit
        if truncated and not tail:
            raise InspectionError('metadata exceeds inspection limit')
        if truncated:
            os.lseek(descriptor, -limit, os.SEEK_END)
        payload = os.read(descriptor, limit)
        return {'text': payload.decode('utf-8', errors='replace'), 'truncated': truncated,
                'size_bytes': info.st_size}
    except FileNotFoundError:
        return None
    except OSError as error:
        raise InspectionError('evidence path unavailable or unsafe') from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _json(root, name, default):
    item = _read(root, [name], METADATA_LIMIT)
    if item is None:
        return default
    try:
        value = json.loads(item['text'])
    except (ValueError, RecursionError) as error:
        raise InspectionError('invalid JSON metadata: ' + name) from error
    if not isinstance(value, dict):
        raise InspectionError('metadata must be a JSON object: ' + name)
    return value


def supervisor_active(root):
    descriptor = None
    try:
        descriptor = os.open(root / 'run.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        return False
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _timestamp(value):
    try:
        return value if type(value) in (int, float) and value >= 0 and math.isfinite(value) else None
    except OverflowError:
        return None


def _timing(scope, started, finished, live, now):
    started, finished = _timestamp(started), _timestamp(finished)
    end = finished if finished is not None else _timestamp(now) if live else None
    duration = end - started if started is not None and end is not None and end >= started else None
    return {'scope': scope, 'started_at': started, 'finished_at': finished,
            'duration_seconds': duration, 'live': bool(live and duration is not None)}


def _timings(events, tasks, active):
    started = finished = None
    session_open = False
    attempts, pending = {}, set()
    for event in events:
        name, timestamp = event.get('event'), event.get('time')
        if name in ('run_started', 'run_resumed', 'run_finished'):
            for identifier in pending:
                attempts[identifier] = (None, None)
            pending.clear()
        if name in ('run_started', 'run_resumed'):
            started, finished, session_open = timestamp, None, True
        elif name == 'run_finished':
            finished, session_open = timestamp, False
        identifier = event.get('task')
        if not isinstance(identifier, str) or identifier not in tasks:
            continue
        if name == 'started':
            attempts[identifier] = (timestamp, None)
            pending.add(identifier)
        elif name == 'finished':
            attempts[identifier] = (attempts.get(identifier, (None, None))[0], timestamp)
            pending.discard(identifier)
        elif name == 'blocked':
            pending.discard(identifier)
    now = time.time()
    for identifier, task in tasks.items():
        task['timing'] = _timing('latest_attempt', *attempts.get(identifier, (None, None)),
                                 active and identifier in pending and task.get('status') == 'running', now)
    return _timing('latest_session', started, finished, active and session_open, now)


def status(run_dir):
    root = checked_directory(run_dir)
    summary = _json(root, 'summary.json', {})
    plan = _json(root, 'plan.json', {'tasks': []})
    if not isinstance(plan.get('tasks', []), list) or not isinstance(summary.get('tasks', {}), dict):
        raise InspectionError('invalid task metadata shape')
    warnings = []
    tasks = {}
    for task in plan.get('tasks', []):
        if isinstance(task, dict) and isinstance(task.get('id'), str) and TASK_ID.fullmatch(task['id']):
            tasks[task['id']] = {'status': 'not_started', 'depends_on': task.get('depends_on', [])}
    raw_events = _read(root, ['events.jsonl'], METADATA_LIMIT, tail=True)
    events = []
    # A damaged event may hide a new attempt; never pair timings across it.
    timing_start = 0
    if raw_events:
        lines = raw_events['text'].splitlines()
        if raw_events['truncated']:
            lines = lines[1:]
            warnings.append('event history truncated to bounded tail')
        for line in lines:
            try:
                event = json.loads(line)
            except (ValueError, RecursionError):
                warnings.append('partial or invalid event skipped')
                timing_start = len(events)
                continue
            if not isinstance(event, dict):
                warnings.append('non-object event skipped')
                timing_start = len(events)
                continue
            events.append(event)
            identifier = event.get('task')
            if not isinstance(identifier, str) or not TASK_ID.fullmatch(identifier):
                continue
            item = tasks.setdefault(identifier, {})
            if event.get('event') == 'started':
                item['status'] = 'running'
            elif event.get('event') == 'finished':
                item['status'] = event.get('status', 'unknown')
            elif event.get('event') == 'blocked':
                item['status'] = 'blocked'
    lifecycle = [event.get('event') for event in events if event.get('event') in ('run_started', 'run_resumed', 'run_finished')]
    if lifecycle and lifecycle[-1] in {'run_started', 'run_resumed'}:
        summary = {}
    for identifier, value in summary.get('tasks', {}).items():
        if isinstance(identifier, str) and TASK_ID.fullmatch(identifier) and isinstance(value, dict):
            tasks.setdefault(identifier, {}).update(value)
    overall = summary.get('status', 'running' if events else 'not_started')
    reported = overall
    active = supervisor_active(root) if overall == 'running' else None
    if overall == 'running' and active is not True:
        overall = 'interrupted' if active is False else 'unknown'
        warnings.append('supervisor lease inactive or unverified; child processes may still exist')
        for value in tasks.values():
            if value.get('status') == 'running':
                value['status'] = overall
    return {'name': root.name, 'status': overall, 'base': summary.get('base'),
            'reported_status': reported, 'supervisor_active': active,
            'timing': _timings(events[timing_start:], tasks, active is True and overall == 'running'),
            'source_unchanged': summary.get('source_unchanged'),
            'security_sandbox': summary.get('security_sandbox', False),
            'tasks': tasks, 'plan': plan, 'events': events[-100:], 'warnings': warnings,
            'evidence_trusted': False}


def review(run_dir, task=None, max_bytes=65536):
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= 1024 * 1024:
        raise InspectionError('max_bytes must be between 1 and 1048576')
    if task is not None and (not isinstance(task, str) or not TASK_ID.fullmatch(task)):
        raise InspectionError('invalid task id')
    root = checked_directory(run_dir)
    snapshot = status(root)
    identifiers = [task] if task is not None else list(snapshot['tasks'])
    if len(identifiers) > 64:
        raise InspectionError('select a task when reviewing more than 64 tasks')
    tasks = {}
    for identifier in identifiers:
        folder = root / 'tasks' / identifier
        if folder.is_symlink():
            raise InspectionError('symlink task directory')
        logs = {}
        for name in ['runtime.stdout', 'runtime.stderr', 'sth.stdout', 'sth.stderr']:
            item = _read(root, ['tasks', identifier, name], max_bytes, tail=True)
            if item is not None:
                logs[name] = item
        patch = _read(root, ['tasks', identifier, 'changes.patch'], max_bytes, tail=True)
        tasks[identifier] = {'logs': logs, 'patch': patch,
                             'status': snapshot['tasks'].get(identifier, {}).get('status', 'unknown')}
    return {'name': root.name, 'status': snapshot['status'], 'tasks': tasks,
            'evidence_trusted': False, 'max_bytes_per_file': max_bytes}

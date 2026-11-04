"""Optional task execution boundaries. Local mode is explicitly not a sandbox."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Callable
import uuid


class IsolationError(Exception):
    pass


@dataclass
class Execution:
    argv: list[str]
    cwd: Path
    env: dict[str, str]
    security_sandbox: bool
    collect: Callable[[], None]
    cleanup: Callable[[], None]
    container_name: str | None = None


def validate_spec(spec):
    spec = {'backend': 'local'} if spec is None else spec
    if not isinstance(spec, dict):
        raise IsolationError('isolation specification must be an object')
    backend = spec.get('backend', 'local')
    if backend not in ('local', 'container'):
        raise IsolationError('unknown isolation backend')
    if backend == 'local':
        if set(spec) - {'backend'}:
            raise IsolationError('local backend accepts no isolation claims')
        return {'backend': 'local'}
    unknown = set(spec) - {'backend', 'image', 'network', 'user', 'memory_mb', 'cpus', 'pids_limit', 'tmp_mb'}
    if unknown:
        raise IsolationError('unsupported isolation options: ' + ', '.join(sorted(unknown)))
    image = spec.get('image', '')
    if not isinstance(image, str) or not re.fullmatch(r'(?:[A-Za-z0-9][A-Za-z0-9._:/-]*@)?sha256:[a-f0-9]{64}', image):
        raise IsolationError('container image must be digest-pinned or an immutable sha256 image id')
    if spec.get('network', 'none') != 'none':
        raise IsolationError('only network=none is supported; no unrestricted provider networking')
    default_uid = os.getuid() if os.getuid() else 1000
    default_gid = os.getgid() if os.getgid() else 1000
    user = spec.get('user', f'{default_uid}:{default_gid}')
    if not isinstance(user, str) or not re.fullmatch(r'[1-9][0-9]*(?::[1-9][0-9]*)?', user):
        raise IsolationError('container user must be a numeric nonroot uid and optional nonroot gid')
    limits = {'memory_mb': (512, 1048576), 'cpus': (1, 64), 'pids_limit': (128, 4096), 'tmp_mb': (64, 65536)}
    normalized = {'backend': 'container', 'image': image, 'network': 'none', 'user': user}
    for name, (default, maximum) in limits.items():
        value = spec.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise IsolationError('invalid isolation limit: ' + name)
        if name != 'cpus' and not isinstance(value, int):
            raise IsolationError('integer isolation limit required: ' + name)
        normalized[name] = value
    return normalized


def _docker_env():
    environment = os.environ.copy()
    for selector in ('DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        environment.pop(selector, None)
    return environment


def _docker_command():
    binary = shutil.which('docker')
    if not binary:
        raise IsolationError('Docker CLI unavailable')
    return [binary, '--host=unix:///var/run/docker.sock']


def cleanup_container(spec, container_name):
    normalized = validate_spec(spec)
    if normalized['backend'] != 'container' or not isinstance(container_name, str) or not re.fullmatch(r'sth-factory-[a-f0-9]{32}', container_name):
        raise IsolationError('refusing cleanup of an unrecognized container identity')
    docker = _docker_command()
    environment = _docker_env()
    inspect = subprocess.run(docker + ['inspect', '--format', '{{json .Config}}', container_name],
                             env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    if inspect.returncode:
        if b'No such object' in inspect.stderr or b'No such container' in inspect.stderr:
            return False
        raise IsolationError('container cleanup inspection failed')
    try:
        config = json.loads(inspect.stdout)
        labels = config.get('Labels') or {}
        if config.get('Image') != normalized['image'] or labels.get('io.sth.factory.container') != container_name:
            raise IsolationError('refusing cleanup: container ownership or image does not match')
    except (json.JSONDecodeError, AttributeError, TypeError) as error:
        raise IsolationError('container cleanup identity is invalid') from error
    removed = subprocess.run(docker + ['rm', '--force', container_name], env=environment,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    if removed.returncode and b'No such container' not in removed.stderr:
        raise IsolationError('container cleanup not confirmed')
    return True


def probe(spec=None):
    try:
        normalized = validate_spec(spec)
        if normalized['backend'] == 'local':
            return {'available': True, 'backend': 'local', 'security_sandbox': False,
                    'reason': 'trusted local process; no operating-system isolation'}
        command = _docker_command()
        server = subprocess.run(command + ['info', '--format', '{{json .SecurityOptions}}'],
                                env=_docker_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if server.returncode:
            raise IsolationError('local Docker daemon unavailable: ' + server.stderr.decode(errors='replace')[:500])
        image = subprocess.run(command + ['image', 'inspect', normalized['image'], '--format', '{{.Id}}'],
                               env=_docker_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if image.returncode:
            raise IsolationError('digest-pinned image not present locally; no automatic pull')
        return {'available': True, 'backend': 'container', 'security_sandbox': True,
                'image': normalized['image'], 'network': 'none',
                'daemon_rootless': 'rootless' in server.stdout.decode(errors='replace'),
                'reason': 'container boundary, shared host kernel; not a virtual machine'}
    except (IsolationError, OSError, subprocess.TimeoutExpired) as error:
        return {'available': False, 'backend': spec.get('backend') if isinstance(spec, dict) else None,
                'security_sandbox': False, 'reason': str(error)}


def _remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _copy_contents(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.name == '.git':
            continue
        target = destination / path.name
        if path.is_symlink():
            target.symlink_to(os.readlink(path))
        elif path.is_dir():
            _copy_contents(path, target)
        elif path.is_file():
            shutil.copy2(path, target, follow_symlinks=False)
        else:
            raise IsolationError('unsupported special file in isolated workspace: ' + path.name)


def prepare_execution(spec, argv, worktree, task_folder, env):
    normalized = validate_spec(spec)
    worktree, task_folder = Path(worktree).resolve(), Path(task_folder).resolve()
    if not isinstance(argv, list) or not argv or not all(isinstance(part, str) and '\0' not in part for part in argv):
        raise IsolationError('execution argv must be a fixed string list')
    if normalized['backend'] == 'local':
        return Execution(list(argv), worktree, dict(env), False, lambda: None, lambda: None)
    if task_folder.is_relative_to(worktree) or worktree.is_relative_to(task_folder):
        raise IsolationError('container control folder and worktree must be separate directories')
    readiness = probe(normalized)
    if not readiness['available']:
        raise IsolationError(readiness.get('reason', 'container isolation unavailable'))
    if ',' in str(task_folder) or ',' in str(worktree):
        raise IsolationError('commas in container workspace paths are unsupported')
    snapshot = task_folder / 'isolated-workspace'
    snapshot.mkdir(mode=0o700, exist_ok=False)
    _copy_contents(worktree, snapshot)
    name = 'sth-factory-' + uuid.uuid4().hex
    docker = _docker_command()
    environment = _docker_env()
    command = docker + [
        'run', '--interactive', '--rm', '--name', name, '--label', 'io.sth.factory.container=' + name, '--pull=never', '--init',
        '--read-only', '--network=none', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
        '--user=' + normalized['user'], '--pids-limit=' + str(normalized['pids_limit']),
        '--cpus=' + str(normalized['cpus']), '--memory=' + str(normalized['memory_mb']) + 'm',
        '--memory-swap=' + str(normalized['memory_mb']) + 'm',
        '--tmpfs', '/tmp:rw,nosuid,nodev,size=' + str(normalized['tmp_mb']) + 'm,mode=1777',
        '--mount', 'type=bind,src=' + str(snapshot) + ',dst=/workspace',
        '--workdir=/workspace', '--env=HOME=/tmp', '--env=LANG=C.UTF-8',
        '--env=PATH=/usr/local/bin:/usr/bin:/bin', '--env=PYTHONDONTWRITEBYTECODE=1',
    ]
    for proxy in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'):
        command.append('--env=' + proxy + '=')
    command += ['--entrypoint', argv[0], normalized['image'], *argv[1:]]
    (task_folder / 'container-control.json').write_text(json.dumps({'container_name': name, 'image': normalized['image'],
                                                                'network': 'none', 'security_sandbox': True}, indent=2))

    def cleanup():
        result = subprocess.run(docker + ['rm', '--force', name], env=environment, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=10)
        if result.returncode and b'No such container' not in result.stderr:
            raise IsolationError('container cleanup not confirmed: ' + result.stderr.decode(errors='replace')[:500])

    def collect():
        for path in worktree.iterdir():
            if path.name != '.git':
                _remove(path)
        _copy_contents(snapshot, worktree)

    return Execution(command, task_folder, environment, True, collect, cleanup, name)

"""Local orchestration for trusted operator policies; worktrees are not sandboxes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import threading
import time

from durability import DurableState, RunLease, StateError
from isolation import IsolationError, cleanup_container, prepare_execution, validate_spec
from runtime_contract import make_request


class FactoryError(Exception):
    pass


class Interrupted(FactoryError):
    def __init__(self, status):
        self.status = status
        super().__init__(status)


def validate(plan, policy):
    if not isinstance(plan, dict) or not isinstance(policy, dict):
        raise FactoryError('plan and policy must be JSON objects')
    validate_spec(policy.get('isolation'))
    if type(policy.get('max_attempts', 1)) is not int or not 1 <= policy.get('max_attempts', 1) <= 3:
        raise FactoryError('max_attempts must be an integer from 1 to 3')
    for key, default, maximum in [('max_tasks', 20, 1000), ('workers', 2, 32),
                                  ('task_timeout', 60, 86400), ('run_timeout', 300, 86400),
                                  ('max_output_bytes', 1048576, 16777216)]:
        value = policy.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= maximum:
            raise FactoryError('invalid policy limit: ' + key)
        if key in ('max_tasks', 'workers', 'max_output_bytes') and not isinstance(value, int):
            raise FactoryError('integer required: ' + key)
    tasks = plan.get('tasks')
    if not isinstance(tasks, list) or not tasks or len(tasks) > policy.get('max_tasks', 20):
        raise FactoryError('task count outside operator budget')
    commands = policy.get('commands', {})
    if not isinstance(commands, dict):
        raise FactoryError('commands must be an operator mapping')
    for name, argv in commands.items():
        if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and '\0' not in arg for arg in argv) or not Path(argv[0]).is_absolute():
            raise FactoryError('command must be a fixed argv with absolute executable: ' + name)
    by_id = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise FactoryError('task must be a JSON object')
        identifier = task.get('id', '')
        if not isinstance(identifier, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', identifier) or identifier in by_id:
            raise FactoryError('invalid or duplicate task id')
        if task.get('runtime') not in ('fake', 'command'):
            raise FactoryError('unknown runtime')
        if task['runtime'] == 'command' and (not isinstance(task.get('command'), str) or task['command'] not in commands):
            raise FactoryError('command not authorized by operator policy')
        if not isinstance(task.get('files', {}), dict) or not all(isinstance(name, str) and isinstance(content, str) for name, content in task.get('files', {}).items()):
            raise FactoryError('fake files must map paths to text')
        if not isinstance(task.get('depends_on', []), list) or not all(isinstance(dep, str) for dep in task.get('depends_on', [])):
            raise FactoryError('dependencies must be task ids')
        if not isinstance(task.get('assets', []), list) or not all(isinstance(asset, str) for asset in task.get('assets', [])):
            raise FactoryError('assets must be local library ids')
        by_id[identifier] = task
    ordered, active, visited = [], set(), set()

    def visit(identifier):
        if identifier not in by_id:
            raise FactoryError('unknown dependency: ' + identifier)
        if identifier in active:
            raise FactoryError('dependency cycle')
        if identifier in visited:
            return
        active.add(identifier)
        for dependency in by_id[identifier].get('depends_on', []):
            visit(dependency)
        active.remove(identifier)
        visited.add(identifier)
        ordered.append(identifier)

    for identifier in by_id:
        visit(identifier)
    return by_id, ordered


def safe_write(root, name, content):
    relative = Path(name)
    if relative.is_absolute() or not relative.parts or any(part in ('..', '.git') for part in relative.parts):
        raise FactoryError('unsafe fake output path')
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise FactoryError('symlink output path')
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_text(content)


class Factory:
    def __init__(self, repo, output, policy, sth=None, cancel_file=None):
        self.repo = Path(repo).resolve()
        self.output = Path(output).absolute()
        self.policy = policy
        self.sth = str(Path(sth).resolve()) if sth else None
        self.cancel_file = Path(cancel_file) if cancel_file else None
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.worktree_lock = threading.Lock()
        self.local = threading.local()
        self.state = None

    def env(self, home):
        home.mkdir(parents=True, exist_ok=True)
        return {'PATH': os.defpath, 'HOME': str(home), 'LANG': 'C.UTF-8',
                'PYTHONDONTWRITEBYTECODE': '1',
                'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                'GIT_TERMINAL_PROMPT': '0', 'STH_MCP_LOCAL_ONLY': '1',
                'STH_USER_CONFIG_DIR': str(home / '.sth'),
                'GIT_AUTHOR_NAME': 'STH Factory', 'GIT_AUTHOR_EMAIL': 'factory@example.invalid',
                'GIT_COMMITTER_NAME': 'STH Factory', 'GIT_COMMITTER_EMAIL': 'factory@example.invalid'}

    def git(self, root, *args, data=None):
        command = ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                   '-c', 'diff.external=', '-C', str(root), *args]
        deadline = min(self.deadline, getattr(self.local, 'deadline', self.deadline))
        self.interrupt(deadline)
        with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            source.write(data or b'')
            source.seek(0)
            process = subprocess.Popen(command, stdin=source, stdout=stdout, stderr=stderr,
                                       env=self.env(self.output / 'operator-home'), start_new_session=True)
            try:
                if self.state:
                    self.state.record_process(process.pid, getattr(self.local, 'task', None))
                while True:
                    self.interrupt(deadline)
                    if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > self.policy.get('max_output_bytes', 1048576):
                        raise FactoryError('git output limit exceeded')
                    if process.poll() is not None:
                        break
                    time.sleep(.01)
                stderr.seek(0)
                if process.returncode:
                    raise FactoryError('git ' + args[0] + ': ' + stderr.read(2000).decode(errors='replace'))
                stdout.seek(0)
                return stdout.read()
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                if self.state:
                    self.state.forget_process(process.pid)

    def fingerprint(self):
        # Content is hashed in memory, never copied into evidence. Ignored files are excluded.
        digest = hashlib.sha256()
        for args in [('rev-parse', 'HEAD'), ('status', '--porcelain=v1', '--untracked-files=all'),
                     ('diff', '--no-ext-diff', '--no-textconv', '--binary', 'HEAD'),
                     ('diff', '--cached', '--no-ext-diff', '--no-textconv', '--binary', 'HEAD')]:
            digest.update(self.git(self.repo, *args))
        names = self.git(self.repo, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split(b'\0')
        for name in sorted(set(names) - {b''}):
            path = self.repo / os.fsdecode(name)
            digest.update(name)
            try:
                digest.update(str(path.lstat().st_mode).encode())
                if path.is_symlink():
                    digest.update(os.fsencode(os.readlink(path)))
                elif path.is_file():
                    with path.open('rb') as stream:
                        while chunk := stream.read(65536):
                            self.interrupt(self.deadline)
                            digest.update(chunk)
            except FileNotFoundError:
                digest.update(b'deleted')
        return digest.hexdigest()

    def event(self, event, **fields):
        payload = {'event': event, 'time': time.time(), **fields}
        with self.lock, (self.output / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps(payload) + '\n')
        if self.state:
            self.state.event(payload)

    def interrupt(self, deadline):
        if self.stop.is_set() or (self.cancel_file and self.cancel_file.exists()):
            raise Interrupted('cancelled')
        if time.monotonic() >= deadline:
            raise Interrupted('timed_out')

    def process(self, argv, cwd, folder, payload, deadline, label, env=None):
        self.interrupt(deadline)
        stdout_path, stderr_path = folder / (label + '.stdout'), folder / (label + '.stderr')
        input_path = folder / (label + '.input.json')
        input_path.write_text(payload)
        with input_path.open('rb') as source, stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
            process = subprocess.Popen(argv, cwd=cwd, env=env if env is not None else self.env(folder / 'home'),
                                       stdin=source, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                if self.state:
                    self.state.record_process(process.pid, getattr(self.local, 'task', None))
                while True:
                    self.interrupt(deadline)
                    if stdout_path.stat().st_size + stderr_path.stat().st_size > self.policy.get('max_output_bytes', 1048576):
                        raise FactoryError('process output limit exceeded')
                    if process.poll() is not None:
                        break
                    time.sleep(.02)
                if process.returncode:
                    raise FactoryError(f'{label} exited {process.returncode}')
            finally:
                # Also terminate surviving children when the parent exits normally.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                if self.state:
                    self.state.forget_process(process.pid)
        return stdout_path.read_bytes()

    def bridge(self, worktree, folder, task, deadline):
        methods = [('handshake', {'protocol_version': 1}), ('status', {})]
        methods += [('library.get', {'id': asset}) for asset in task.get('assets', [])]
        if not self.sth:
            if task.get('assets'):
                raise FactoryError('STH executable required for assets')
            return None
        frames = [{'jsonrpc': '2.0', 'id': index, 'method': method, 'params': params}
                  for index, (method, params) in enumerate(methods, 1)]
        raw = self.process([self.sth, 'bridge', '--stdio'], worktree, folder,
                           ''.join(json.dumps(frame) + '\n' for frame in frames), deadline, 'sth')
        responses = [json.loads(line) for line in raw.splitlines()]
        if len(responses) != len(frames):
            raise FactoryError('invalid STH frame count')
        for frame, response in zip(frames, responses):
            if response.get('jsonrpc') != '2.0' or response.get('id') != frame['id'] or 'error' in response or 'result' not in response:
                raise FactoryError('STH RPC failed: ' + frame['method'])
        handshake = responses[0]['result']
        if handshake.get('protocol_version') != 1 or not all(method in handshake.get('methods', []) for method, _ in methods):
            raise FactoryError('incompatible STH bridge')
        (folder / 'sth.json').write_text(json.dumps(responses, indent=2))
        return {'status': responses[1]['result'], 'assets': [response['result'] for response in responses[2:]]}

    def ancestors(self, task):
        found = set()

        def collect(identifier):
            if identifier not in found:
                found.add(identifier)
                for dependency in self.tasks[identifier].get('depends_on', []):
                    collect(dependency)

        for dependency in task.get('depends_on', []):
            collect(dependency)
        return [identifier for identifier in self.ordered if identifier in found]

    def execute(self, identifier):
        task = self.tasks[identifier]
        self.local.task = identifier
        if self.state:
            self.state.start(identifier, self.policy.get('max_attempts', 1))
        folder = self.output / 'tasks' / identifier
        folder.mkdir(parents=True)
        worktree = self.output / 'worktrees' / identifier
        deadline = min(self.deadline, time.monotonic() + self.policy.get('task_timeout', 60))
        self.local.deadline = deadline
        self.event('started', task=identifier)
        result = {'status': 'failed', 'worktree': str(worktree), 'security_sandbox': False,
                  'isolation_backend': 'local'}
        try:
            self.interrupt(deadline)
            with self.worktree_lock:
                self.git(self.mirror, 'worktree', 'add', '--detach', str(worktree), self.base)
            for dependency in self.ancestors(task):
                patch = (self.output / 'tasks' / dependency / 'delta.patch').read_bytes()
                if patch:
                    self.git(worktree, 'apply', '--index', '--binary', '-', data=patch)
            baseline = self.git(worktree, 'write-tree').decode().strip()
            context = self.bridge(worktree, folder, task, deadline)
            request = make_request(task, context)
            if task['runtime'] == 'fake':
                for name, content in task.get('files', {}).items():
                    self.interrupt(deadline)
                    safe_write(worktree, name, content)
            else:
                execution = prepare_execution(self.policy.get('isolation'), self.policy['commands'][task['command']],
                                              worktree, folder, self.env(folder / 'home'))
                result.update(security_sandbox=execution.security_sandbox,
                              isolation_backend='container' if execution.security_sandbox else 'local')
                try:
                    self.process(execution.argv, execution.cwd, folder, json.dumps(request), deadline, 'runtime',
                                 env=execution.env)
                    self.interrupt(deadline)
                    execution.collect()
                finally:
                    execution.cleanup()
            self.interrupt(deadline)
            self.git(worktree, 'add', '-A')
            delta = self.git(worktree, 'diff', '--cached', '--no-ext-diff', '--no-textconv', '--binary', baseline)
            changes = self.git(worktree, 'diff', '--cached', '--no-ext-diff', '--no-textconv', '--binary', self.base)
            (folder / 'delta.patch').write_bytes(delta)
            (folder / 'changes.patch').write_bytes(changes)
            result.update(status='succeeded', patch_sha256=hashlib.sha256(changes).hexdigest(),
                          delta_sha256=hashlib.sha256(delta).hexdigest())
        except Interrupted as error:
            result.update(status=error.status, error=str(error))
        except Exception as error:
            result['error'] = str(error)
        (folder / 'result.json').write_text(json.dumps(result, indent=2))
        if self.state:
            self.state.finish(identifier, result)
        self.event('finished', task=identifier, **result)
        return result

    def run(self, plan):
        self.tasks, self.ordered = validate(plan, self.policy)
        if self.output.resolve().is_relative_to(self.repo):
            raise FactoryError('run output must be outside source repository')
        self.output.mkdir(parents=True, exist_ok=False, mode=0o700)
        with RunLease(self.output):
            self.state = DurableState(self.output)
            metadata = {'repo': str(self.repo), 'policy': self.policy, 'plan': plan, 'sth': self.sth,
                        'deadline_epoch': time.time() + self.policy.get('run_timeout', 300), 'phase': 'setup'}
            self.state.initialize(metadata, self.ordered)
            return self._new_run(plan)

    def _new_run(self, plan):
        self.deadline = time.monotonic() + self.policy.get('run_timeout', 300)
        (self.output / 'plan.json').write_text(json.dumps(plan, indent=2))
        (self.output / 'policy.json').write_text(json.dumps(self.policy, indent=2))
        self.event('run_started', phase='setup')
        try:
            before = self.fingerprint()
            self.base = self.git(self.repo, 'rev-parse', 'HEAD').decode().strip()
            self.mirror = self.output / 'repository.git'
            self.git(self.output, 'clone', '--bare', '--no-local', '--', str(self.repo), str(self.mirror))
            self.state.update_metadata(base=self.base, source_fingerprint=before, phase='execution')
        except Exception as error:
            summary = {'status': error.status if isinstance(error, Interrupted) else 'failed',
                       'phase': 'setup', 'error': str(error), 'source_unchanged': None,
                       'tasks': {identifier: {'status': 'not_started'} for identifier in self.ordered},
                       'security_sandbox': False}
            (self.output / 'summary.json').write_text(json.dumps(summary, indent=2))
            self.event('run_finished', phase='setup', status=summary['status'], error=str(error))
            return summary
        self.event('setup_finished', base=self.base)
        return self._schedule(before)

    def _schedule(self, before, results=None):
        results = {} if results is None else dict(results)
        pending, running = set(self.ordered) - set(results), {}
        with ThreadPoolExecutor(max_workers=self.policy.get('workers', 2)) as pool:
            while pending or running:
                for identifier in self.ordered:
                    if identifier not in pending:
                        continue
                    dependencies = self.tasks[identifier].get('depends_on', [])
                    if not all(dependency in results for dependency in dependencies):
                        continue
                    if any(results[dependency]['status'] != 'succeeded' for dependency in dependencies):
                        results[identifier] = {'status': 'blocked'}
                        self.state.finish(identifier, results[identifier])
                        self.event('blocked', task=identifier)
                        pending.remove(identifier)
                    elif len(running) < self.policy.get('workers', 2):
                        running[pool.submit(self.execute, identifier)] = identifier
                        pending.remove(identifier)
                for future in list(running):
                    if future.done():
                        results[running.pop(future)] = future.result()
                time.sleep(.01)
        try:
            unchanged = before == self.fingerprint()
        except Interrupted:
            unchanged = None
        summary = {'status': 'succeeded' if unchanged and all(result['status'] == 'succeeded' for result in results.values()) else 'failed',
                   'base': self.base, 'source_unchanged': unchanged, 'tasks': results,
                   'sth': self.sth, 'security_sandbox': bool(results) and all(result.get('security_sandbox', False) for result in results.values())}
        (self.output / 'summary.json').write_text(json.dumps(summary, indent=2))
        self.event('run_finished', status=summary['status'])
        self.state.update_metadata(status=summary['status'])
        return summary

    def resume(self, retry_tasks=None):
        retry_tasks = [] if retry_tasks is None else retry_tasks
        if not self.output.is_dir() or not (self.output / 'state.sqlite3').is_file():
            raise FactoryError('durable run state not found')
        with RunLease(self.output):
            self.state = DurableState(self.output)
            metadata = self.state.metadata()
            if metadata['repo'] != str(self.repo) or metadata['policy'] != self.policy or metadata['sth'] != self.sth:
                raise FactoryError('resume requires the original repository, operator policy and STH executable')
            if metadata['phase'] != 'execution':
                raise FactoryError('setup did not finish; use a fresh run')
            self.tasks, self.ordered = validate(metadata['plan'], self.policy)
            self.deadline = time.monotonic() + max(0, metadata['deadline_epoch'] - time.time())
            self.interrupt(self.deadline)
            self.base, self.mirror = metadata['base'], self.output / 'repository.git'
            before = metadata['source_fingerprint']
            if self.fingerprint() != before:
                raise FactoryError('source repository changed since run start; use a fresh run')
            self.state.assert_no_live_processes()
            self.state.recover_interrupted()
            for identifier in retry_tasks:
                if identifier not in self.tasks:
                    raise FactoryError('unknown retry task')
                self._archive_attempt(identifier)
                self.state.retry(identifier, self.policy.get('max_attempts', 1))
            results = {}
            for identifier, record in self.state.tasks().items():
                if record['status'] == 'pending':
                    continue
                result = record['result'] or {'status': record['status']}
                if result['status'] == 'succeeded':
                    folder = self.output / 'tasks' / identifier
                    for filename, field in [('changes.patch', 'patch_sha256'), ('delta.patch', 'delta_sha256')]:
                        patch = folder / filename
                        if patch.is_symlink() or not patch.is_file() or hashlib.sha256(patch.read_bytes()).hexdigest() != result.get(field):
                            raise FactoryError('cached task evidence changed: ' + identifier)
                results[identifier] = result
            self.event('run_resumed', reused=list(results), retry_tasks=retry_tasks)
            return self._schedule(before, results)

    def _archive_attempt(self, identifier):
        record = self.state.tasks()[identifier]
        if record['status'] not in ('failed', 'timed_out', 'cancelled', 'interrupted') or record['attempts'] >= self.policy.get('max_attempts', 1):
            raise FactoryError('explicit retry is outside operator attempt budget')
        folder = self.output / 'tasks' / identifier
        if (folder / 'container-control.json').exists() and record['status'] == 'interrupted':
            control = folder / 'container-control.json'
            if control.is_symlink():
                raise FactoryError('container recovery metadata must not be a symlink')
            container = json.loads(control.read_text())
            cleanup_container(self.policy.get('isolation'), container['container_name'])
        archive = self.output / 'attempts' / identifier / str(record['attempts'])
        if archive.is_symlink() or (archive.exists() and not archive.is_dir()):
            raise FactoryError('retry archive is unsafe; use a fresh run')
        archive.mkdir(parents=True, exist_ok=True)
        worktree = self.output / 'worktrees' / identifier
        if worktree.exists():
            if (archive / 'worktree').exists():
                raise FactoryError('retry archive conflicts with current worktree; use a fresh run')
            with self.worktree_lock:
                self.git(self.mirror, 'worktree', 'move', str(worktree), str(archive / 'worktree'))
        if folder.exists():
            if (archive / 'evidence').exists():
                raise FactoryError('retry archive conflicts with current evidence; use a fresh run')
            folder.rename(archive / 'evidence')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['plan', 'run', 'resume', 'init', 'doctor', 'status', 'review',
                                         'serve', 'github-prepare', 'github-draft'])
    parser.add_argument('--plan')
    parser.add_argument('--policy', help='Trusted operator policy, outside task/agent control')
    parser.add_argument('--repo')
    parser.add_argument('--output')
    parser.add_argument('--sth')
    parser.add_argument('--cancel-file')
    parser.add_argument('--retry-task', action='append', default=[])
    parser.add_argument('--destination')
    parser.add_argument('--template', choices=['python', 'node'], default='python')
    parser.add_argument('--run-dir')
    parser.add_argument('--task')
    parser.add_argument('--runs-root')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--repository')
    parser.add_argument('--base', default='main')
    parser.add_argument('--head')
    parser.add_argument('--prepared')
    parser.add_argument('--request-draft', action='store_true', help='Explicitly request a remote draft PR for a reviewed prepared request')
    parser.add_argument('--probe-isolation', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'init':
            from project_setup import initialize_project
            if not args.destination:
                raise FactoryError('--destination required')
            print(json.dumps(initialize_project(args.destination, args.template), indent=2))
            return 0
        if args.action in ('status', 'review'):
            from monitoring import status, review
            if not args.run_dir:
                raise FactoryError('--run-dir required')
            print(json.dumps(status(args.run_dir) if args.action == 'status' else review(args.run_dir, args.task), indent=2))
            return 0
        if args.action == 'serve':
            from cockpit import make_server
            if not args.runs_root:
                raise FactoryError('--runs-root required')
            server = make_server(args.runs_root, port=args.port)
            print(json.dumps({'url': server.url, 'read_only': True, 'loopback_only': True}), flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        if args.action == 'github-prepare':
            from github_integration import prepare_pr
            if not args.run_dir or not args.task or not args.repository:
                raise FactoryError('--run-dir, --task and --repository required')
            print(json.dumps(prepare_pr(args.run_dir, args.task, args.repository, args.base, args.head), indent=2))
            return 0
        if args.action == 'github-draft':
            from github_integration import create_draft_pr
            if not args.request_draft or not args.prepared:
                raise FactoryError('review a prepared request, then explicitly provide --prepared and --request-draft')
            print(json.dumps(create_draft_pr(json.loads(Path(args.prepared).read_text()), requested=True), indent=2))
            return 0
        if not args.policy:
            raise FactoryError('--policy required')
        policy = json.loads(Path(args.policy).read_text())
        if args.action == 'doctor':
            from project_setup import doctor
            from isolation import probe
            if not args.repo:
                raise FactoryError('--repo required')
            diagnosis = doctor(args.repo, policy, sth=args.sth)
            if args.probe_isolation:
                diagnosis['isolation_probe'] = probe(policy.get('isolation'))
                diagnosis['ready'] = diagnosis['ready'] and diagnosis['isolation_probe']['available']
            print(json.dumps(diagnosis, indent=2))
            return 0 if diagnosis['ready'] else 1
        if args.action == 'resume':
            if not args.repo or not args.output:
                raise FactoryError('--repo and --output required')
            runner = Factory(args.repo, args.output, policy, sth=args.sth, cancel_file=args.cancel_file)
            signal.signal(signal.SIGINT, lambda *_: runner.stop.set())
            signal.signal(signal.SIGTERM, lambda *_: runner.stop.set())
            result = runner.resume(retry_tasks=args.retry_task)
            print(json.dumps(result, indent=2))
            return 0 if result['status'] == 'succeeded' else 1
        if not args.plan:
            raise FactoryError('--plan required')
        plan = json.loads(Path(args.plan).read_text())
        _, ordered = validate(plan, policy)
        if args.action == 'plan':
            print(json.dumps({'order': ordered, 'max_launches': len(ordered), 'workers': policy.get('workers', 2)}))
            return 0
        if not args.repo or not args.output:
            raise FactoryError('--repo and --output required for run')
        runner = Factory(args.repo, args.output, policy, sth=args.sth, cancel_file=args.cancel_file)
        signal.signal(signal.SIGINT, lambda *_: runner.stop.set())
        signal.signal(signal.SIGTERM, lambda *_: runner.stop.set())
        result = runner.run(plan)
        print(json.dumps(result, indent=2))
        return 0 if result['status'] == 'succeeded' else 1
    except (FactoryError, IsolationError, OSError, ValueError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

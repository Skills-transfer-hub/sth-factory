"""Prepare reviewable GitHub requests; remote writes require a separate explicit request."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from urllib.parse import quote


class GitHubIntegrationError(ValueError):
    pass


class PRExecutionUncertainError(GitHubIntegrationError):
    pass


def _read(run, relative, limit):
    path = run
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise GitHubIntegrationError('symlink evidence is not eligible')
    try:
        if not path.is_file() or path.stat().st_size > limit:
            raise GitHubIntegrationError('missing, oversized or non-file evidence')
        content = path.read_bytes()
    except OSError as error:
        raise GitHubIntegrationError('evidence cannot be read') from error
    if len(content) > limit:
        raise GitHubIntegrationError('evidence exceeds size limit')
    return content


def _json(run, relative):
    try:
        value = json.loads(_read(run, relative, 1024 * 1024))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise GitHubIntegrationError('invalid JSON evidence') from error
    if not isinstance(value, dict):
        raise GitHubIntegrationError('evidence must contain a JSON object')
    return value


def _branch(value, optional=False):
    if value is None and optional:
        return
    if (not isinstance(value, str) or not 1 <= len(value) <= 200
            or value.startswith(('-', '/', '.', 'refs/')) or value.endswith(('/', '.', '.lock'))
            or not re.fullmatch(r'[A-Za-z0-9_./-]+', value)
            or any(part in value for part in ('..', '//', '@{'))
            or any(segment.startswith('.') or segment.endswith('.lock') for segment in value.split('/'))):
        raise GitHubIntegrationError('invalid explicit GitHub branch')


def _request_digest(request):
    canonical = json.dumps({key: value for key, value in request.items() if key != 'request_sha256'},
                           sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canonical).hexdigest()


def prepare_pr(run_dir, task, repository, base='main', head=None):
    """Read local evidence only; never invoke GitHub, Git, a shell or an agent."""
    run = Path(run_dir).absolute()
    if run.is_symlink() or not run.is_dir():
        raise GitHubIntegrationError('run must be an existing non-symlink directory')
    if not isinstance(task, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', task):
        raise GitHubIntegrationError('invalid task id')
    if (not isinstance(repository, str) or len(repository) > 201
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}', repository)
            or '..' in repository):
        raise GitHubIntegrationError('repository must be an explicit owner/name')
    _branch(base)
    _branch(head, optional=True)
    if head is not None and head == base:
        raise GitHubIntegrationError('head and base must be distinct')
    summary = _json(run, 'summary.json')
    result = _json(run, Path('tasks') / task / 'result.json')
    task_summary = summary.get('tasks', {}).get(task) if isinstance(summary.get('tasks'), dict) else None
    if (summary.get('status') != 'succeeded' or summary.get('source_unchanged') is not True
            or not isinstance(task_summary, dict) or task_summary.get('status') != 'succeeded'
            or result.get('status') != 'succeeded'):
        raise GitHubIntegrationError('only a successful run with unchanged source is eligible')
    source_commit = summary.get('base')
    if not isinstance(source_commit, str) or not re.fullmatch(r'[a-f0-9]{40}|[a-f0-9]{64}', source_commit):
        raise GitHubIntegrationError('invalid source commit evidence')
    patch = _read(run, Path('tasks') / task / 'changes.patch', 4 * 1024 * 1024)
    digest = hashlib.sha256(patch).hexdigest()
    if not patch or task_summary.get('patch_sha256') != digest or result.get('patch_sha256') != digest:
        raise GitHubIntegrationError('patch digest does not match successful task evidence')
    body = (f'Local factory run completed successfully for task `{task}`.\n\n'
            f'- Source commit: `{source_commit}`\n'
            f'- Cumulative local patch SHA256: `{digest}`\n'
            '- Local source changes were preserved.\n\n'
            'This draft requires human review. The published head branch has not been proven identical '
            'to the local patch; inspect its diff and CI before approval. No merge or deployment is authorized.\n')
    request = {'schema_version': 1, 'operation': 'create_draft_pr', 'run_dir': str(run), 'task': task,
               'repository': repository, 'base': base, 'head': head,
               'title': f'Factory review: {task}', 'body': body, 'source_commit': source_commit,
               'patch_sha256': digest, 'draft': True, 'push': False, 'merge': False, 'deploy': False,
               'authorization': 'Preparation is not permission; a separate explicit request is required.'}
    request['request_sha256'] = _request_digest(request)
    return request


def _receipt(path, value, exclusive=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def create_draft_pr(prepared, requested=False, runner=None):
    """Future opt-in operation. Caller must derive requested from a current user request, never task text."""
    if requested is not True:
        raise GitHubIntegrationError('draft PR creation requires a separate explicit user request')
    if not isinstance(prepared, dict):
        raise GitHubIntegrationError('a prepared request is required')
    try:
        current = prepare_pr(prepared['run_dir'], prepared['task'], prepared['repository'],
                             base=prepared['base'], head=prepared['head'])
    except (KeyError, TypeError) as error:
        raise GitHubIntegrationError('malformed prepared request') from error
    if current != prepared:
        raise GitHubIntegrationError('prepared request or local evidence changed; prepare and review again')
    if current['head'] is None:
        raise GitHubIntegrationError('an explicitly named already published head branch is required')
    execute = runner or subprocess.run
    executable = shutil.which('gh') or 'gh'
    receipt_path = Path(current['run_dir']) / ('github-pr-' + current['request_sha256'] + '.json')
    record = {'request_sha256': current['request_sha256'], 'repository': current['repository'],
              'base': current['base'], 'head': current['head'], 'status': 'pending',
              'phase': 'preflight', 'time': time.time()}
    try:
        _receipt(receipt_path, record, exclusive=True)
    except FileExistsError as error:
        raise GitHubIntegrationError('request already attempted; inspect its receipt and GitHub before any retry') from error
    environment = {**os.environ, 'GH_HOST': 'github.com', 'GH_PROMPT_DISABLED': '1',
                   'GIT_TERMINAL_PROMPT': '0', 'GH_PAGER': 'cat'}
    options = {'check': True, 'capture_output': True, 'text': True, 'timeout': 30, 'env': environment}
    try:
        endpoint = f'repos/{current["repository"]}/git/ref/heads/{quote(current["head"], safe="")}'
        reference = execute([executable, 'api', '--hostname', 'github.com', endpoint], **options)
        if reference.returncode or json.loads(reference.stdout).get('ref') != 'refs/heads/' + current['head']:
            raise GitHubIntegrationError('the explicitly named head branch does not exist')
    except Exception as error:
        record.update(status='preflight_failed', error_type=type(error).__name__)
        _receipt(receipt_path, record)
        raise GitHubIntegrationError('GitHub head preflight failed; no PR creation was attempted') from error
    with tempfile.TemporaryDirectory(prefix='sth-factory-pr-') as temporary:
        body_path = Path(temporary) / 'body.md'
        body_path.write_text(current['body'])
        argv = [executable, 'pr', 'create', '--draft', '--repo', current['repository'],
                '--base', current['base'], '--head', current['head'], '--title', current['title'],
                '--body-file', str(body_path), '--no-maintainer-edit']
        record.update(phase='creation')
        _receipt(receipt_path, record)
        try:
            response = execute(argv, **options)
            url = response.stdout.strip()
            if response.returncode or not re.fullmatch(r'https://github\.com/' + re.escape(current['repository']) + r'/pull/[1-9][0-9]*', url):
                raise GitHubIntegrationError('creation returned an unconfirmed result')
        except Exception as error:
            record.update(status='uncertain', error_type=type(error).__name__)
            _receipt(receipt_path, record)
            raise PRExecutionUncertainError('PR creation outcome is uncertain; inspect GitHub and the receipt before retrying') from error
    record.update(status='created', url=url)
    _receipt(receipt_path, record)
    return {'status': 'created', 'url': url, 'receipt': str(receipt_path), 'draft': True,
            'push': False, 'merge': False, 'deploy': False}

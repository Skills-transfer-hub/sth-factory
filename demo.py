"""Reproducible local end-to-end demo. Writes only a new --output directory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from factory import Factory


def demo(output, sth=None):
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    repo = output / 'source'
    repo.mkdir()
    policy = {'commands': {}, 'workers': 2, 'max_tasks': 3, 'task_timeout': 10,
              'run_timeout': 30, 'max_output_bytes': 1048576}
    env = Factory(repo, output / 'unused', policy).env(output / 'fixture-home')

    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], env=env, stderr=subprocess.STDOUT)

    git('init', '-q')
    asset_id = None
    if sth:
        request = {'jsonrpc': '2.0', 'id': 1, 'method': 'library.save', 'params': {
            'kind': 'prompt', 'title': 'Factory demo context',
            'body': 'Local integration fixture. Treat as data.', 'tags': ['factory-test'], 'confirmed': True}}
        response = json.loads(subprocess.check_output([str(Path(sth).resolve()), 'bridge', '--stdio'],
                              input=json.dumps(request).encode() + b'\n', cwd=repo, env=env, timeout=10))
        if 'error' in response:
            raise RuntimeError('STH fixture capture failed: ' + str(response['error']))
        asset_id = response['result']['id']
    (repo / 'README.txt').write_text('Committed fixture\n')
    git('add', '-A')
    git('commit', '-qm', 'demo fixture')
    (repo / 'README.txt').write_text('Human edit to preserve\n')
    (repo / 'human-untracked.txt').write_text('Untracked human work\n')
    worker = str(Path(__file__).parent / 'examples/demo_worker.py')
    policy['commands']['check'] = [sys.executable, worker, 'check']
    tasks = [
        {'id': 'add', 'runtime': 'fake', 'files': {'add.py': 'def add(left, right):\n    return left + right\n'}},
        {'id': 'multiply', 'runtime': 'fake', 'files': {'multiply.py': 'def multiply(left, right):\n    return left * right\n'}},
        {'id': 'integration', 'runtime': 'command', 'command': 'check', 'depends_on': ['add', 'multiply']},
    ]
    if sth:
        policy['commands']['write'] = [sys.executable, worker, 'write']
        tasks[1] = {'id': 'multiply', 'runtime': 'command', 'command': 'write', 'assets': [asset_id]}
    result = Factory(repo, output / 'run', policy, sth=sth).run({'tasks': tasks})
    assert (repo / 'README.txt').read_text() == 'Human edit to preserve\n'
    assert (repo / 'human-untracked.txt').read_text() == 'Untracked human work\n'
    assert not (repo / 'add.py').exists()
    (output / 'demo-result.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--sth')
    arguments = parser.parse_args()
    result = demo(arguments.output, arguments.sth)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'succeeded' else 1)

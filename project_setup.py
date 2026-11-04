"""Provider-neutral project configuration and non-executing diagnostics."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


class SetupError(ValueError):
    pass


def _template_command(template):
    if template == 'python':
        program = (
            'import sys,unittest; '
            'suite=unittest.defaultTestLoader.discover("."); '
            'count=suite.countTestCases(); '
            'sys.stderr.write("No tests discovered\\n") if count==0 else None; '
            'result=unittest.TextTestRunner(verbosity=2).run(suite) if count else None; '
            'sys.exit(0 if result is not None and result.wasSuccessful() else 1)'
        )
        return [str(Path(sys.executable).resolve()), '-c', program]
    if template == 'node':
        executable = shutil.which('node')
        if executable is None:
            raise SetupError('Node template requires an installed Node executable')
        program = (
            'const {spawnSync}=require("node:child_process"); '
            'const result=spawnSync(process.execPath,["--test","--test-reporter=tap"],{encoding:"utf8"}); '
            'process.stdout.write(result.stdout||""); process.stderr.write(result.stderr||""); '
            'const match=(result.stdout||"").match(/^# tests ([0-9]+)\\s*$/m); '
            'if(!match||Number(match[1])===0){console.error("No tests discovered");process.exit(1);} '
            'process.exit(result.status===0?0:1);'
        )
        return [str(Path(executable).resolve()), '-e', program]
    raise SetupError('unknown project template; choose python or node')


def initialize_project(destination, template='python'):
    """Create a new configuration directory, without changing source or Git state."""
    command = _template_command(template)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise SetupError('configuration destination already exists; nothing was overwritten')
    if not destination.parent.is_dir():
        raise SetupError('configuration parent directory must already exist')
    plan = {'tasks': [{'id': 'test', 'runtime': 'command', 'command': 'test'}]}
    policy = {'commands': {'test': command}, 'workers': 1, 'max_tasks': 10,
              'task_timeout': 60, 'run_timeout': 300, 'max_output_bytes': 1048576}
    readme = (
        '# Factory project configuration\n\n'
        f'Template: {template}. No agent or asset provider is required.\n\n'
        'Review operator-policy.json before running it. The generated command runs the project test suite '
        'and fails when no tests are discovered. It does not install dependencies.\n\n'
        'Run the factory with --plan plan.json --policy operator-policy.json, the explicit --repo path, '
        'and a new --output directory outside the source repository.\n\n'
        'The initial command uses the trusted local runtime. Worktrees are not security sandboxes. '
        'Configure and verify an isolated backend before running untrusted code.\n\n'
        'This directory was created without modifying project files, Git configuration or credentials. '
        'The executable path is local to this machine; regenerate or review it after moving machines.\n'
    )
    documents = {'plan.json': json.dumps(plan, indent=2) + '\n',
                 'operator-policy.json': json.dumps(policy, indent=2) + '\n', 'README.md': readme}
    created = []
    directory_created = False
    try:
        destination.mkdir(mode=0o700)
        directory_created = True
        for filename, content in documents.items():
            target = destination / filename
            with target.open('x', encoding='utf-8') as stream:
                stream.write(content)
            target.chmod(0o600)
            created.append(target)
    except OSError as error:
        for target in created:
            target.unlink(missing_ok=True)
        if directory_created:
            try:
                destination.rmdir()
            except OSError:
                pass
        raise SetupError('configuration could not be created: ' + str(error)) from error
    return {'status': 'created', 'template': template, 'directory': str(destination),
            'plan': str(destination / 'plan.json'), 'policy': str(destination / 'operator-policy.json'),
            'project_code_modified': False, 'git_initialized': False,
            'agent_required': False, 'sth_required': False}


def _executable_available(executable):
    return isinstance(executable, str) and Path(executable).is_absolute() and Path(executable).is_file() and os.access(executable, os.X_OK)


def doctor(repo, policy, sth=None):
    """Inspect prerequisites without executing policy commands or reading credentials."""
    repository = Path(repo).absolute()
    git = shutil.which('git')
    python_ready = sys.version_info >= (3, 12)
    checks = {'python': {'available': python_ready, 'version': '.'.join(map(str, sys.version_info[:3]))},
              'git': {'available': git is not None, 'executable': git},
              'repository': {'path': str(repository), 'status': 'not_git_repository'},
              'commands': {},
              'sth': {'status': 'not_configured', 'required': False},
              'provider_auth': {'status': 'not_checked', 'required_by_core': False,
                                'detail': 'Credentials are never read by doctor; configure authentication in the chosen adapter.'},
              'isolation': {'status': 'not_verified', 'security_sandbox': False,
                            'engines': {name: {'executable_available': shutil.which(name) is not None}
                                        for name in ['docker', 'podman', 'bwrap']},
                            'detail': 'Executable presence is not evidence that a sandbox is usable or secure.'},
              'warnings': []}
    if git is not None and repository.is_dir():
        try:
            result = subprocess.run([git, '-c', 'core.fsmonitor=false', '-C', str(repository),
                                     'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                                    timeout=3, env={'PATH': os.defpath, 'LANG': 'C.UTF-8',
                                                    'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1'})
            if result.returncode == 0:
                checks['repository'].update(status='ready', root=result.stdout.strip())
        except (OSError, subprocess.TimeoutExpired):
            checks['repository']['status'] = 'inspection_failed'
    commands = policy.get('commands') if isinstance(policy, dict) else None
    policy_valid = isinstance(commands, dict)
    if policy_valid:
        for name, argv in commands.items():
            available = isinstance(argv, list) and bool(argv) and _executable_available(argv[0])
            checks['commands'][name] = {'available': available,
                                         'executable': argv[0] if isinstance(argv, list) and argv and isinstance(argv[0], str) else None,
                                         'command_executed': False}
        try:
            from factory import validate
            validate({'tasks': [{'id': 'diagnostic', 'runtime': 'fake'}]}, policy)
        except Exception as error:
            policy_valid = False
            checks['warnings'].append('Policy validation failed: ' + str(error))
    if not policy_valid and not checks['warnings']:
        checks['warnings'].append('Policy must contain a commands mapping.')
    checks['policy'] = {'valid': policy_valid}
    sth_available = True
    if sth is not None:
        sth_available = _executable_available(str(sth))
        checks['sth'] = {'status': 'available' if sth_available else 'missing', 'required': True,
                         'version_verified': False}
    checks['ready'] = bool(python_ready and git and checks['repository']['status'] == 'ready' and
                           policy_valid and all(item['available'] for item in checks['commands'].values()) and sth_available)
    checks['scope'] = 'Local prerequisites only; project tests, provider authentication and isolation were not executed.'
    return checks

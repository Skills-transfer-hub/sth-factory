import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from runtime_contract import make_request

ADAPTER = Path(__file__).resolve().parents[1] / 'runtimes/deepseek.py'


class DeepSeekRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.binary = self.root / 'dsh-stub'

    def stub(self, body):
        self.binary.write_text('#!' + sys.executable + '\nimport json,os,sys\nfrom pathlib import Path\n' + body)
        self.binary.chmod(0o700)

    def invoke(self, *arguments, payload=None):
        request = make_request({'id': 'change', 'prompt': 'literal $(do-not-execute); fix tests'})
        return subprocess.run([sys.executable, str(ADAPTER), '--binary', str(self.binary), *arguments],
                              cwd=self.workspace, input=json.dumps(request) if payload is None else payload,
                              text=True, capture_output=True, timeout=10)

    def test_headless_contract_guards_home_and_stream(self):
        config = self.root / 'operator.yml'
        config.write_text('- id: agent-default-model\n  config: {provider: mock, model: test}\n')
        self.stub('home=Path(os.environ["DSH_HOME"])\n'
                  'args=sys.argv[1:]\n'
                  'print(json.dumps({"type":"session","sessionId":"test","argv":args,"home":str(home),'
                  '"telemetry":os.environ["DSH_TELEMETRY_DISABLED"],'
                  '"guard":Path(args[args.index("--patch",args.index("--patch")+1)+1]).read_text(),'
                  '"prompt":sys.stdin.read()}),flush=True)\n'
                  'print(json.dumps({"type":"final","sessionId":"test","reason":{"kind":"completed"},"text":"done"}))\n')
        result = self.invoke('--config', str(config))
        self.assertEqual(result.returncode, 0, result.stderr)
        opening, final = map(json.loads, result.stdout.splitlines())
        self.assertEqual(opening['argv'][:4], ['--profile', 'headless', '--patch', str(config.resolve())])
        self.assertEqual(opening['argv'][6:], ['--permission-mode', 'workspace-write', '--approval-policy', 'never', '--json', '-'])
        self.assertIn('session-log-deepseek\n  config:\n    enabled: false', opening['guard'])
        self.assertIn('session-telemetry-otel\n  disabled: true', opening['guard'])
        self.assertIn('plugin-package-inventory-deepseek\n  config:\n    enabled: false', opening['guard'])
        self.assertIn('session-title-llm\n  disabled: true', opening['guard'])
        self.assertEqual(opening['telemetry'], '1')
        self.assertFalse(Path(opening['home']).is_relative_to(self.workspace.resolve()))
        self.assertFalse(Path(opening['home']).exists())
        self.assertIn('literal $(do-not-execute)', opening['prompt'])
        self.assertEqual(final['reason']['kind'], 'completed')

    def test_completion_requires_terminal_record_and_exit_zero(self):
        cases = [('', 0), ('not json', 0), ('[]', 0),
                 (json.dumps({'type': 'final', 'reason': None}), 0),
                 (json.dumps({'type': 'final', 'reason': {'kind': 'error'}}), 0),
                 (json.dumps({'type': 'final', 'reason': {'kind': 'completed'}}), 7)]
        completed = json.dumps({'type': 'final', 'reason': {'kind': 'completed'}})
        cases += [(completed + '\n' + completed, 0), (completed + '\n{}', 0), ('x' * (1024 * 1024 + 1), 0)]
        for output, exitcode in cases:
            with self.subTest(output=output[:80], exitcode=exitcode):
                self.stub('sys.stdin.read()\nprint(' + repr(output) + ')\nsys.exit(' + str(exitcode) + ')\n')
                result = self.invoke()
                self.assertNotEqual(result.returncode, 0)
                if exitcode:
                    self.assertEqual(result.returncode, exitcode)

    def test_untrusted_env_and_config_fail_before_launch(self):
        self.stub('Path("launched").touch()\n')
        envfile = self.workspace / '.env'
        for kind in ['file', 'directory', 'symlink']:
            with self.subTest(kind=kind):
                if kind == 'file':
                    envfile.write_text('DEEPSEEK_API_KEY=untrusted\n')
                elif kind == 'directory':
                    envfile.mkdir()
                else:
                    envfile.symlink_to(self.root / 'missing')
                result = self.invoke()
                self.assertEqual(result.returncode, 2)
                self.assertIn('.env', result.stderr)
                envfile.rmdir() if kind == 'directory' else envfile.unlink()
        local_config = self.workspace / 'config.yml'
        local_config.write_text('[]')
        for config in ['relative.yml', str(local_config), str(self.workspace)]:
            with self.subTest(config=config):
                self.assertEqual(self.invoke('--config', config).returncode, 2)
        self.assertFalse((self.workspace / 'launched').exists())

    def test_probe_only_and_invalid_request_do_not_start_session(self):
        self.stub('assert sys.argv[1:]==["--version"]\nprint("0.2.2-rc.1")\n')
        (self.workspace / '.env').write_text('ignored by version probe')
        result = self.invoke('--probe', payload='invalid')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'available': True, 'version_output': '0.2.2-rc.1', 'model_called': False})
        self.stub('Path("launched").touch()\n')
        self.assertEqual(self.invoke(payload='{}').returncode, 2)
        self.assertFalse((self.workspace / 'launched').exists())

    def test_explicit_interpreter_works_without_path_lookup(self):
        self.stub('assert sys.argv[1:]==["--version"]\nprint("interpreter-probe")\n')
        self.binary.chmod(0o600)
        result = self.invoke('--node', sys.executable, '--probe')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['version_output'], 'interpreter-probe')
        self.stub('assert sys.argv[1:3]==["--profile","headless"]\nsys.stdin.read()\n'
                  'print(json.dumps({"type":"final","reason":{"kind":"completed"}}))\n')
        self.binary.chmod(0o600)
        self.assertEqual(self.invoke('--node', sys.executable).returncode, 0)
        self.assertEqual(self.invoke('--node', 'relative-node').returncode, 2)


if __name__ == '__main__':
    unittest.main()

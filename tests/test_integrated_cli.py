import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import test_factory
from factory import Factory


class IntegratedCLITests(test_factory.FactoryFixture, unittest.TestCase):
    def cli(self, *args, expected=0):
        script = Path(__file__).resolve().parents[1] / 'factory.py'
        result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_init_doctor_run_status_review_and_resume(self):
        (self.repo / 'test_example.py').write_text('import unittest\nclass Checks(unittest.TestCase):\n def test_one(self): self.assertEqual(2+2,4)\n')
        test_factory.git(self.repo, 'add', '.')
        test_factory.git(self.repo, 'commit', '-qm', 'checks')
        config = self.root / 'config'
        self.cli('init', '--destination', config)
        policy, plan = config / 'operator-policy.json', config / 'plan.json'
        diagnosis = self.cli('doctor', '--repo', self.repo, '--policy', policy, '--probe-isolation')
        self.assertTrue(diagnosis['ready'])
        output = self.root / 'cli-run'
        result = self.cli('run', '--repo', self.repo, '--output', output, '--policy', policy, '--plan', plan)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(self.cli('status', '--run-dir', output)['status'], 'succeeded')
        self.assertIn('test', self.cli('review', '--run-dir', output)['tasks'])
        self.assertEqual(self.cli('resume', '--repo', self.repo, '--output', output, '--policy', policy)['status'], 'succeeded')

    def test_github_remote_creation_requires_explicit_operator_request(self):
        result = self.cli('github-draft', '--prepared', '/does/not/exist', expected=1)
        self.assertIn('explicitly', result['error'])

    @unittest.skipUnless(os.environ.get('STH_TEST_CONTAINER_IMAGE'), 'Set STH_TEST_CONTAINER_IMAGE for actual isolated integration')
    def test_full_factory_contract_in_real_container(self):
        self.policy.update(task_timeout=10, run_timeout=30,
                           isolation={'backend': 'container', 'image': os.environ['STH_TEST_CONTAINER_IMAGE']})
        self.policy['commands']['implement'] = ['/usr/local/bin/python3', '-c',
            "import json,sys; from pathlib import Path; req=json.load(sys.stdin); assert req['protocol_version']==1 and req['sth'] is None; assert not Path('.git').exists(); Path('generated.py').write_text('value = 42\\n')"]
        self.policy['commands']['check'] = ['/usr/local/bin/python3', '-c',
            "from pathlib import Path; assert Path('generated.py').read_text()=='value = 42\\n'"]
        result = self.run_plan([{'id': 'implement', 'runtime': 'command', 'command': 'implement'},
                                {'id': 'check', 'runtime': 'command', 'command': 'check', 'depends_on': ['implement']}])
        self.assertEqual(result['status'], 'succeeded', result)
        self.assertTrue(result['security_sandbox'])
        self.assertTrue(result['source_unchanged'])
        self.assertFalse((self.repo / 'generated.py').exists())

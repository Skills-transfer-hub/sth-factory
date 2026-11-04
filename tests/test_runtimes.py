import json
from pathlib import Path
import sys
import unittest

import test_factory
from factory import FactoryError, validate


class RuntimeTests(test_factory.FactoryFixture, unittest.TestCase):
    def test_codex_adapter_contract_without_calling_model(self):
        binary = self.root / 'codex-stub'
        binary.write_text('#!' + sys.executable + '\nimport json,sys\n'
                          'print(json.dumps({"argv":sys.argv[1:],"prompt":sys.stdin.read()}))\n')
        binary.chmod(0o700)
        adapter = Path(__file__).resolve().parents[1] / 'runtimes/codex.py'
        self.policy['commands']['codex'] = [sys.executable, str(adapter), '--binary', str(binary)]
        result = self.run_plan([{'id': 'code', 'runtime': 'command', 'command': 'codex', 'prompt': 'implement feature'}])
        self.assertEqual(result['status'], 'succeeded')
        output = json.loads((self.root / 'run/tasks/code/runtime.stdout').read_text())
        self.assertEqual(output['argv'], ['-a', 'never', 'exec', '--ignore-user-config', '--ephemeral', '--sandbox', 'workspace-write', '--json', '-'])
        self.assertIn('implement feature', output['prompt'])

    def test_malformed_input_and_budget_rejected(self):
        for plan in [[], {'tasks': ['not an object']}, {'tasks': [{'id': 'a', 'runtime': 'command', 'command': ['shell']}]},
                     {'tasks': [{'id': 'a', 'runtime': 'fake', 'files': {'bad': 42}}]}]:
            with self.subTest(plan=plan), self.assertRaises(FactoryError):
                validate(plan, self.policy)
        self.policy['max_tasks'] = 1
        with self.assertRaises(FactoryError):
            validate({'tasks': [{'id': 'a', 'runtime': 'fake'}, {'id': 'b', 'runtime': 'fake'}]}, self.policy)

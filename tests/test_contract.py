import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import unittest

import test_factory
from runtime_contract import ContractError, make_request, normalize_metadata, validate_request


class ContractTests(unittest.TestCase):
    def test_versioned_request_preserves_context_without_provider_fields(self):
        task = {'id': 'code', 'runtime': 'command', 'command': 'agent', 'prompt': 'edit a file'}
        context = {'assets': [{'body': 'untrusted context'}]}
        request = make_request(task, context)
        self.assertEqual(request['protocol_version'], 1)
        self.assertEqual(request['task'], task)
        self.assertEqual(request['sth'], context)
        self.assertEqual(validate_request(request), request)
        task['prompt'] = 'changed'
        self.assertEqual(request['task']['prompt'], 'edit a file')

    def test_invalid_requests_fail_before_adapter_launch(self):
        for request in [None, [], {}, {'protocol_version': True, 'task': {}},
                        {'protocol_version': 99, 'task': {}},
                        {'protocol_version': 1, 'task': [], 'sth': None, 'trust': ''},
                        {'protocol_version': 1, 'task': {}, 'sth': None, 'trust': '', 'secret': 'forbidden'},
                        {'protocol_version': 1, 'task': {'number': float('nan')}, 'sth': None, 'trust': ''}]:
            with self.subTest(request=request), self.assertRaises(ContractError):
                validate_request(request)

    def test_accounting_is_optional_and_not_an_enforced_provider_budget(self):
        self.assertEqual(normalize_metadata('custom'), {'adapter_id': 'custom', 'accounting': 'reported'})
        result = normalize_metadata('custom', {'requests': 2, 'input_tokens': 4, 'cost_usd': .02})
        self.assertEqual(result['requests'], 2)
        for fields in [{'requests': -1}, {'requests': True}, {'cost_usd': float('inf')}, {'api_key': 'not retained'}]:
            with self.subTest(fields=fields), self.assertRaises(ContractError):
                normalize_metadata('custom', fields)


class AdapterTests(test_factory.FactoryFixture, unittest.TestCase):
    def stub(self):
        script = self.root / 'cli-stub'
        script.write_text('#!' + sys.executable + '\nimport json,sys\n'
                          'print(json.dumps({"argv":sys.argv[1:],"stdin":sys.stdin.read()}))\n')
        script.chmod(0o700)
        return script

    def test_claude_adapter_uses_restricted_noninteractive_contract(self):
        adapter = Path(__file__).resolve().parents[1] / 'runtimes/claude.py'
        result = subprocess.run([sys.executable, str(adapter), '--binary', str(self.stub())],
                                input=json.dumps(make_request({'id': 'a', 'prompt': 'implement feature'})),
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertIn('--restricted', output['argv'])
        self.assertIn('dontAsk', output['argv'])
        self.assertNotIn('--dangerously-skip-permissions', output['argv'])
        self.assertIn('implement feature', output['stdin'])

    def test_generic_adapter_forwards_contract_without_shell(self):
        adapter = Path(__file__).resolve().parents[1] / 'runtimes/command.py'
        request = make_request({'id': 'a', 'prompt': 'literal $(no-shell)'})
        result = subprocess.run([sys.executable, str(adapter), '--', sys.executable, '-c',
                                 'import sys; print(sys.stdin.read())'],
                                input=json.dumps(request), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), request)

    def test_bad_request_does_not_launch_optional_cli(self):
        adapter = Path(__file__).resolve().parents[1] / 'runtimes/claude.py'
        result = subprocess.run([sys.executable, str(adapter), '--binary', '/missing/executable'],
                                input='{}', text=True, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('contract', result.stderr.lower())


class ProcessConformanceTests(test_factory.FactoryFixture, unittest.TestCase):
    def implementations(self):
        python = self.root / 'python_adapter.py'
        python.write_text('import json,sys,time\nfrom pathlib import Path\nrequest=json.load(sys.stdin)\n'
                          'assert request["protocol_version"] == 1 and request["sth"] is None\n'
                          'mode=request["task"]["prompt"]\n'
                          'if mode == "fail": raise SystemExit(7)\n'
                          'if mode in ("timeout","cancel"): time.sleep(10)\n'
                          'Path("result.txt").write_text("portable\\n")\n')
        implementations = {'python': [sys.executable, str(python)]}
        node_binary = shutil.which('node')
        if node_binary:
            node = self.root / 'node_adapter.js'
            node.write_text('const fs=require("node:fs"); const request=JSON.parse(fs.readFileSync(0,"utf8"));\n'
                            'if(request.protocol_version!==1 || request.sth!==null) process.exit(8);\n'
                            'const mode=request.task.prompt; if(mode==="fail") process.exit(7);\n'
                            'function finish(){fs.writeFileSync("result.txt","portable\\n");}\n'
                            'if(mode==="timeout" || mode==="cancel") setTimeout(finish,10000); else finish();\n')
            implementations['node'] = [node_binary, str(node)]
        return implementations

    def test_two_distinct_process_implementations_share_lifecycle(self):
        implementations = self.implementations()
        if 'node' not in implementations:
            self.skipTest('Node required to prove the second distinct implementation; no LLM required')
        patches = []
        for name, argv in implementations.items():
            for mode in ['success', 'fail', 'timeout', 'cancel']:
                with self.subTest(implementation=name, mode=mode):
                    from factory import Factory
                    output = self.root / (name + '-' + mode)
                    policy = {**self.policy, 'commands': {'agent': argv},
                              'task_timeout': .25 if mode == 'timeout' else 3}
                    marker = self.root / (name + '-marker')
                    if mode == 'cancel':
                        def cancel(folder=output, cancel_file=marker):
                            deadline = time.monotonic() + 4
                            while time.monotonic() < deadline:
                                if (folder / 'tasks/code/runtime.stdout').exists():
                                    cancel_file.touch()
                                    return
                                time.sleep(.005)
                        threading.Thread(target=cancel, daemon=True).start()
                    result = Factory(self.repo, output, policy, cancel_file=marker if mode == 'cancel' else None).run({'tasks': [
                        {'id': 'code', 'runtime': 'command', 'command': 'agent', 'prompt': mode},
                        {'id': 'later', 'runtime': 'fake', 'depends_on': ['code']}]})
                    expected = {'success': 'succeeded', 'fail': 'failed', 'timeout': 'timed_out', 'cancel': 'cancelled'}[mode]
                    self.assertEqual(result['tasks']['code']['status'], expected)
                    self.assertEqual(result['tasks']['later']['status'], 'succeeded' if mode == 'success' else 'blocked')
                    self.assertIsNone(result['sth'])
                    if mode == 'success':
                        patches.append(result['tasks']['code']['patch_sha256'])
        self.assertEqual(len(patches), 2)
        self.assertEqual(patches[0], patches[1])

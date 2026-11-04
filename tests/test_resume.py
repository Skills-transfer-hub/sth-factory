import json
import os
from pathlib import Path
import sys
import subprocess
import time
from unittest import mock
import unittest

import test_factory
from durability import StateError
from factory import Factory, FactoryError


class ResumeTests(test_factory.FactoryFixture, unittest.TestCase):
    def test_completed_tasks_are_reused_without_runtime_replay(self):
        marker = self.root / 'invocations'
        self.policy['commands']['once'] = [sys.executable, '-c',
            f"from pathlib import Path; marker=Path({str(marker)!r}); marker.write_text(marker.read_text()+'x' if marker.exists() else 'x'); Path('result').write_text('done')"]
        first = self.run_plan([{'id': 'a', 'runtime': 'command', 'command': 'once'}])
        result = Factory(self.repo, self.root / 'run', self.policy).resume()
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(marker.read_text(), 'x')
        self.assertEqual(first['tasks']['a']['patch_sha256'], result['tasks']['a']['patch_sha256'])

    def test_policy_change_and_tampered_patch_refused(self):
        self.run_plan([{'id': 'a', 'runtime': 'fake', 'files': {'result': 'done'}}])
        changed = {**self.policy, 'workers': 1}
        with self.assertRaises((FactoryError, StateError)):
            Factory(self.repo, self.root / 'run', changed).resume()
        (self.root / 'run/tasks/a/delta.patch').write_text('tampered')
        with self.assertRaises((FactoryError, StateError)):
            Factory(self.repo, self.root / 'run', self.policy).resume()

    def test_failed_task_not_retried_without_explicit_request(self):
        self.policy['commands']['fail'] = [sys.executable, '-c', 'raise SystemExit(3)']
        self.policy['max_attempts'] = 2
        self.run_plan([{'id': 'a', 'runtime': 'command', 'command': 'fail'}])
        runner = Factory(self.repo, self.root / 'run', self.policy)
        result = runner.resume()
        self.assertEqual(result['tasks']['a']['status'], 'failed')
        result = runner.resume(retry_tasks=['a'])
        self.assertEqual(result['tasks']['a']['status'], 'failed')
        self.assertTrue((self.root / 'run/attempts/a/1/evidence/result.json').exists())
        with self.assertRaises((FactoryError, StateError)):
            runner.resume(retry_tasks=['a'])

    def test_retry_recovers_archive_before_database_commit(self):
        self.policy['commands']['fail'] = [sys.executable, '-c', 'raise SystemExit(3)']
        self.policy['max_attempts'] = 2
        self.run_plan([{'id': 'a', 'runtime': 'command', 'command': 'fail'}])
        runner = Factory(self.repo, self.root / 'run', self.policy)
        with mock.patch('factory.DurableState.retry', side_effect=RuntimeError('simulated supervisor stop')):
            with self.assertRaises(RuntimeError):
                runner.resume(retry_tasks=['a'])
        result = runner.resume(retry_tasks=['a'])
        self.assertEqual(result['tasks']['a']['status'], 'failed')
        self.assertTrue((self.root / 'run/attempts/a/1/evidence/result.json').exists())

    def test_record_process_failure_never_leaves_launched_process(self):
        for operation in ['runtime', 'git']:
            with self.subTest(operation=operation):
                runner = Factory(self.repo, self.root / operation, self.policy)
                runner.output.mkdir()
                runner.deadline = time.monotonic() + 2
                runner.state = mock.Mock()
                runner.state.record_process.side_effect = RuntimeError('durable state unavailable')
                launched = []
                original = subprocess.Popen

                def track(argv, *args, **kwargs):
                    process = original([sys.executable, '-c', 'import time; time.sleep(10)'], *args, **kwargs)
                    launched.append(process.pid)
                    return process

                with mock.patch('factory.subprocess.Popen', side_effect=track):
                    with self.assertRaises(RuntimeError):
                        if operation == 'git':
                            runner.git(self.repo, 'status')
                        else:
                            runner.process([sys.executable], self.repo, runner.output, '{}', runner.deadline, 'runtime')
                with self.assertRaises(ProcessLookupError):
                    os.kill(launched[0], 0)

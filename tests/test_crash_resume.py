import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import unittest

import test_factory
from durability import StateError, process_identity
from factory import Factory


class CrashResumeTests(test_factory.FactoryFixture, unittest.TestCase):
    def test_real_supervisor_crash_requires_explicit_retry_and_reuses_completed_task(self):
        marker = self.root / 'first-launch'
        script = ("from pathlib import Path; import time; marker=Path(" + repr(str(marker)) + "); "
                  "first=not marker.exists(); marker.write_text('seen'); "
                  "time.sleep(10) if first else None; Path('result.txt').write_text('recovered')")
        self.policy.update(max_attempts=2, run_timeout=30, task_timeout=15, workers=1)
        self.policy['commands']['slow'] = [sys.executable, '-c', script]
        self.policy['commands']['check'] = [sys.executable, '-c', "from pathlib import Path; assert Path('result.txt').read_text()=='recovered'"]
        plan = {'tasks': [{'id': 'quick', 'runtime': 'fake', 'files': {'quick.txt': 'once'}},
                           {'id': 'slow', 'runtime': 'command', 'command': 'slow', 'depends_on': ['quick']},
                           {'id': 'check', 'runtime': 'command', 'command': 'check', 'depends_on': ['slow']}]}
        (self.root / 'plan.json').write_text(json.dumps(plan))
        (self.root / 'policy.json').write_text(json.dumps(self.policy))
        output = self.root / 'run'
        factory = Path(__file__).resolve().parents[1] / 'factory.py'
        supervisor = subprocess.Popen([sys.executable, str(factory), 'run', '--repo', str(self.repo),
            '--output', str(output), '--plan', str(self.root / 'plan.json'), '--policy', str(self.root / 'policy.json')],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        runtime_pid, identity = None, None
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if marker.exists():
                    with sqlite3.connect(output / 'state.sqlite3') as database:
                        row = database.execute('SELECT pid,identity FROM processes WHERE task=?', ('slow',)).fetchone()
                    if row:
                        runtime_pid, identity = row
                        break
                time.sleep(.01)
            self.assertIsNotNone(runtime_pid)
            supervisor.kill()
            supervisor.communicate(timeout=3)
            runner = Factory(self.repo, output, self.policy)
            with self.assertRaisesRegex(StateError, 'active'):
                runner.resume()
            self.assertEqual(process_identity(runtime_pid), identity)
            os.killpg(runtime_pid, signal.SIGKILL)
            recovered = runner.resume()
            self.assertEqual(recovered['tasks']['slow']['status'], 'interrupted')
            self.assertEqual(recovered['tasks']['check']['status'], 'blocked')
            result = runner.resume(retry_tasks=['slow'])
            self.assertEqual(result['status'], 'succeeded', result)
            with sqlite3.connect(output / 'state.sqlite3') as database:
                records = dict(database.execute('SELECT id,attempts FROM tasks'))
            self.assertEqual(records, {'quick': 1, 'slow': 2, 'check': 1})
        finally:
            if supervisor.poll() is None:
                supervisor.kill()
                supervisor.communicate(timeout=3)
            if runtime_pid and process_identity(runtime_pid) == identity:
                try:
                    os.killpg(runtime_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

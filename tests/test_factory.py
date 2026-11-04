import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from factory import Factory, FactoryError, validate


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.STDOUT).decode().strip()


class FactoryFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        git(self.repo, 'init', '-q')
        git(self.repo, 'config', 'user.email', 'test@example.invalid')
        git(self.repo, 'config', 'user.name', 'Test')
        (self.repo / 'human.txt').write_text('committed\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'fixture')
        self.policy = {'commands': {}, 'max_tasks': 8, 'workers': 2,
                       'task_timeout': 2, 'run_timeout': 10, 'max_output_bytes': 8192}

    def run_plan(self, tasks, **kwargs):
        runner = Factory(self.repo, self.root / 'run', self.policy, **kwargs)
        return runner.run({'tasks': tasks})


class FactoryTests(FactoryFixture, unittest.TestCase):

    def test_dag_integration_and_human_changes_preserved(self):
        (self.repo / 'human.txt').write_text('human edit\n')
        (self.repo / 'untracked.txt').write_text('keep me')
        self.policy['commands']['check'] = [sys.executable, '-c',
            "from pathlib import Path; assert Path('a.txt').read_text() == 'A'; assert Path('b.txt').read_text() == 'B'"]
        result = self.run_plan([
            {'id': 'a', 'runtime': 'fake', 'files': {'a.txt': 'A'}},
            {'id': 'b', 'runtime': 'fake', 'files': {'b.txt': 'B'}},
            {'id': 'integration', 'depends_on': ['a', 'b'], 'runtime': 'command', 'command': 'check'}])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual((self.repo / 'human.txt').read_text(), 'human edit\n')
        self.assertEqual((self.repo / 'untracked.txt').read_text(), 'keep me')
        self.assertFalse((self.repo / 'a.txt').exists())
        self.assertTrue((self.root / 'run/tasks/integration/changes.patch').read_text())
        events = [json.loads(line) for line in (self.root / 'run/events.jsonl').read_text().splitlines()]
        self.assertGreaterEqual(next(i for i, event in enumerate(events) if event.get('task') == 'integration' and event['event'] == 'started'), 2)
        self.assertTrue(result['source_unchanged'])

    def test_rejects_cycle_unknown_dependency_and_duplicate(self):
        for tasks in [
            [{'id': 'a', 'depends_on': ['a'], 'runtime': 'fake'}],
            [{'id': 'a', 'depends_on': ['missing'], 'runtime': 'fake'}],
            [{'id': 'a', 'runtime': 'fake'}, {'id': 'a', 'runtime': 'fake'}],
            [{'id': '../escape', 'runtime': 'fake'}],
            [{'id': 'a', 'runtime': 'command', 'command': 'unapproved'}],
        ]:
            with self.subTest(tasks=tasks), self.assertRaises(FactoryError):
                validate({'tasks': tasks}, self.policy)

    def test_fake_traversal_and_symlink_rejected(self):
        for name in ['../outside', '/tmp/escape', '.git/config']:
            with self.subTest(name=name):
                result = self.run_plan([{'id': 'a', 'runtime': 'fake', 'files': {name: 'bad'}}])
                self.assertEqual(result['tasks']['a']['status'], 'failed')
                self.root.joinpath('run').rename(self.root / ('done' + str(len(list(self.root.glob('done*'))))))
        os.symlink(self.root, self.repo / 'link')
        git(self.repo, 'add', 'link')
        git(self.repo, 'commit', '-qm', 'symlink fixture')
        result = self.run_plan([{'id': 'a', 'runtime': 'fake', 'files': {'link/escaped': 'bad'}}])
        self.assertEqual(result['tasks']['a']['status'], 'failed')
        self.assertFalse((self.root / 'escaped').exists())

    def test_failure_blocks_dependents(self):
        self.policy['commands']['fail'] = [sys.executable, '-c', 'raise SystemExit(3)']
        result = self.run_plan([{'id': 'bad', 'runtime': 'command', 'command': 'fail'},
                                {'id': 'later', 'runtime': 'fake', 'depends_on': ['bad']}])
        self.assertEqual(result['tasks']['bad']['status'], 'failed')
        self.assertEqual(result['tasks']['later']['status'], 'blocked')

    def test_conflicting_patches_fail_integration(self):
        result = self.run_plan([
            {'id': 'a', 'runtime': 'fake', 'files': {'human.txt': 'A'}},
            {'id': 'b', 'runtime': 'fake', 'files': {'human.txt': 'B'}},
            {'id': 'integration', 'runtime': 'fake', 'depends_on': ['a', 'b']}])
        self.assertEqual(result['tasks']['integration']['status'], 'failed')
        self.assertEqual((self.repo / 'human.txt').read_text(), 'committed\n')

    def test_transitive_dependencies_applied_once(self):
        result = self.run_plan([
            {'id': 'a', 'runtime': 'fake', 'files': {'human.txt': 'A'}},
            {'id': 'b', 'runtime': 'fake', 'depends_on': ['a'], 'files': {'human.txt': 'B'}},
            {'id': 'c', 'runtime': 'fake', 'depends_on': ['a', 'b']}])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual((self.root / 'run/worktrees/c/human.txt').read_text(), 'B')

    def test_timeout_cancellation_and_output_limit(self):
        for mode in ['timeout', 'cancel', 'output']:
            with self.subTest(mode=mode):
                self.policy['task_timeout'] = 0.15 if mode == 'timeout' else 2
                self.policy['commands']['process'] = [sys.executable, '-c',
                    "import time; time.sleep(10)" if mode != 'output' else "print('x' * 20000)"]
                cancel = self.root / 'cancel'
                runner = Factory(self.repo, self.root / 'run', self.policy, cancel_file=cancel)
                process = runner.process

                def cancel_started_process(*args, **kwargs):
                    cancel.touch()
                    return process(*args, **kwargs)

                # Cancel during task execution, independently of Git setup speed.
                with mock.patch.object(runner, 'process', cancel_started_process if mode == 'cancel' else process):
                    result = runner.run({'tasks': [{'id': 'a', 'runtime': 'command', 'command': 'process'}]})
                expected = {'timeout': 'timed_out', 'cancel': 'cancelled', 'output': 'failed'}[mode]
                self.assertEqual(result['tasks']['a']['status'], expected)
                self.root.joinpath('run').rename(self.root / ('done-' + mode))
                cancel.unlink(missing_ok=True)

    def test_process_does_not_inherit_secrets_or_home(self):
        os.environ['STH_FACTORY_TEST_SECRET'] = 'must not leak'
        self.addCleanup(os.environ.pop, 'STH_FACTORY_TEST_SECRET')
        self.policy['commands']['check'] = [sys.executable, '-c',
            "import os,json; from pathlib import Path; request=json.load(__import__('sys').stdin); assert 'STH_FACTORY_TEST_SECRET' not in os.environ; assert Path(os.environ['HOME']).name == 'home'; assert request['task']['prompt'] == 'data only'"]
        result = self.run_plan([{'id': 'a', 'runtime': 'command', 'command': 'check', 'prompt': 'data only'}])
        self.assertEqual(result['status'], 'succeeded')

    def test_existing_run_not_overwritten(self):
        self.run_plan([{'id': 'a', 'runtime': 'fake'}])
        with self.assertRaises((FactoryError, FileExistsError)):
            self.run_plan([{'id': 'a', 'runtime': 'fake'}])

    def test_worktree_is_not_security_sandbox(self):
        outside = self.root / 'outside-marker'
        self.policy['commands']['trusted'] = [sys.executable, '-c',
            f"from pathlib import Path; Path({str(outside)!r}).write_text('reachable')"]
        result = self.run_plan([{'id': 'a', 'runtime': 'command', 'command': 'trusted'}])
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual(outside.read_text(), 'reachable')

    def test_source_untracked_content_change_is_detected(self):
        human = self.repo / 'untracked.txt'
        human.write_text('original')
        self.policy['commands']['trusted'] = [sys.executable, '-c',
            f"from pathlib import Path; Path({str(human)!r}).write_text('changed')"]
        result = self.run_plan([{'id': 'a', 'runtime': 'command', 'command': 'trusted'}])
        self.assertFalse(result['source_unchanged'])
        self.assertEqual(result['status'], 'failed')

    def test_git_respects_task_timeout(self):
        real_popen = subprocess.Popen

        def delayed_checkout(argv, *args, **kwargs):
            if 'worktree' in argv:
                argv = [sys.executable, '-c', 'import time; time.sleep(10)']
            return real_popen(argv, *args, **kwargs)

        self.policy['task_timeout'] = .1
        with mock.patch('factory.subprocess.Popen', side_effect=delayed_checkout):
            started = time.monotonic()
            result = self.run_plan([{'id': 'a', 'runtime': 'fake'}])
        self.assertEqual(result['tasks']['a']['status'], 'timed_out')
        self.assertLess(time.monotonic() - started, 2)

    def test_cancellation_during_clone_keeps_evidence(self):
        real_popen = subprocess.Popen
        cancel = self.root / 'cancel'

        def delayed_clone(argv, *args, **kwargs):
            if 'clone' in argv:
                threading.Timer(.05, cancel.touch).start()
                argv = [sys.executable, '-c', 'import time; time.sleep(10)']
            return real_popen(argv, *args, **kwargs)

        with mock.patch('factory.subprocess.Popen', side_effect=delayed_clone):
            result = self.run_plan([{'id': 'a', 'runtime': 'fake'}], cancel_file=cancel)
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(result['phase'], 'setup')
        self.assertEqual(result['tasks']['a']['status'], 'not_started')
        for name in ['summary.json', 'events.jsonl', 'plan.json', 'policy.json']:
            self.assertTrue((self.root / 'run' / name).exists())

    def test_staged_change_detected_with_identical_worktree_and_status(self):
        runner = Factory(self.repo, self.root / 'fingerprint', self.policy)
        runner.output.mkdir()
        runner.deadline = time.monotonic() + 5
        human = self.repo / 'human.txt'
        human.write_text('first stage')
        git(self.repo, 'add', 'human.txt')
        human.write_text('working tree')
        before_status = git(self.repo, 'status', '--porcelain')
        before = runner.fingerprint()
        human.write_text('second stage')
        git(self.repo, 'add', 'human.txt')
        human.write_text('working tree')
        self.assertEqual(before_status, git(self.repo, 'status', '--porcelain'))
        self.assertNotEqual(before, runner.fingerprint())

    def test_worktree_metadata_creation_is_serialized(self):
        original_git = Factory.git
        active = 0
        guard = threading.Lock()

        def guarded_git(runner, root, *args, **kwargs):
            nonlocal active
            if args[0] != 'worktree':
                return original_git(runner, root, *args, **kwargs)
            with guard:
                active += 1
                concurrent = active > 1
            try:
                if concurrent:
                    raise FactoryError('concurrent worktree metadata mutation')
                time.sleep(.05)
                return original_git(runner, root, *args, **kwargs)
            finally:
                with guard:
                    active -= 1

        with mock.patch.object(Factory, 'git', new=guarded_git):
            result = self.run_plan([{'id': 'a', 'runtime': 'fake'}, {'id': 'b', 'runtime': 'fake'}])
        self.assertEqual(result['status'], 'succeeded')

    def test_timeout_stops_child_in_same_process_group(self):
        self.policy['task_timeout'] = .3
        self.policy['commands']['spawn'] = [sys.executable, '-c',
            "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(10)']); print(child.pid,flush=True); time.sleep(10)"]
        result = self.run_plan([{'id': 'a', 'runtime': 'command', 'command': 'spawn'}])
        self.assertEqual(result['tasks']['a']['status'], 'timed_out')
        child_pid = int((self.root / 'run/tasks/a/runtime.stdout').read_text().strip())
        process_stat = Path('/proc') / str(child_pid) / 'stat'
        if process_stat.exists():
            self.assertIn(process_stat.read_text().split()[2], ['Z', 'X'])

    def test_shared_run_budget_bounds_sequential_tasks(self):
        self.policy.update(run_timeout=.7, task_timeout=2, workers=1)
        self.policy['commands']['wait'] = [sys.executable, '-c', 'import time; time.sleep(.4)']
        started = time.monotonic()
        result = self.run_plan([{'id': identifier, 'runtime': 'command', 'command': 'wait'} for identifier in ['a', 'b', 'c']])
        self.assertEqual(result['status'], 'failed')
        self.assertIn('timed_out', [task['status'] for task in result['tasks'].values()])
        self.assertLess(time.monotonic() - started, 1.5)


if __name__ == '__main__':
    unittest.main()

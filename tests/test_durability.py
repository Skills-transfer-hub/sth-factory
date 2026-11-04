import json
from pathlib import Path
import tempfile
import unittest

from durability import DurableState, RunLease, StateError


class DurabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_committed_tasks_survive_reopen(self):
        state = DurableState(self.root)
        state.initialize({'base': 'abc', 'policy': {'max_attempts': 2}}, ['a', 'b'])
        state.start('a', 2)
        state.finish('a', {'status': 'succeeded', 'patch_sha256': 'digest'})
        recovered = DurableState(self.root)
        self.assertEqual(recovered.metadata()['base'], 'abc')
        self.assertEqual(recovered.tasks()['a']['result']['status'], 'succeeded')
        self.assertEqual(recovered.tasks()['a']['attempts'], 1)
        self.assertEqual(recovered.tasks()['b']['status'], 'pending')

    def test_running_task_requires_explicit_bounded_retry(self):
        state = DurableState(self.root)
        state.initialize({}, ['a'])
        state.start('a', 2)
        state.recover_interrupted()
        self.assertEqual(state.tasks()['a']['status'], 'interrupted')
        with self.assertRaises(StateError):
            state.start('a', 2)
        state.retry('a', 2)
        state.start('a', 2)
        state.finish('a', {'status': 'failed'})
        with self.assertRaises(StateError):
            state.retry('a', 2)

    def test_exclusive_run_lease(self):
        with RunLease(self.root):
            with self.assertRaises(StateError):
                with RunLease(self.root):
                    pass
        with RunLease(self.root):
            pass

    def test_cannot_reinitialize_existing_state(self):
        state = DurableState(self.root)
        state.initialize({'one': 1}, ['a'])
        with self.assertRaises(StateError):
            state.initialize({'one': 2}, ['b'])


if __name__ == '__main__':
    unittest.main()

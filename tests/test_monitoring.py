import json
import fcntl
import os
from pathlib import Path
import tempfile
import unittest

from monitoring import InspectionError, review, status


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run'
        (self.run / 'tasks/build').mkdir(parents=True)
        (self.run / 'plan.json').write_text(json.dumps({'tasks': [{'id': 'build', 'depends_on': []}]}))
        (self.run / 'events.jsonl').write_text(json.dumps({'event': 'started', 'task': 'build'}) + '\n')
        self.lease = (self.run / 'run.lock').open('w')
        fcntl.flock(self.lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.addCleanup(self.lease.close)

    def test_live_status_without_summary_and_completed_summary(self):
        live = status(self.run)
        self.assertEqual(live['status'], 'running')
        self.assertEqual(live['tasks']['build']['status'], 'running')
        self.assertEqual(live['plan']['tasks'][0]['id'], 'build')
        (self.run / 'summary.json').write_text(json.dumps({'status': 'succeeded', 'tasks': {'build': {'status': 'succeeded'}}}))
        self.assertEqual(status(self.run)['status'], 'succeeded')

    def test_review_bounds_log_tail_and_preserves_untrusted_text(self):
        (self.run / 'tasks/build/runtime.stdout').write_text('a' * 1000 + '<script>evil()</script>')
        (self.run / 'tasks/build/changes.patch').write_text('patch\n')
        output = review(self.run, 'build', max_bytes=64)
        self.assertLessEqual(len(output['tasks']['build']['logs']['runtime.stdout']['text'].encode()), 64)
        self.assertTrue(output['tasks']['build']['logs']['runtime.stdout']['truncated'])
        self.assertIn('<script>', output['tasks']['build']['logs']['runtime.stdout']['text'])
        self.assertEqual(output['tasks']['build']['patch']['text'], 'patch\n')

    def test_symlink_files_and_task_traversal_rejected(self):
        secret = self.root / 'secret'
        secret.write_text('do not read')
        os.symlink(secret, self.run / 'summary.json')
        with self.assertRaises(InspectionError):
            status(self.run)
        for task in ['../secret', '..', '/tmp/x', 'a/b']:
            with self.subTest(task=task), self.assertRaises(InspectionError):
                review(self.run, task)

    def test_malformed_and_oversize_metadata_reported(self):
        (self.run / 'summary.json').write_text('not-json')
        with self.assertRaises(InspectionError):
            status(self.run)
        (self.run / 'summary.json').write_text('x' * (1024 * 1024 + 1))
        with self.assertRaises(InspectionError):
            status(self.run)

    def test_symlink_task_directory_rejected(self):
        target = self.root / 'external'
        target.mkdir()
        os.symlink(target, self.run / 'tasks/external')
        with self.assertRaises(InspectionError):
            review(self.run, 'external')

    def test_partial_last_event_does_not_break_live_status(self):
        with (self.run / 'events.jsonl').open('a') as stream:
            stream.write('{"event":')
        snapshot = status(self.run)
        self.assertEqual(snapshot['status'], 'running')
        self.assertTrue(snapshot['warnings'])

    def test_nonregular_file_and_malformed_task_shape_rejected(self):
        os.mkfifo(self.run / 'summary.json')
        with self.assertRaises(InspectionError):
            status(self.run)
        (self.run / 'summary.json').unlink()
        (self.run / 'summary.json').write_text(json.dumps({'tasks': []}))
        with self.assertRaises(InspectionError):
            status(self.run)

    def test_new_run_event_supersedes_stale_summary(self):
        (self.run / 'summary.json').write_text(json.dumps({'status': 'failed', 'tasks': {'build': {'status': 'failed'}}}))
        (self.run / 'events.jsonl').write_text('\n'.join(json.dumps(item) for item in [
            {'event': 'run_finished', 'status': 'failed'}, {'event': 'run_resumed'}, {'event': 'started', 'task': 'build'}]) + '\n')
        self.assertEqual(status(self.run)['tasks']['build']['status'], 'running')
        self.assertEqual(status(self.run)['status'], 'running')

    def test_old_running_event_does_not_claim_a_dead_supervisor_is_working(self):
        fcntl.flock(self.lease.fileno(), fcntl.LOCK_UN)
        snapshot = status(self.run)
        self.assertEqual(snapshot['reported_status'], 'running')
        self.assertEqual(snapshot['status'], 'interrupted')
        self.assertEqual(snapshot['tasks']['build']['status'], 'interrupted')
        self.assertFalse(snapshot['supervisor_active'])

    def test_missing_or_unsafe_lease_is_unknown_not_live(self):
        (self.run / 'run.lock').unlink()
        self.assertEqual(status(self.run)['status'], 'unknown')
        os.mkfifo(self.run / 'run.lock')
        self.assertEqual(status(self.run)['status'], 'unknown')

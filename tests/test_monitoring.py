import json
import fcntl
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

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

    def write_events(self, events):
        (self.run / 'events.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))

    def test_timings_keep_only_latest_session_and_attempt_but_retain_reused_work(self):
        self.write_events([
            {'event': 'run_started', 'time': 10},
            {'event': 'started', 'task': 'build', 'time': 11},
            {'event': 'started', 'task': 'reused', 'time': 12},
            {'event': 'finished', 'task': 'reused', 'status': 'succeeded', 'time': 13},
            {'event': 'finished', 'task': 'build', 'status': 'failed', 'time': 14},
            {'event': 'run_finished', 'time': 15},
            {'event': 'run_resumed', 'time': 100},
            {'event': 'started', 'task': 'build', 'time': 101},
            {'event': 'finished', 'task': 'build', 'status': 'succeeded', 'time': 103},
            {'event': 'run_finished', 'time': 105},
        ])
        snapshot = status(self.run)
        self.assertEqual(snapshot['timing'], {'scope': 'latest_session', 'started_at': 100,
                         'finished_at': 105, 'duration_seconds': 5, 'live': False})
        self.assertEqual(snapshot['tasks']['build']['timing'], {'scope': 'latest_attempt',
                         'started_at': 101, 'finished_at': 103, 'duration_seconds': 2, 'live': False})
        self.assertEqual(snapshot['tasks']['reused']['timing']['duration_seconds'], 1)

    def test_live_timings_require_an_active_supervisor_and_stop_after_interruption(self):
        self.write_events([{'event': 'run_started', 'time': 100},
                           {'event': 'started', 'task': 'build', 'time': 102}])
        with mock.patch('monitoring.time.time', return_value=125):
            snapshot = status(self.run)
            self.assertEqual(snapshot['timing']['duration_seconds'], 25)
            self.assertTrue(snapshot['timing']['live'])
            self.assertEqual(snapshot['tasks']['build']['timing']['duration_seconds'], 23)
            self.assertTrue(snapshot['tasks']['build']['timing']['live'])
            fcntl.flock(self.lease.fileno(), fcntl.LOCK_UN)
            snapshot = status(self.run)
            self.assertIsNone(snapshot['timing']['duration_seconds'])
            self.assertIsNone(snapshot['tasks']['build']['timing']['duration_seconds'])
            self.assertFalse(snapshot['tasks']['build']['timing']['live'])
            (self.run / 'run.lock').unlink()
            self.assertIsNone(status(self.run)['timing']['duration_seconds'])

    def test_resume_does_not_restart_an_unfinished_old_attempt_clock(self):
        self.write_events([{'event': 'run_started', 'time': 10},
                           {'event': 'started', 'task': 'build', 'time': 11},
                           {'event': 'run_resumed', 'time': 100}])
        with mock.patch('monitoring.time.time', return_value=125):
            snapshot = status(self.run)
        self.assertEqual(snapshot['timing']['duration_seconds'], 25)
        self.assertIsNone(snapshot['tasks']['build']['timing']['duration_seconds'])
        self.assertFalse(snapshot['tasks']['build']['timing']['live'])
        with (self.run / 'events.jsonl').open('a') as stream:
            stream.write(json.dumps({'event': 'finished', 'task': 'build', 'time': 130}) + '\n')
        self.assertIsNone(status(self.run)['tasks']['build']['timing']['duration_seconds'])

    def test_bad_or_missing_timestamps_never_create_durations(self):
        bad_values = [None, True, -1, '100', [], {}, float('nan'), float('inf'), 10 ** 400]
        for invalid in bad_values:
            for start, finish in [(invalid, 105), (100, invalid)]:
                with self.subTest(start=start, finish=finish):
                    self.write_events([{'event': 'run_started', 'time': start},
                        {'event': 'started', 'task': 'build', 'time': start},
                        {'event': 'finished', 'task': 'build', 'time': finish},
                        {'event': 'run_finished', 'time': finish}])
                    snapshot = status(self.run)
                    for timing in [snapshot['timing'], snapshot['tasks']['build']['timing']]:
                        self.assertIsNone(timing['duration_seconds'])
                        self.assertFalse(timing['live'])
                        json.dumps(timing, allow_nan=False)
        self.write_events([{'event': 'run_started', 'time': 105},
                           {'event': 'started', 'task': 'build', 'time': 105},
                           {'event': 'finished', 'task': 'build', 'time': 100},
                           {'event': 'run_finished', 'time': 100}])
        snapshot = status(self.run)
        self.assertIsNone(snapshot['timing']['duration_seconds'])
        self.assertIsNone(snapshot['tasks']['build']['timing']['duration_seconds'])
        self.write_events([{'event': 'run_finished', 'time': 100},
                           {'event': 'finished', 'task': 'build', 'time': 100}])
        self.assertIsNone(status(self.run)['tasks']['build']['timing']['duration_seconds'])

    def test_damaged_or_truncated_history_does_not_pair_unrelated_timestamps(self):
        starts = [{'event': 'run_started', 'time': 10},
                  {'event': 'started', 'task': 'build', 'time': 11}]
        finishes = [{'event': 'finished', 'task': 'build', 'time': 13},
                    {'event': 'run_finished', 'time': 15}]
        for damage in ['{"event":\n', '[]\n']:
            self.write_events(starts)
            with (self.run / 'events.jsonl').open('a') as stream:
                stream.write(damage + ''.join(json.dumps(event) + '\n' for event in finishes))
            snapshot = status(self.run)
            self.assertIsNone(snapshot['timing']['duration_seconds'])
            self.assertIsNone(snapshot['tasks']['build']['timing']['duration_seconds'])
            self.assertTrue(snapshot['warnings'])
        self.write_events(starts + [{'event': 'padding', 'text': 'x' * 600}] + finishes)
        with mock.patch('monitoring.METADATA_LIMIT', 512):
            snapshot = status(self.run)
        self.assertIsNone(snapshot['timing']['duration_seconds'])
        self.assertIsNone(snapshot['tasks']['build']['timing']['duration_seconds'])
        self.assertIn('event history truncated to bounded tail', snapshot['warnings'])
        self.write_events([{'event': 'padding', 'text': 'x' * 600}] + starts + finishes)
        with mock.patch('monitoring.METADATA_LIMIT', 512):
            self.assertEqual(status(self.run)['tasks']['build']['timing']['duration_seconds'], 2)

    def test_summary_cannot_supply_timings_and_partial_last_event_invalidates_old_pair(self):
        (self.run / 'summary.json').write_text(json.dumps({'status': 'succeeded',
            'tasks': {'build': {'status': 'succeeded', 'timing': {'duration_seconds': 999}}}}))
        self.assertIsNone(status(self.run)['tasks']['build']['timing']['duration_seconds'])
        self.write_events([{'event': 'started', 'task': 'build', 'time': 10},
                           {'event': 'finished', 'task': 'build', 'time': 15}])
        with (self.run / 'events.jsonl').open('a') as stream:
            stream.write('{"event":')
        self.assertIsNone(status(self.run)['tasks']['build']['timing']['duration_seconds'])

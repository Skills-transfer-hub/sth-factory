import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from github_integration import GitHubIntegrationError, PRExecutionUncertainError, create_draft_pr, prepare_pr
from factory import Factory


class GitHubIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run'
        folder = self.run / 'tasks' / 'implementation'
        folder.mkdir(parents=True)
        patch = b'diff --git a/result.txt b/result.txt\nnew file mode 100644\n--- /dev/null\n+++ b/result.txt\n@@ -0,0 +1 @@\n+result\n'
        self.digest = hashlib.sha256(patch).hexdigest()
        (folder / 'changes.patch').write_bytes(patch)
        result = {'status': 'succeeded', 'patch_sha256': self.digest}
        (folder / 'result.json').write_text(json.dumps(result))
        self.summary = {'status': 'succeeded', 'source_unchanged': True, 'base': 'a' * 40,
                        'tasks': {'implementation': result}}
        (self.run / 'summary.json').write_text(json.dumps(self.summary))

    def prepare(self, **kwargs):
        return prepare_pr(self.run, 'implementation', 'example/project', base='main', **kwargs)

    def test_prepare_is_reviewable_and_never_executes(self):
        with mock.patch('github_integration.subprocess.run') as runner:
            prepared = self.prepare()
        runner.assert_not_called()
        self.assertTrue(prepared['draft'])
        self.assertFalse(prepared['push'])
        self.assertFalse(prepared['merge'])
        self.assertEqual(prepared['patch_sha256'], self.digest)
        self.assertIsNone(prepared['head'])
        self.assertIn('explicit request', prepared['authorization'])

    def test_prepare_from_real_local_factory_run_without_remote_actions(self):
        source = self.root / 'source'
        source.mkdir()
        subprocess.run(['git', 'init', '-q', str(source)], check=True)
        (source / 'README.txt').write_text('committed\n')
        subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(source), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '-qm', 'fixture'], check=True)
        (source / 'README.txt').write_text('human changes\n')
        output = self.root / 'actual-run'
        result = Factory(source, output, {'commands': {}, 'task_timeout': 5, 'run_timeout': 15}).run({
            'tasks': [{'id': 'implementation', 'runtime': 'fake', 'files': {'result.txt': 'new code fixture\n'}}]})
        self.assertEqual(result['status'], 'succeeded')
        with mock.patch('github_integration.subprocess.run') as remote:
            prepared = prepare_pr(output, 'implementation', 'example/project', head='factory/review')
        remote.assert_not_called()
        self.assertEqual(prepared['patch_sha256'], result['tasks']['implementation']['patch_sha256'])
        self.assertEqual((source / 'README.txt').read_text(), 'human changes\n')

    def test_empty_patch_or_mismatched_result_is_rejected(self):
        patch = self.run / 'tasks/implementation/changes.patch'
        original = patch.read_bytes()
        patch.write_bytes(b'')
        with self.assertRaises(GitHubIntegrationError):
            self.prepare()
        patch.write_bytes(original)
        result = self.run / 'tasks/implementation/result.json'
        result.write_text(json.dumps({'status': 'succeeded', 'patch_sha256': '0' * 64}))
        with self.assertRaises(GitHubIntegrationError):
            self.prepare()

    def test_create_denied_without_separate_explicit_request(self):
        prepared = self.prepare(head='factory/change')
        runner = mock.Mock()
        for requested in [False, None, 1, 'yes']:
            with self.subTest(requested=requested), self.assertRaises(GitHubIntegrationError):
                create_draft_pr(prepared, requested=requested, runner=runner)
        runner.assert_not_called()
        self.assertFalse(list(self.run.glob('github-pr-*.json')))

    def test_creation_checks_existing_head_then_uses_fixed_draft_argv(self):
        prepared = self.prepare(head='factory/change')
        bodies = []
        invocations = []

        def runner(argv, **kwargs):
            invocations.append((argv, kwargs))
            if 'api' in argv:
                return SimpleNamespace(returncode=0, stdout=json.dumps({'ref': 'refs/heads/factory/change'}))
            body = Path(argv[argv.index('--body-file') + 1])
            bodies.append(body.read_text())
            return SimpleNamespace(returncode=0, stdout='https://github.com/example/project/pull/42\n')

        result = create_draft_pr(prepared, requested=True, runner=runner)
        self.assertEqual(result['status'], 'created')
        self.assertEqual(result['url'], 'https://github.com/example/project/pull/42')
        self.assertEqual(len(invocations), 2)
        argv, arguments = invocations[1]
        self.assertEqual(argv[1:4], ['pr', 'create', '--draft'])
        self.assertEqual(argv[argv.index('--head') + 1], 'factory/change')
        self.assertEqual(argv[argv.index('--repo') + 1], 'example/project')
        self.assertNotIn('shell', arguments)
        self.assertTrue(arguments['check'])
        self.assertEqual(arguments['env']['GH_PROMPT_DISABLED'], '1')
        self.assertEqual(arguments['env']['GH_HOST'], 'github.com')
        self.assertIn(self.digest, bodies[0])
        self.assertNotIn('git push', ' '.join(argv))
        receipt = json.loads(Path(result['receipt']).read_text())
        self.assertEqual(receipt['status'], 'created')

    def test_replay_does_not_create_second_pr(self):
        prepared = self.prepare(head='factory/change')
        runner = mock.Mock(side_effect=[SimpleNamespace(returncode=0, stdout='{"ref":"refs/heads/factory/change"}'),
                                        SimpleNamespace(returncode=0, stdout='https://github.com/example/project/pull/42')])
        create_draft_pr(prepared, requested=True, runner=runner)
        with self.assertRaises(GitHubIntegrationError):
            create_draft_pr(prepared, requested=True, runner=runner)
        self.assertEqual(runner.call_count, 2)

    def test_mutated_request_or_evidence_fails_before_any_network_action(self):
        prepared = self.prepare(head='factory/change')
        runner = mock.Mock()
        bad = {**prepared, 'repository': 'another/project'}
        with self.assertRaises(GitHubIntegrationError):
            create_draft_pr(bad, requested=True, runner=runner)
        (self.run / 'tasks/implementation/changes.patch').write_text('changed')
        with self.assertRaises(GitHubIntegrationError):
            create_draft_pr(prepared, requested=True, runner=runner)
        runner.assert_not_called()

    def test_failed_or_changed_source_runs_are_not_eligible(self):
        for key, value in [('status', 'failed'), ('source_unchanged', False), ('source_unchanged', None)]:
            with self.subTest(key=key, value=value):
                changed = {**self.summary, key: value}
                (self.run / 'summary.json').write_text(json.dumps(changed))
                with self.assertRaises(GitHubIntegrationError):
                    self.prepare()

    def test_rejects_paths_symlinks_and_oversized_evidence(self):
        with self.assertRaises(GitHubIntegrationError):
            prepare_pr(self.run, '../outside', 'example/project')
        result = self.run / 'tasks/implementation/result.json'
        result.unlink()
        result.symlink_to(self.run / 'summary.json')
        with self.assertRaises(GitHubIntegrationError):
            self.prepare()
        result.unlink()
        result.write_bytes(b'x' * (1024 * 1024 + 1))
        with self.assertRaises(GitHubIntegrationError):
            self.prepare()

    def test_rejects_invalid_repository_and_branch_arguments(self):
        for repository in ['--help', 'https://github.com/example/project', 'owner/repo/extra', 'owner/../repo']:
            with self.subTest(repository=repository), self.assertRaises(GitHubIntegrationError):
                prepare_pr(self.run, 'implementation', repository)
        for branch in ['--help', '../main', 'a..b', 'a@{b}', 'a b', 'a.lock', 'refs/heads/main', 'a:main']:
            with self.subTest(branch=branch), self.assertRaises(GitHubIntegrationError):
                self.prepare(head=branch)

    def test_creation_needs_existing_head_and_does_not_push_it(self):
        prepared = self.prepare(head='factory/change')
        runner = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout='{"ref":"refs/heads/another"}'))
        with self.assertRaises(GitHubIntegrationError):
            create_draft_pr(prepared, requested=True, runner=runner)
        self.assertEqual(runner.call_count, 1)
        self.assertNotIn('pr', runner.call_args.args[0])

    def test_uncertain_creation_is_recorded_and_not_automatically_retried(self):
        prepared = self.prepare(head='factory/change')
        runner = mock.Mock(side_effect=[SimpleNamespace(returncode=0, stdout='{"ref":"refs/heads/factory/change"}'),
                                        subprocess.TimeoutExpired('gh', 30)])
        with self.assertRaises(PRExecutionUncertainError):
            create_draft_pr(prepared, requested=True, runner=runner)
        receipt = json.loads(next(self.run.glob('github-pr-*.json')).read_text())
        self.assertEqual(receipt['status'], 'uncertain')
        with self.assertRaises(GitHubIntegrationError):
            create_draft_pr(prepared, requested=True, runner=runner)
        self.assertEqual(runner.call_count, 2)

    def test_missing_head_or_extra_permission_fields_rejected(self):
        runner = mock.Mock()
        for prepared in [self.prepare(), {**self.prepare(head='factory/change'), 'requested': True}]:
            with self.assertRaises(GitHubIntegrationError):
                create_draft_pr(prepared, requested=True, runner=runner)
        runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from factory import Factory, validate
from project_setup import SetupError, doctor, initialize_project


class ProjectSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def repository(self, name):
        repository = self.root / name
        repository.mkdir()
        subprocess.run(['git', 'init', '-q', str(repository)], check=True)
        return repository

    def commit(self, repository):
        subprocess.run(['git', '-C', str(repository), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(repository), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)

    def test_initialize_creates_neutral_valid_configuration(self):
        destination = self.root / 'configuration'
        result = initialize_project(destination)
        plan = json.loads((destination / 'plan.json').read_text())
        policy = json.loads((destination / 'operator-policy.json').read_text())
        validate(plan, policy)
        self.assertEqual(result['template'], 'python')
        self.assertEqual(plan['tasks'][0]['command'], 'test')
        self.assertTrue(Path(policy['commands']['test'][0]).is_absolute())
        self.assertNotIn('sth', json.dumps(plan).lower())
        self.assertNotIn('codex', json.dumps(plan).lower())
        self.assertFalse((destination / '.git').exists())
        self.assertTrue((destination / 'README.md').exists())

    def test_initialize_never_overwrites_existing_directory_or_symlink(self):
        destination = self.root / 'human-config'
        destination.mkdir()
        human = destination / 'plan.json'
        human.write_text('human work')
        with self.assertRaises(SetupError):
            initialize_project(destination)
        self.assertEqual(human.read_text(), 'human work')
        link = self.root / 'link'
        link.symlink_to(destination, target_is_directory=True)
        with self.assertRaises(SetupError):
            initialize_project(link)
        self.assertEqual(human.read_text(), 'human work')

    def test_invalid_or_unavailable_template_has_no_side_effects(self):
        for template in ['unknown', 'node']:
            destination = self.root / template
            with mock.patch('project_setup.shutil.which', return_value=None):
                with self.assertRaises(SetupError):
                    initialize_project(destination, template=template)
            self.assertFalse(destination.exists())

    def test_initialization_race_does_not_remove_another_directory(self):
        destination = self.root / 'racing-config'
        original_mkdir = Path.mkdir

        def race(path, *args, **kwargs):
            if path == destination:
                original_mkdir(path, *args, **kwargs)
                raise FileExistsError('another process created this directory')
            return original_mkdir(path, *args, **kwargs)

        with mock.patch.object(Path, 'mkdir', new=race), self.assertRaises(SetupError):
            initialize_project(destination)
        self.assertTrue(destination.is_dir())

    def test_python_initialization_runs_real_tests_without_sth(self):
        repository = self.repository('python-project')
        (repository / 'test_math.py').write_text('import unittest\nclass MathTests(unittest.TestCase):\n    def test_sum(self):\n        self.assertEqual(2 + 3, 5)\n')
        self.commit(repository)
        config = self.root / 'python-config'
        initialize_project(config, template='python')
        plan, policy = self.load(config)
        report = doctor(repository, policy)
        self.assertTrue(report['ready'])
        self.assertEqual(report['sth']['status'], 'not_configured')
        result = Factory(repository, self.root / 'python-run', policy).run(plan)
        self.assertEqual(result['status'], 'succeeded')
        self.assertIsNone(result['sth'])
        self.assertIn('Ran 1 test', (self.root / 'python-run/tasks/test/runtime.stderr').read_text())

    def test_python_template_rejects_an_empty_test_suite(self):
        repository = self.repository('empty-project')
        (repository / 'README').write_text('No tests')
        self.commit(repository)
        config = self.root / 'empty-config'
        initialize_project(config)
        plan, policy = self.load(config)
        result = Factory(repository, self.root / 'empty-run', policy).run(plan)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('No tests discovered', (self.root / 'empty-run/tasks/test/runtime.stderr').read_text())

    @unittest.skipUnless(shutil.which('node'), 'Node is not installed')
    def test_node_initialization_runs_real_tests_without_sth(self):
        repository = self.repository('node-project')
        (repository / 'math.test.js').write_text("const test=require('node:test'); const assert=require('node:assert/strict'); test('sum',()=>assert.equal(2+3,5));\n")
        self.commit(repository)
        config = self.root / 'node-config'
        initialize_project(config, template='node')
        plan, policy = self.load(config)
        result = Factory(repository, self.root / 'node-run', policy).run(plan)
        self.assertEqual(result['status'], 'succeeded')
        self.assertIsNone(result['sth'])
        self.assertIn('# tests 1', (self.root / 'node-run/tasks/test/runtime.stdout').read_text())

    @unittest.skipUnless(shutil.which('node'), 'Node is not installed')
    def test_node_template_rejects_an_empty_test_suite(self):
        repository = self.repository('empty-node-project')
        (repository / 'README').write_text('No tests')
        self.commit(repository)
        config = self.root / 'empty-node-config'
        initialize_project(config, template='node')
        plan, policy = self.load(config)
        result = Factory(repository, self.root / 'empty-node-run', policy).run(plan)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('No tests discovered', (self.root / 'empty-node-run/tasks/test/runtime.stderr').read_text())

    def test_doctor_reports_missing_executables_and_unknown_auth_without_secrets(self):
        repository = self.repository('doctor-project')
        (repository / 'README').write_text('fixture')
        self.commit(repository)
        secret = 'must-never-appear-in-report'
        with mock.patch.dict(os.environ, {'OPENAI_API_KEY': secret}):
            report = doctor(repository, {'commands': {'missing': ['/missing/executable']}})
        self.assertFalse(report['ready'])
        self.assertFalse(report['commands']['missing']['available'])
        self.assertEqual(report['provider_auth']['status'], 'not_checked')
        self.assertNotIn(secret, json.dumps(report))

    def test_doctor_does_not_execute_project_commands(self):
        repository = self.repository('doctor-no-execute')
        (repository / 'README').write_text('fixture')
        self.commit(repository)
        sentinel = self.root / 'must-not-exist'
        report = doctor(repository, {'commands': {'test': [sys.executable, '-c', f'open({str(sentinel)!r},"w").write("bad")']}})
        self.assertTrue(report['ready'])
        self.assertFalse(sentinel.exists())

    def test_doctor_is_not_ready_for_nonrepository_or_missing_optional_sth_when_requested(self):
        report = doctor(self.root, {'commands': {}}, sth='/missing/sth')
        self.assertFalse(report['ready'])
        self.assertEqual(report['repository']['status'], 'not_git_repository')
        self.assertEqual(report['sth']['status'], 'missing')

    @staticmethod
    def load(config):
        return (json.loads((config / 'plan.json').read_text()),
                json.loads((config / 'operator-policy.json').read_text()))


if __name__ == '__main__':
    unittest.main()

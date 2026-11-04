import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from isolation import IsolationError, cleanup_container, prepare_execution, probe, validate_spec


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.worktree = self.root / 'worktree'
        self.worktree.mkdir()
        (self.worktree / '.git').write_text('gitdir: /host/private/mirror/worktrees/task')
        (self.worktree / 'keep.txt').write_text('original')
        self.folder = self.root / 'evidence'
        self.folder.mkdir()
        self.environment = {'HOME': str(self.folder / 'home'), 'PATH': os.defpath}
        self.spec = {'backend': 'container', 'image': 'python@sha256:' + 'a' * 64}

    def test_local_execution_explicitly_has_no_sandbox(self):
        execution = prepare_execution({'backend': 'local'}, ['/usr/bin/true'], self.worktree, self.folder, self.environment)
        self.assertFalse(execution.security_sandbox)
        self.assertEqual(execution.argv, ['/usr/bin/true'])
        self.assertEqual(execution.cwd, self.worktree)
        execution.collect()
        execution.cleanup()
        self.assertFalse(probe({'backend': 'local'})['security_sandbox'])

    def test_container_requires_fixed_image_and_rejects_weakened_boundaries(self):
        for invalid in [
            {'backend': 'unknown'}, {'backend': 'container'},
            {'backend': 'container', 'image': 'python:latest'},
            {**self.spec, 'network': 'host'}, {**self.spec, 'user': '0:0'},
            {**self.spec, 'memory_mb': -1}, {**self.spec, 'cpus': 0},
            {**self.spec, 'privileged': True}, {**self.spec, 'mounts': ['/']},
            {**self.spec, 'pids_limit': True},
        ]:
            with self.subTest(invalid=invalid), self.assertRaises(IsolationError):
                validate_spec(invalid)

    def test_container_command_is_hardened_and_only_mounts_snapshot(self):
        with mock.patch('isolation.probe', return_value={'available': True}), mock.patch('isolation.shutil.which', return_value='/usr/local/bin/docker'):
            execution = prepare_execution(self.spec, ['/usr/local/bin/python3', '-c', 'print(1)'], self.worktree, self.folder, self.environment)
        command = execution.argv
        self.assertIn('--read-only', command)
        self.assertIn('--interactive', command)
        self.assertNotIn('--tty', command)
        self.assertIn('--network=none', command)
        self.assertIn('--cap-drop=ALL', command)
        self.assertIn('--security-opt=no-new-privileges:true', command)
        self.assertIn('--pids-limit=128', command)
        self.assertIn('--pull=never', command)
        self.assertEqual(sum(arg == '--mount' for arg in command), 1)
        mount = command[command.index('--mount') + 1]
        self.assertIn(str(self.folder / 'isolated-workspace'), mount)
        self.assertNotIn(str(self.worktree), mount)
        self.assertNotIn('/host/private/mirror', ' '.join(command))
        self.assertFalse((self.folder / 'isolated-workspace/.git').exists())
        self.assertIn('--env=HTTP_PROXY=', command)
        self.assertNotIn('DOCKER_HOST', execution.env)

    def test_collection_preserves_git_pointer_and_handles_deletion_and_symlinks(self):
        outside = self.root / 'outside'
        outside.write_text('untouched')
        with mock.patch('isolation.probe', return_value={'available': True}), mock.patch('isolation.shutil.which', return_value='/usr/local/bin/docker'):
            execution = prepare_execution(self.spec, ['/bin/true'], self.worktree, self.folder, self.environment)
        snapshot = self.folder / 'isolated-workspace'
        (snapshot / 'keep.txt').unlink()
        (snapshot / '.git').mkdir()
        (snapshot / '.git/config').write_text('runtime-owned git metadata')
        (snapshot / 'new.txt').write_text('new')
        (snapshot / 'link').symlink_to(outside)
        execution.collect()
        self.assertFalse((self.worktree / 'keep.txt').exists())
        self.assertEqual((self.worktree / '.git').read_text(), 'gitdir: /host/private/mirror/worktrees/task')
        self.assertEqual((self.worktree / 'new.txt').read_text(), 'new')
        self.assertTrue((self.worktree / 'link').is_symlink())
        self.assertEqual(outside.read_text(), 'untouched')

    def test_unavailable_container_fails_closed(self):
        with mock.patch('isolation.probe', return_value={'available': False, 'reason': 'no daemon'}):
            with self.assertRaisesRegex(IsolationError, 'no daemon'):
                prepare_execution(self.spec, ['/bin/true'], self.worktree, self.folder, self.environment)
        self.assertFalse((self.folder / 'isolated-workspace').exists())

    def test_cleanup_removes_only_named_container_even_after_client_exit(self):
        with mock.patch('isolation.probe', return_value={'available': True}), mock.patch('isolation.shutil.which', return_value='/usr/local/bin/docker'):
            execution = prepare_execution(self.spec, ['/bin/true'], self.worktree, self.folder, self.environment)
        with mock.patch('isolation.subprocess.run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run:
            execution.cleanup()
        self.assertEqual(run.call_args.args[0][-3:], ['rm', '--force', execution.container_name])
        self.assertTrue(execution.container_name.startswith('sth-factory-'))

    def test_recovery_cleanup_requires_exact_owned_container_identity(self):
        name = 'sth-factory-' + 'a' * 32
        with self.assertRaises(IsolationError):
            cleanup_container(self.spec, 'unrelated-container')
        with mock.patch('isolation.shutil.which', return_value='/usr/local/bin/docker'), mock.patch('isolation.subprocess.run',
                return_value=subprocess.CompletedProcess([], 0, json.dumps({'Image': self.spec['image'], 'Labels': {}}).encode(), b'')):
            with self.assertRaisesRegex(IsolationError, 'ownership'):
                cleanup_container(self.spec, name)
        inspected = subprocess.CompletedProcess([], 0, json.dumps({'Image': self.spec['image'], 'Labels': {'io.sth.factory.container': name}}).encode(), b'')
        with mock.patch('isolation.shutil.which', return_value='/usr/local/bin/docker'), mock.patch('isolation.subprocess.run',
                side_effect=[inspected, subprocess.CompletedProcess([], 0, b'', b'')]) as run:
            self.assertTrue(cleanup_container(self.spec, name))
            self.assertEqual(run.call_args.args[0][-3:], ['rm', '--force', name])


@unittest.skipUnless(os.environ.get('STH_TEST_CONTAINER_IMAGE'), 'Set STH_TEST_CONTAINER_IMAGE to a locally available digest-pinned Python image')
class RealContainerTests(unittest.TestCase):
    def test_real_container_receives_runtime_json_on_stdin_without_tty(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree, folder = root / 'worktree', root / 'evidence'
            worktree.mkdir()
            folder.mkdir()
            request = {'protocol_version': 1, 'task': {'id': 'contract', 'prompt': 'stdin round trip'},
                       'sth': None, 'trust': 'untrusted task input'}
            script = "import json,sys; from pathlib import Path; request=json.load(sys.stdin); assert not sys.stdin.isatty(); assert request['protocol_version']==1; Path('request.json').write_text(json.dumps(request)); print(json.dumps({'received':request['task']['id']}))"
            execution = prepare_execution({'backend': 'container', 'image': os.environ['STH_TEST_CONTAINER_IMAGE']},
                                          ['/usr/local/bin/python3', '-c', script], worktree, folder, {'PATH': os.defpath})
            try:
                result = subprocess.run(execution.argv, cwd=execution.cwd, env=execution.env,
                                        input=json.dumps(request).encode(), stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(json.loads(result.stdout), {'received': 'contract'})
                execution.collect()
                self.assertEqual(json.loads((worktree / 'request.json').read_text()), request)
            finally:
                execution.cleanup()

    def test_real_nonroot_networkless_readonly_task_and_collection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree, folder = root / 'worktree', root / 'evidence'
            worktree.mkdir()
            folder.mkdir()
            (worktree / '.git').write_text('gitdir: /host/secrets')
            host_marker = root / 'host-marker'
            host_marker.write_text('secret-marker')
            spec = {'backend': 'container', 'image': os.environ['STH_TEST_CONTAINER_IMAGE']}
            script = "import json,os,socket; from pathlib import Path; assert os.getuid()!=0; assert not Path('/workspace/.git').exists(); assert not Path(%r).exists(); assert os.statvfs('/').f_flag & os.ST_RDONLY; assert len(socket.if_nameindex())==1; assert Path('/sys/fs/cgroup/pids.max').read_text().strip()=='128'; assert Path('/sys/fs/cgroup/memory.max').read_text().strip()=='536870912'; assert all(not os.environ.get(name) for name in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY')); Path('result.json').write_text(json.dumps({'uid':os.getuid(),'git_hidden':True,'root_readonly':True,'network_none':True,'pids_max':128,'memory_max':536870912}))" % str(host_marker)
            execution = prepare_execution(spec, ['/usr/local/bin/python3', '-c', script], worktree, folder, {'PATH': os.defpath})
            try:
                result = subprocess.run(execution.argv, cwd=execution.cwd, env=execution.env, input=b'', stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode())
                execution.collect()
                self.assertNotEqual(json.loads((worktree / 'result.json').read_text())['uid'], 0)
                self.assertEqual((worktree / '.git').read_text(), 'gitdir: /host/secrets')
            finally:
                execution.cleanup()

    def test_cleanup_stops_container_after_docker_client_is_killed(self):
        import time
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            worktree, folder = root / 'worktree', root / 'evidence'
            worktree.mkdir()
            folder.mkdir()
            spec = {'backend': 'container', 'image': os.environ['STH_TEST_CONTAINER_IMAGE']}
            execution = prepare_execution(spec, ['/usr/local/bin/python3', '-c',
                "from pathlib import Path; import time; Path('started').touch(); time.sleep(30)"], worktree, folder, {'PATH': os.defpath})
            process = subprocess.Popen(execution.argv, cwd=execution.cwd, env=execution.env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                marker = folder / 'isolated-workspace/started'
                while not marker.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(.02)
                self.assertTrue(marker.exists())
                process.kill()
                process.wait(timeout=3)
                self.assertTrue(cleanup_container(spec, execution.container_name))
                inspect = subprocess.run(execution.argv[:2] + ['inspect', execution.container_name],
                                         env=execution.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
                self.assertNotEqual(inspect.returncode, 0)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
                process.stdout.close()
                process.stderr.close()
                execution.cleanup()


if __name__ == '__main__':
    unittest.main()

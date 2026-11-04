import http.client
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest

from cockpit import make_server


class CockpitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run-one'
        self.run.mkdir()
        (self.run / 'summary.json').write_text(json.dumps({'status': 'succeeded', 'tasks': {}}))
        self.server = make_server(self.root, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path, *, auth=True, headers=None, method='GET'):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        request_headers = dict(headers or {})
        if auth:
            request_headers['Authorization'] = 'Bearer ' + self.server.token
        connection.request(method, path, headers=request_headers)
        response = connection.getresponse()
        output = response.read()
        result = response.status, dict(response.getheaders()), output
        connection.close()
        return result

    def test_authenticated_run_list_and_status(self):
        code, _, body = self.get('/api/runs')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['runs'][0]['name'], 'run-one')
        code, _, body = self.get('/api/status?run=run-one')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['status'], 'succeeded')
        self.assertIn('#', self.server.url)

    def test_missing_token_bad_host_origin_and_mutation_rejected(self):
        self.assertEqual(self.get('/api/runs', auth=False)[0], 401)
        self.assertEqual(self.get('/api/runs', headers={'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.get('/api/runs', headers={'Origin': 'https://attacker.example'})[0], 403)
        self.assertEqual(self.get('/api/runs', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)
        self.assertEqual(self.get('/api/runs', method='POST')[0], 405)

    def test_traversal_and_symlink_runs_rejected(self):
        for name in ['..%2Foutside', '%2Ftmp', '..']:
            self.assertEqual(self.get('/api/status?run=' + name)[0], 400)
        (self.root / 'symlink').symlink_to(self.run, target_is_directory=True)
        self.assertEqual(self.get('/api/status?run=symlink')[0], 400)

    def test_cross_site_navigation_serves_only_the_empty_shell(self):
        headers = {'Sec-Fetch-Site': 'cross-site', 'Sec-Fetch-Mode': 'navigate',
                   'Sec-Fetch-Dest': 'document'}
        code, _, body = self.get('/', auth=False, headers=headers)
        self.assertEqual(code, 200)
        self.assertNotIn(self.server.token.encode(), body)
        self.assertNotIn(b'run-one', body)
        for path in ['/api/runs', '/api/status?run=run-one', '/app.js', '/buddy.png', '/?run=run-one']:
            self.assertEqual(self.get(path, headers=headers)[0], 403)
        self.assertEqual(self.get('/', headers={**headers, 'Origin': 'https://attacker.example'})[0], 403)
        self.assertEqual(self.get('/', headers={**headers, 'Host': 'attacker.example'})[0], 403)
        self.assertEqual(self.get('/', headers={'Sec-Fetch-Site': 'cross-site'})[0], 403)

    def test_ui_uses_text_content_and_security_headers(self):
        code, headers, body = self.get('/', auth=False)
        self.assertEqual(code, 200)
        self.assertIn('frame-ancestors', headers['Content-Security-Policy'])
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertNotIn('Access-Control-Allow-Origin', headers)
        code, _, script = self.get('/app.js', auth=False)
        self.assertEqual(code, 200)
        self.assertIn(b'textContent', script)
        self.assertNotIn(b'innerHTML', script)
        self.assertNotIn(b'<script>evil()', body)

    def test_non_loopback_bind_rejected(self):
        with self.assertRaises(ValueError):
            make_server(self.root, host='0.0.0.0')

    def test_official_buddy_is_served_unchanged_as_local_image(self):
        code, headers, content = self.get('/buddy.png', auth=False)
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertEqual(hashlib.sha256(content).hexdigest(),
                         '0895815220853f29f3730b915e36e229bb49e8d2c81dad7356991cd264df114b')
        self.assertEqual(self.get('/buddy.png', auth=False, headers={'Host': 'attacker.example'})[0], 403)

import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from cockpit import make_server


class BuddyAnimationRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.server = make_server(self.temporary.name, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=3)
        connection.request('GET', path)
        response = connection.getresponse()
        output = response.read()
        value = response.status, dict(response.getheaders()), output
        connection.close()
        return value

    def test_local_player_and_reserved_frames_are_available_without_external_dependencies(self):
        self.assertEqual(self.get('/buddy-player.js')[0], 200)
        self.assertEqual(self.get('/buddy-state.js')[0], 200)
        code, headers, payload = self.get('/buddy-3d/161b1278/manifest.json')
        self.assertEqual(code, 200)
        manifest = json.loads(payload)
        self.assertEqual(manifest['source_commit'], '161b12789f1d8c74f5305f727917c5cb1fca8a13')
        self.assertEqual(manifest['fps'], 20)
        self.assertEqual({key: value['count'] for key, value in manifest['sequences'].items()},
                         {'ok': 80, 'work': 48, 'done': 38, 'error': 30})
        for sequence in ['ok', 'work', 'done', 'error']:
            code, headers, image = self.get('/buddy-3d/161b1278/' + sequence + '/0000.webp')
            self.assertEqual(code, 200)
            self.assertEqual(headers['Content-Type'], 'image/webp')
            self.assertIn('immutable', headers['Cache-Control'])
            self.assertEqual(image[:4], b'RIFF')
            self.assertEqual(image[8:12], b'WEBP')

    def test_asset_routes_are_bounded_and_do_not_expose_model_or_source_paths(self):
        for path in ['/buddy-3d/161b1278/ok/0080.webp', '/buddy-3d/161b1278/work/9999.webp',
                     '/buddy-3d/161b1278/../LICENSE', '/buddy-3d/161b1278/model.blend']:
            self.assertNotEqual(self.get(path)[0], 200)


if __name__ == '__main__':
    unittest.main()

"""Loopback-only, capability-protected, read-only factory cockpit."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urlsplit

from monitoring import InspectionError, checked_directory, review, status


def make_server(runs_root, host='127.0.0.1', port=0):
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('cockpit binds only to loopback')
    root = checked_directory(runs_root)
    token = secrets.token_urlsafe(32)
    assets = Path(__file__).with_name('web')

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, code, payload, content_type='application/json; charset=utf-8', cache='no-store'):
            if not isinstance(payload, bytes):
                payload = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', cache)
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def valid_origin(self):
            authority = {'127.0.0.1:' + str(self.server.server_port), 'localhost:' + str(self.server.server_port)}
            if self.headers.get('Host') not in authority:
                return False
            origin = self.headers.get('Origin')
            if origin is not None and origin not in {'http://' + item for item in authority}:
                return False
            if self.headers.get('Sec-Fetch-Site') != 'cross-site':
                return True
            # A linked top-level shell contains no token or run data; API checks stay strict.
            return (origin is None and self.path == '/' and
                    self.headers.get('Sec-Fetch-Mode') == 'navigate' and
                    self.headers.get('Sec-Fetch-Dest') == 'document')

        def do_GET(self):
            if not self.valid_origin():
                self.send(403, {'error': 'untrusted Host or Origin'})
                return
            parsed = urlsplit(self.path)
            if parsed.path in {'/', '/app.js', '/style.css', '/buddy.png', '/buddy-player.js', '/buddy-state.js', '/factory-view.js'}:
                name, kind = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/factory-view.js': ('factory-view.js', 'text/javascript; charset=utf-8'),
                              '/style.css': ('style.css', 'text/css; charset=utf-8'),
                              '/buddy.png': ('buddy.png', 'image/png'),
                              '/buddy-player.js': ('buddy-player.js', 'text/javascript; charset=utf-8'),
                              '/buddy-state.js': ('buddy-state.js', 'text/javascript; charset=utf-8')}[parsed.path]
                self.send(200, (assets / name).read_bytes(), kind)
                return
            if parsed.path.startswith('/buddy-3d/'):
                if parsed.path == '/buddy-3d/161b1278/manifest.json':
                    path = assets / 'buddy-3d' / '161b1278' / 'manifest.json'
                    self.send(200, path.read_bytes(), 'application/json; charset=utf-8')
                    return
                match = re.fullmatch(r'/buddy-3d/161b1278/(ok|work|done|error)/([0-9]{4})\.webp', parsed.path)
                counts = {'ok': 80, 'work': 48, 'done': 38, 'error': 30}
                if match and int(match[2]) < counts[match[1]]:
                    path = assets / 'buddy-3d' / '161b1278' / match[1] / (match[2] + '.webp')
                    self.send(200, path.read_bytes(), 'image/webp', cache='private, max-age=86400, immutable')
                    return
                self.send(404, {'error': 'Buddy asset not found'})
                return
            supplied = self.headers.get('Authorization', '')
            if not hmac.compare_digest(supplied, 'Bearer ' + token):
                self.send(401, {'error': 'capability token required'})
                return
            try:
                if parsed.path == '/api/runs':
                    runs = []
                    for path in sorted(root.iterdir()):
                        if path.is_dir() and not path.is_symlink() and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', path.name):
                            if (path / 'plan.json').exists() or (path / 'summary.json').exists() or (path / 'events.jsonl').exists():
                                try:
                                    snapshot = status(path)
                                    runs.append({'name': path.name, 'status': snapshot['status'], 'tasks': len(snapshot['tasks'])})
                                except InspectionError:
                                    runs.append({'name': path.name, 'status': 'unreadable', 'tasks': None})
                        if len(runs) >= 200:
                            break
                    self.send(200, {'runs': runs, 'limit': 200})
                    return
                if parsed.path not in {'/api/status', '/api/review'}:
                    self.send(404, {'error': 'route not found'})
                    return
                query = parse_qs(parsed.query, keep_blank_values=True)
                name = query.get('run', [''])[0]
                if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', name):
                    raise InspectionError('invalid run name')
                run = root / name
                if run.is_symlink():
                    raise InspectionError('symlink run not allowed')
                snapshot = status(run) if parsed.path == '/api/status' else review(run, query.get('task', [None])[0])
                self.send(200, snapshot)
            except (InspectionError, OSError, ValueError) as error:
                self.send(400, {'error': str(error)})

        def do_POST(self):
            self.send(405, {'error': 'cockpit is read-only'})

        do_PUT = do_POST
        do_PATCH = do_POST
        do_DELETE = do_POST

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.token = token
    server.runs_root = root
    server.url = 'http://127.0.0.1:' + str(server.server_port) + '/#' + token
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs-root', required=True)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    server = make_server(args.runs_root, port=args.port)
    print(server.url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()

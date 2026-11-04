"""Durable local run state. Retries require explicit operator action."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import threading
import time


class StateError(ValueError):
    pass


class RunLease:
    def __init__(self, root):
        self.path = Path(root) / 'run.lock'
        self.descriptor = None

    def __enter__(self):
        self.descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            os.close(self.descriptor)
            self.descriptor = None
            raise StateError('another supervisor owns this run') from error
        return self

    def __exit__(self, *_):
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


class DurableState:
    def __init__(self, root):
        self.path = Path(root) / 'state.sqlite3'
        if self.path.is_symlink():
            raise StateError('state must not be a symlink')
        self.lock = threading.Lock()
        with self.connection() as database:
            database.executescript('''
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0, result TEXT);
                CREATE TABLE IF NOT EXISTS processes (pid INTEGER PRIMARY KEY, task TEXT, identity TEXT);
                CREATE TABLE IF NOT EXISTS events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connection(self):
        with self.lock:
            database = sqlite3.connect(self.path, timeout=5)
            database.row_factory = sqlite3.Row
            database.execute('PRAGMA synchronous=FULL')
            try:
                with database:
                    yield database
            finally:
                database.close()

    def initialize(self, metadata, identifiers):
        with self.connection() as database:
            if database.execute('SELECT 1 FROM metadata WHERE key=?', ('context',)).fetchone():
                raise StateError('run state already initialized')
            database.execute('INSERT INTO metadata VALUES (?,?)', ('context', json.dumps(metadata)))
            database.executemany('INSERT INTO tasks(id,status) VALUES (?,?)', [(identifier, 'pending') for identifier in identifiers])

    def metadata(self):
        with self.connection() as database:
            row = database.execute('SELECT value FROM metadata WHERE key=?', ('context',)).fetchone()
            if not row:
                raise StateError('run state not initialized')
            return json.loads(row['value'])

    def update_metadata(self, **updates):
        with self.connection() as database:
            row = database.execute('SELECT value FROM metadata WHERE key=?', ('context',)).fetchone()
            if not row:
                raise StateError('run state not initialized')
            data = json.loads(row['value'])
            data.update(updates)
            database.execute('UPDATE metadata SET value=? WHERE key=?', (json.dumps(data), 'context'))

    def tasks(self):
        with self.connection() as database:
            return {row['id']: {'status': row['status'], 'attempts': row['attempts'],
                                'result': json.loads(row['result']) if row['result'] else None}
                    for row in database.execute('SELECT * FROM tasks')}

    def start(self, identifier, max_attempts):
        with self.connection() as database:
            row = database.execute('SELECT * FROM tasks WHERE id=?', (identifier,)).fetchone()
            if not row or row['status'] != 'pending' or row['attempts'] >= max_attempts:
                raise StateError('task is not pending or attempt budget exhausted: ' + identifier)
            database.execute('UPDATE tasks SET status=?,attempts=attempts+1,result=NULL WHERE id=?', ('running', identifier))

    def finish(self, identifier, result):
        with self.connection() as database:
            database.execute('UPDATE tasks SET status=?,result=? WHERE id=?', (result['status'], json.dumps(result), identifier))

    def recover_interrupted(self):
        with self.connection() as database:
            rows = database.execute('SELECT id FROM tasks WHERE status=?', ('running',)).fetchall()
            for row in rows:
                result = {'status': 'interrupted', 'error': 'supervisor stopped; explicit retry required'}
                database.execute('UPDATE tasks SET status=?,result=? WHERE id=?', ('interrupted', json.dumps(result), row['id']))

    def retry(self, identifier, max_attempts):
        with self.connection() as database:
            row = database.execute('SELECT * FROM tasks WHERE id=?', (identifier,)).fetchone()
            if not row or row['status'] not in ('failed', 'timed_out', 'cancelled', 'interrupted') or row['attempts'] >= max_attempts:
                raise StateError('task cannot be retried within operator budget: ' + identifier)
            database.execute('UPDATE tasks SET status=?,result=NULL WHERE id=?', ('pending', identifier))
            database.execute('UPDATE tasks SET status=?,result=NULL WHERE status=?', ('pending', 'blocked'))

    def record_process(self, pid, task=None):
        with self.connection() as database:
            database.execute('INSERT OR REPLACE INTO processes VALUES (?,?,?)', (pid, task, process_identity(pid)))

    def forget_process(self, pid):
        with self.connection() as database:
            database.execute('DELETE FROM processes WHERE pid=?', (pid,))

    def processes(self):
        with self.connection() as database:
            return [dict(row) for row in database.execute('SELECT * FROM processes')]

    def assert_no_live_processes(self):
        for process in self.processes():
            try:
                os.killpg(process['pid'], 0)
            except ProcessLookupError:
                self.forget_process(process['pid'])
                continue
            except PermissionError as error:
                raise StateError('previous process group has uncertain ownership; recovery refused') from error
            if Path('/proc').is_dir():
                live = False
                for entry in Path('/proc').iterdir():
                    if not entry.name.isdigit():
                        continue
                    try:
                        fields = (entry / 'stat').read_text().rsplit(')', 1)[1].split()
                        if int(fields[2]) == process['pid'] and fields[0] not in ('Z', 'X'):
                            live = True
                            break
                    except (FileNotFoundError, ProcessLookupError):
                        continue
                if not live:
                    self.forget_process(process['pid'])
                    continue
            raise StateError('previous process group may still be active; inspect before resume: ' + str(process['pid']))

    def event(self, payload):
        with self.connection() as database:
            database.execute('INSERT INTO events(payload) VALUES (?)', (json.dumps(payload),))

    def events(self):
        with self.connection() as database:
            return [json.loads(row['payload']) for row in database.execute('SELECT payload FROM events ORDER BY sequence')]

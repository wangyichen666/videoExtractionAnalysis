"""SQLite 持久化与加密凭据；运行密钥与数据库分开保存。"""
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from cryptography.fernet import Fernet


class Store:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        key_path = directory / 'secret.key'
        key = os.getenv('ANALYSIS_SECRET_KEY')
        if not key:
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(fd, 'wb') as f:
                    f.write(Fernet.generate_key())
            key = key_path.read_bytes()
        self.cipher = Fernet(key)
        self.path = directory / 'analysis.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL, created REAL NOT NULL)')
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=15000')
        return db

    def encrypt(self, value):
        return self.cipher.encrypt(value.encode()).decode()

    def decrypt(self, value):
        return self.cipher.decrypt(value.encode()).decode() if value else ''

    def put(self, kind, data, record_id=None):
        record_id = record_id or str(uuid.uuid4())
        with self.connect() as db:
            db.execute('INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',
                       (record_id, kind, json.dumps(data, ensure_ascii=False), time.time()))
        return record_id

    def get(self, record_id, kind=None):
        with self.connect() as db:
            row = db.execute('SELECT kind,data FROM records WHERE id=?', (record_id,)).fetchone()
        if not row or (kind and row[0] != kind):
            raise KeyError(record_id)
        return {'id': record_id, **json.loads(row[1])}

    def list(self, kind):
        with self.connect() as db:
            rows = db.execute('SELECT id,data FROM records WHERE kind=? ORDER BY created DESC', (kind,)).fetchall()
        return [{'id': row[0], **json.loads(row[1])} for row in rows]

    def delete(self, record_id, kind):
        with self.connect() as db:
            db.execute('DELETE FROM records WHERE id=? AND kind=?', (record_id, kind))

    def update(self, record_id, **fields):
        data = self.get(record_id)
        data.pop('id')
        data.update(fields)
        self.put('job', data, record_id)

    def claim(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT id,data FROM records WHERE kind='job' ORDER BY created").fetchall()
            for record_id, raw in rows:
                data = json.loads(raw)
                if data['status'] == 'queued':
                    data['status'] = 'running'
                    db.execute('UPDATE records SET data=? WHERE id=?', (json.dumps(data), record_id))
                    return {'id': record_id, **data}
        return None

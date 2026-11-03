"""Local SQLite storage with bounded event retention."""
import sqlite3
from pathlib import Path

SCHEMA = '''CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 timestamp TEXT NOT NULL,
 event TEXT NOT NULL,
 process TEXT NOT NULL,
 pid INTEGER,
 protocol TEXT,
 local_addr TEXT,
 remote_addr TEXT,
 status TEXT
)'''

class History:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(SCHEMA)
        self.db.commit()
        self.previous = set()

    def record(self, timestamp, connections):
        current = {(c['pid'], c['name'], c['protocol'], c['local'], c['remote'], c['status']) for c in connections}
        added = current - self.previous
        removed = self.previous - current
        rows = [(timestamp, action, name, pid, protocol, local, remote, status)
                for action, entries in [('OPEN', added), ('CLOSED', removed)]
                for pid, name, protocol, local, remote, status in entries]
        if rows:
            self.db.executemany('INSERT INTO events(timestamp,event,process,pid,protocol,local_addr,remote_addr,status) VALUES (?,?,?,?,?,?,?,?)', rows)
            self.db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 25000)')
            self.db.commit()
        self.previous = current
        return rows

    def recent(self, limit=400):
        return self.db.execute('SELECT timestamp,event,process,pid,protocol,local_addr,remote_addr,status FROM events ORDER BY id DESC LIMIT ?', (limit,)).fetchall()

    def close(self):
        self.db.close()

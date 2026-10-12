"""Incremental, masked 24-hour Kodi log history shared by every profile.

Only new bytes are read after the initial import of kodi.old.log and kodi.log.
SQLite commits entries and file cursors together, so a restart never loses or
duplicates committed lines. A renamed log keeps its identity; truncation starts
a new generation. Collection never calls Kodi or waits for an idle TV.
"""
from contextlib import closing
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from typing import Any, List

try:
    from .log_scan import classify_line
    from .validation import redact
except ImportError:
    from log_scan import classify_line
    from validation import redact

HISTORY_FILE = "special://masterprofile/addon_data/service.kodi.addonadmin/log-history.db"
RETENTION = 24 * 3600
READ_BYTES = 1024 * 1024
STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\.(\d+))?")


def line_time(line, fallback):
    match = STAMP.match(line)
    if match:
        try:
            return time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")) + float("0." + (match.group(2) or "0"))
        except (ValueError, OverflowError):
            pass
    return fallback


class LogHistory:
    def __init__(self, path, log_dir, clock=time.time):
        self.path, self.log_dir, self.clock = str(path), str(log_dir), clock
        self.lock = threading.Lock()

    def connect(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        db = sqlite3.connect(self.path, timeout=0.5)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, source TEXT, generation INTEGER, position INTEGER,
                at REAL, level TEXT, line TEXT, UNIQUE(source,generation,position));
            CREATE INDEX IF NOT EXISTS events_at ON events(at);
            CREATE TABLE IF NOT EXISTS cursors (
                source TEXT PRIMARY KEY, generation INTEGER, position INTEGER,
                anchor BLOB, last_time REAL, notice INTEGER, seen REAL);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
        """)
        return db

    def collect(self, skin=None, stopping=lambda: False):
        now = self.clock()
        with self.lock, closing(self.connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('started',?)", (str(now),))
            available, catching_up, read_error = False, False, False
            for name in ("kodi.old.log", "kodi.log"):
                if stopping():
                    break
                try:
                    with open(os.path.join(self.log_dir, name), "rb") as handle:
                        stat = os.fstat(handle.fileno())
                        # The first complete line identifies this log even if an inode is reused.
                        header = handle.readline()
                        source = hashlib.sha256(("%s:%s:" % (stat.st_dev, stat.st_ino)).encode() + header).hexdigest()
                        cursor = db.execute("SELECT generation,position,anchor,last_time,notice FROM cursors WHERE source=?", (source,)).fetchone()
                        generation, position, anchor, last_time, notice = cursor or (0, 0, hashlib.sha256(b"").digest(), min(now, stat.st_mtime), False)
                        handle.seek(max(0, position - 64))
                        if position > stat.st_size or hashlib.sha256(handle.read(min(position, 64))).digest() != anchor:
                            generation, position, last_time, notice = generation + 1, 0, min(now, stat.st_mtime), False
                        handle.seek(position)
                        records = []
                        while handle.tell() - position < READ_BYTES and not stopping():
                            start = handle.tell()
                            raw = handle.readline()
                            if not raw:
                                break
                            # A live log may currently end midway through a write.
                            if name == "kodi.log" and not raw.endswith(b"\n"):
                                handle.seek(start)
                                break
                            records.append((start, raw.decode("utf-8", "replace").rstrip("\r\n")))
                        end = handle.tell()
                        following = [handle.readline().decode("utf-8", "replace").rstrip("\r\n") for _ in range(5)]
                        lines = [r[1] for r in records] + following
                        for i, (start, line) in enumerate(records):
                            last_time = line_time(line, last_time)
                            kind, notice = classify_line(line, lines[i + 1:i + 6], skin, notice)
                            at = min(now, last_time)
                            if kind and at >= now - RETENTION:
                                db.execute("INSERT OR IGNORE INTO events(source,generation,position,at,level,line) VALUES (?,?,?,?,?,?)",
                                           (source, generation, start, at, kind, redact(line)))
                        handle.seek(max(0, end - 64))
                        anchor = hashlib.sha256(handle.read(min(end, 64))).digest()
                        db.execute("INSERT OR REPLACE INTO cursors VALUES (?,?,?,?,?,?,?)",
                                   (source, generation, end, anchor, last_time, int(notice), now))
                        if name == "kodi.log":
                            available = True
                        catching_up = catching_up or end < stat.st_size
                except FileNotFoundError:
                    pass
                except OSError:
                    read_error = True
            db.execute("DELETE FROM events WHERE at < ?", (now - RETENTION,))
            db.execute("DELETE FROM cursors WHERE seen < ?", (now - RETENTION,))
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('scan',?)",
                       (json.dumps({"available": available and not read_error, "catching_up": catching_up, "last_scan_at": now}),))

    def snapshot(self, level="all", limit=100, before=0):
        if level not in ("all", "error", "warning", "notice"):
            raise ValueError("level must be all, error, warning or notice")
        try:
            limit, before = int(limit), int(before)
        except (ValueError, TypeError):
            raise ValueError("limit and before must be integers") from None
        if not 1 <= limit <= 500 or not 0 <= before < 2 ** 63:
            raise ValueError("limit must be 1–500 and before must be a nonnegative 64-bit integer")
        now = self.clock()
        with self.lock, closing(self.connect()) as db:
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            counts = dict(db.execute("SELECT level,count(*) FROM events WHERE at >= ? GROUP BY level", (now - RETENTION,)))
            where = "at >= ?"
            args: List[Any] = [now - RETENTION]
            if level != "all":
                where += " AND level=?"
                args.append(level)
            total = db.execute("SELECT count(*) FROM events WHERE " + where, args).fetchone()[0]
            if before:
                where += " AND id<?"
                args.append(before)
            rows = db.execute("SELECT id,at,level,line FROM events WHERE " + where + " ORDER BY id DESC LIMIT ?", args + [limit + 1]).fetchall()
        status = json.loads(metadata.get("scan", "{}"))
        if now - status.get("last_scan_at", 0) > 30:
            status["available"] = False
        # Apply current rules to entries collected by an older version, too.
        entries = [{"id": r[0], "timestamp": r[1], "level": r[2], "line": redact(r[3])} for r in rows[:limit]]
        return dict(status, retention_hours=24, since=now - RETENTION, now=now,
                    tracking_started_at=float(metadata["started"]) if "started" in metadata else None,
                    available=status.get("available", False), catching_up=status.get("catching_up", True),
                    counts={"errors": counts.get("error", 0), "warnings": counts.get("warning", 0),
                            "notices": counts.get("notice", 0), "warning_lines": counts.get("warning", 0) + counts.get("notice", 0)},
                    entries=entries, total=total, has_more=len(rows) > limit,
                    next_before=entries[-1]["id"] if len(rows) > limit else None)

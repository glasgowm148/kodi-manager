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
from typing import Any, Dict, List, Optional

try:
    from .log_scan import classify_line
    from .validation import redact
    from .log_issues import describe_issue
except ImportError:
    from log_scan import classify_line
    from validation import redact
    from log_issues import describe_issue

HISTORY_FILE = "special://masterprofile/addon_data/service.kodi.addonadmin/log-history.db"
RETENTION = 24 * 3600
READ_BYTES = 1024 * 1024
# The collector runs every 2 s. When no log file changed it does not write at all,
# except the scan status every METADATA_EVERY s; expired entries are removed and space
# reclaimed every MAINTAIN_EVERY s. (Writing every 2 s cost ~2 GB of flash writes a day.)
METADATA_EVERY = 20
MAINTAIN_EVERY = 60
# At most this many entries are kept (the oldest go first): an error burst cannot grow
# the database without bound inside the 24-hour window.
MAX_EVENTS = 50000
# A database created before space was reclaimed (auto_vacuum off) is compacted once,
# when more than half of it is free and what is left is at most this size.
COMPACT_MAX_BYTES = 32 * 1024 * 1024
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
    def __init__(self, path, log_dir, clock=time.time, version=None):
        self.path, self.log_dir, self.clock = str(path), str(log_dir), clock
        self.lock = threading.Lock()
        self.version, self._version_recorded = version, False
        # This process's view of the log files and of the last scan (see collect).
        self._stats = None
        self._scan: Optional[Dict[str, Any]] = None
        self._metadata_at = self._maintained_at = float("-inf")

    def connect(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        db = sqlite3.connect(self.path, timeout=0.5)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        if not db.execute("PRAGMA page_count").fetchone()[0]:
            # A new database returns freed pages to the filesystem (see _maintain). Older
            # versions read and write such a database as before.
            db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, source TEXT, generation INTEGER, position INTEGER,
                at REAL, level TEXT, line TEXT, UNIQUE(source,generation,position));
            CREATE INDEX IF NOT EXISTS events_at ON events(at);
            CREATE TABLE IF NOT EXISTS cursors (
                source TEXT PRIMARY KEY, generation INTEGER, position INTEGER,
                anchor BLOB, last_time REAL, notice INTEGER, seen REAL);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS issue_definitions (id TEXT PRIMARY KEY, detail TEXT);
            CREATE TABLE IF NOT EXISTS issue_members (event_id INTEGER PRIMARY KEY, issue_id TEXT,
                source TEXT, generation INTEGER, position INTEGER);
            CREATE INDEX IF NOT EXISTS issue_members_issue ON issue_members(issue_id);
            CREATE TABLE IF NOT EXISTS issue_reviews (issue_id TEXT PRIMARY KEY, at REAL, last_id INTEGER);
        """)
        return db

    @staticmethod
    def index_missing(db):
        # Bounded migration preserves the original entries, IDs, cursors and retention.
        # Older collectors can reuse row IDs after all entries expire. Bind membership to
        # the original file cursor identity so rollback/reuse cannot assign the wrong cause.
        db.execute('DELETE FROM issue_members WHERE NOT EXISTS (SELECT 1 FROM events e WHERE e.id=event_id '
                   'AND e.source IS issue_members.source AND e.generation IS issue_members.generation '
                   'AND e.position IS issue_members.position)')
        rows = db.execute("SELECT e.id,e.line,e.source,e.generation,e.position FROM events e LEFT JOIN issue_members m ON m.event_id=e.id "
                          "WHERE m.event_id IS NULL ORDER BY e.id LIMIT 500").fetchall()
        for event_id, line, source, generation, position in rows:
            key, detail = describe_issue(line)
            db.execute("INSERT OR IGNORE INTO issue_definitions VALUES (?,?)", (key, json.dumps(detail)))
            db.execute("INSERT OR IGNORE INTO issue_members VALUES (?,?,?,?,?)", (event_id, key, source, generation, position))

    def record_review(self, issue):
        if not re.fullmatch(r'[0-9a-f]{32}', str(issue)):
            raise ValueError('Invalid issue ID')
        now = self.clock()
        with self.lock, closing(self.connect()) as db, db:
            self.index_missing(db)
            found = db.execute("SELECT 1 FROM issue_members m JOIN events e ON e.id=m.event_id "
                               "WHERE m.issue_id=? AND e.at>=? LIMIT 1", (issue, now - RETENTION)).fetchone()
            if not found:
                raise ValueError('Issue is no longer in the retained history')
            last_id = db.execute('SELECT COALESCE(max(id),0) FROM events').fetchone()[0]
            db.execute('INSERT OR REPLACE INTO issue_reviews VALUES (?,?,?)', (issue, now, last_id))
        return {'issue': issue, 'reviewed_at': now}

    def _log_stats(self):
        stats = []
        for name in ("kodi.old.log", "kodi.log"):
            try:
                st = os.stat(os.path.join(self.log_dir, name))
                stats.append((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns))
            except FileNotFoundError:
                stats.append(None)
            except OSError:
                return None  # unknown: scan
        return tuple(stats)

    def collect(self, skin=None, stopping=lambda: False):
        now = self.clock()
        stats = self._log_stats()

        def due(last, every):
            return not last <= now < last + every  # also when the clock went back

        maintain = due(self._maintained_at, MAINTAIN_EVERY)
        last = self._scan
        unchanged = (stats is not None and stats == self._stats and last is not None
                     and not last["catching_up"] and self._version_recorded)
        if unchanged and last is not None and not maintain:
            # Nothing new to read: no transaction (no flash write), except the scan status
            # now and then for snapshots served by another process.
            self._scan = dict(last, last_scan_at=now)
            if due(self._metadata_at, METADATA_EVERY):
                with self.lock, closing(self.connect()) as db, db:
                    db.execute("INSERT OR REPLACE INTO metadata VALUES ('scan',?)", (json.dumps(self._scan),))
                self._metadata_at = now
            return
        with self.lock:
            self._collect(now, skin, stopping, maintain)
            if not stopping():
                self._stats = stats
            if maintain:
                self._maintained_at = now
                self._compact_once()

    def _collect(self, now, skin, stopping, maintain):
        with closing(self.connect()) as db, db:
            db.execute("INSERT OR IGNORE INTO metadata VALUES ('started',?)", (str(now),))
            if self.version and not self._version_recorded:
                old = db.execute("SELECT value FROM metadata WHERE key='recording_version'").fetchone()
                if not old or json.loads(old[0]).get('version') != self.version:
                    db.execute("INSERT OR REPLACE INTO metadata VALUES ('recording_version',?)",
                               (json.dumps({'version': self.version, 'at': now,
                                            'last_id': db.execute('SELECT COALESCE(max(id),0) FROM events').fetchone()[0]}),))
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
                        cursor = db.execute("SELECT generation,position,anchor,last_time,notice,seen FROM cursors WHERE source=?", (source,)).fetchone()
                        generation, position, anchor, last_time, notice, seen = cursor or (0, 0, hashlib.sha256(b"").digest(), min(now, stat.st_mtime), False, None)
                        stored = cursor[:5] if cursor else None
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
                        # An unchanged cursor is rewritten only now and then (``seen`` keeps it
                        # from expiring): rewriting it every scan was a flash write each time.
                        if (stored != (generation, end, anchor, last_time, int(notice))
                                or not isinstance(seen, (int, float)) or not seen <= now < seen + 3600):
                            db.execute("INSERT OR REPLACE INTO cursors VALUES (?,?,?,?,?,?,?)",
                                       (source, generation, end, anchor, last_time, int(notice), now))
                        if name == "kodi.log":
                            available = True
                        catching_up = catching_up or end < stat.st_size
                except FileNotFoundError:
                    pass
                except OSError:
                    read_error = True
            if maintain:
                self._maintain(db, now)
            self.index_missing(db)
            scan = {"available": available and not read_error, "catching_up": catching_up, "last_scan_at": now}
            changed = self._scan is None or any(scan[k] != self._scan.get(k) for k in ("available", "catching_up"))
            if changed or maintain or not self._metadata_at <= now < self._metadata_at + METADATA_EVERY:
                db.execute("INSERT OR REPLACE INTO metadata VALUES ('scan',?)", (json.dumps(scan),))
                self._metadata_at = now
            self._scan = scan
        self._version_recorded = True

    @staticmethod
    def _maintain(db, now):
        """Remove expired entries (and the oldest beyond MAX_EVENTS), their issue links and
        stale cursors, then return freed pages to the filesystem."""
        db.execute("DELETE FROM events WHERE at < ?", (now - RETENTION,))
        cutoff = db.execute("SELECT id FROM events ORDER BY id DESC LIMIT 1 OFFSET ?", (MAX_EVENTS,)).fetchone()
        if cutoff:
            db.execute("DELETE FROM events WHERE id <= ?", (cutoff[0],))
        db.execute("DELETE FROM issue_members WHERE event_id NOT IN (SELECT id FROM events)")
        db.execute("DELETE FROM issue_definitions WHERE id NOT IN (SELECT issue_id FROM issue_members)")
        db.execute("DELETE FROM cursors WHERE seen < ?", (now - RETENTION,))
        if db.execute("PRAGMA auto_vacuum").fetchone()[0] == 2 and db.execute("PRAGMA freelist_count").fetchone()[0]:
            db.execute("PRAGMA incremental_vacuum").fetchall()

    def _compact_once(self):
        """Compact a database created without auto_vacuum (by an older version) once most
        of it is free, switching it to incremental vacuum so it never needs this again.
        Bounded by COMPACT_MAX_BYTES of live data, so it stays short."""
        try:
            with closing(sqlite3.connect(self.path, timeout=0.5, isolation_level=None)) as db:
                mode = db.execute("PRAGMA auto_vacuum").fetchone()[0]
                pages, free = (db.execute("PRAGMA %s" % name).fetchone()[0] for name in ("page_count", "freelist_count"))
                size = db.execute("PRAGMA page_size").fetchone()[0]
                if mode == 0 and free * 2 > pages and pages > 256 and (pages - free) * size <= COMPACT_MAX_BYTES:
                    db.execute("PRAGMA auto_vacuum=INCREMENTAL")
                    db.execute("VACUUM")
        except sqlite3.Error:
            pass  # busy or short of space: try again at the next maintenance

    def snapshot(self, level="all", limit=100, before=0, issue="", group_offset=0):
        if level not in ("all", "error", "warning", "notice"):
            raise ValueError("level must be all, error, warning or notice")
        try:
            limit, before, group_offset = int(limit), int(before), int(group_offset)
        except (ValueError, TypeError):
            raise ValueError("limit and before must be integers") from None
        if not 1 <= limit <= 500 or not 0 <= before < 2 ** 63 or not 0 <= group_offset <= 1_000_000:
            raise ValueError("limit must be 1–500 and before must be a nonnegative 64-bit integer")
        if issue and not re.fullmatch(r'[0-9a-f]{32}', str(issue)):
            raise ValueError('Invalid issue ID')
        now = self.clock()
        with self.lock, closing(self.connect()) as db, db:
            self.index_missing(db)
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            marker = json.loads(metadata['recording_version']) if 'recording_version' in metadata else None
            counts = dict(db.execute("SELECT level,count(*) FROM events WHERE at >= ? GROUP BY level", (now - RETENTION,)))
            update_counts = None
            if marker:
                recent = dict(db.execute("SELECT level,count(*) FROM events WHERE at >= ? AND "
                                         "(at > ? OR (at = ? AND id > ?)) GROUP BY level",
                                         (now - RETENTION, marker['at'], marker['at'], marker.get('last_id', 0))))
                update_counts = {key: recent.get(level, 0) for key, level in
                                 (('errors', 'error'), ('warnings', 'warning'), ('notices', 'notice'))}
            last_problem = db.execute("SELECT max(at) FROM events WHERE at >= ? AND level IN ('error','warning')",
                                      (now - RETENTION,)).fetchone()[0]
            where = "at >= ?"
            args: List[Any] = [now - RETENTION]
            if level != "all":
                where += " AND level=?"
                args.append(level)
            if issue:
                where += " AND id IN (SELECT event_id FROM issue_members WHERE issue_id=?)"
                args.append(issue)
            total = db.execute("SELECT count(*) FROM events WHERE " + where, args).fetchone()[0]
            group_where = where.replace('at >=', 'e.at >=').replace('level=', 'e.level=').replace(' AND id IN', ' AND e.id IN')
            joins = ' FROM events e JOIN issue_members m ON m.event_id=e.id JOIN issue_definitions d ON d.id=m.issue_id LEFT JOIN issue_reviews r ON r.issue_id=m.issue_id '
            group_total = db.execute('SELECT count(DISTINCT m.issue_id)' + joins + 'WHERE ' + group_where, args).fetchone()[0]
            baseline = marker['at'] if marker else None
            baseline_id = marker.get('last_id', 0) if marker else 0
            groups = db.execute('SELECT m.issue_id,d.detail,count(*),min(e.at),max(e.at),max(e.id),r.at,'
                                "sum(e.level='error'),sum(e.level='warning'),sum(e.level='notice'),"
                                'sum(CASE WHEN COALESCE(r.at,?) IS NULL THEN NULL WHEN e.at>COALESCE(r.at,?) OR '
                                '(e.at=COALESCE(r.at,?) AND e.id>COALESCE(r.last_id,?)) THEN 1 ELSE 0 END)'
                                + joins + "WHERE " + group_where + " GROUP BY m.issue_id ORDER BY sum(e.level='error')>0 DESC,sum(e.level='warning')>0 DESC,max(e.at) DESC,m.issue_id LIMIT 25 OFFSET ?",
                                [baseline, baseline, baseline, baseline_id] + args + [group_offset]).fetchall()
            issues_ready = not db.execute('SELECT 1 FROM events e LEFT JOIN issue_members m ON m.event_id=e.id WHERE e.at>=? AND m.event_id IS NULL LIMIT 1', (now - RETENTION,)).fetchone()
            issues = []
            for key, detail, count, first, last, latest, review, errors, warnings, notices, new_count in groups:
                sample = db.execute('SELECT line FROM events WHERE id=?', (latest,)).fetchone()[0]
                issues.append(dict(json.loads(detail), id=key, count=count, first_seen=first, last_seen=last,
                                   level='error' if errors else 'warning' if warnings else 'notice',
                                   counts={'errors': errors, 'warnings': warnings, 'notices': notices},
                                   sample=redact(sample), reviewed_at=review, baseline_at=review or baseline,
                                   since_baseline=new_count))
            if before:
                where += " AND id<?"
                args.append(before)
            rows = db.execute("SELECT id,at,level,line FROM events WHERE " + where + " ORDER BY id DESC LIMIT ?", args + [limit + 1]).fetchall()
        # This process's collector knows the latest scan; the database copy is written
        # less often (METADATA_EVERY).
        status = dict(self._scan) if self._scan is not None else json.loads(metadata.get("scan", "{}"))
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
                    next_before=entries[-1]["id"] if len(rows) > limit else None,
                    issues=issues, issue_total=group_total, issues_ready=issues_ready,
                    group_offset=group_offset, groups_has_more=group_offset + len(issues) < group_total,
                    recording_version=marker, since_update_counts=update_counts, last_problem_at=last_problem,
                    selected_issue=issue or None)

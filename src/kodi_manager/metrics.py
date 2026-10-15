"""A small, bounded history of the TV's health for the dashboard's charts.

The service samples from its existing watchdog loop, only while the TV is
idle and at most once per ``RESOLUTION`` seconds. Nothing extra runs during
playback: a film simply shows as a gap. Each sample holds memory figures, the
newest internet probe (only when a new probe ran since the previous sample;
the sampler never probes by itself) and cached-row counts.

The history lives in the Kodi profile's addon_data, so each profile keeps its
own. It is written atomically, kept for ``RETENTION`` seconds and capped at
``MAX_SAMPLES`` samples and ``MAX_BYTES`` bytes; a damaged file starts a
fresh history instead of failing.
"""
import json
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Union

try:
    from .fsutil import atomic_write_json, path_lock
except ImportError:
    from fsutil import atomic_write_json, path_lock

RESOLUTION = 15 * 60
RETENTION = 7 * 86400
MAX_SAMPLES = 800
MAX_BYTES = 256 * 1024
HISTORY_FILE = "special://profile/addon_data/service.kodi.addonadmin/metrics_history.json"
VERSION = 1

# Short keys keep the file small: about 120 bytes a sample.
_NUMBER_KEYS = {"ma": "memory_available_mb", "mt": "memory_total_mb", "mk": "kodi_mb", "sw": "swap_used_pct",
                "rc": "rows_cached", "rf": "rows_failing", "rp": "rows_persistent", "kp": "kodi_started_at"}
_STATUSES = ("ok", "warning", "error")
_HOST_LIMIT = 6
_lock = threading.Lock()


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return int(value) if float(value).is_integer() else round(float(value), 3)


def clean_sample(sample) -> Optional[Dict[str, Any]]:
    """A validated copy of a stored sample, or None. Files are untrusted input."""
    if not isinstance(sample, dict):
        return None
    t = _number(sample.get("t"))
    if t is None or t <= 0:
        return None
    out: Dict[str, Any] = {"t": int(t)}
    for key in _NUMBER_KEYS:
        value = _number(sample.get(key))
        if value is not None and value >= 0:
            out[key] = value
    if sample.get("ns") in _STATUSES:
        out["ns"] = sample["ns"]
        hosts = sample.get("nh")
        if isinstance(hosts, dict):
            kept = {}
            for name, ms in list(hosts.items())[:_HOST_LIMIT]:
                if isinstance(name, str) and 0 < len(name) <= 40:
                    value = _number(ms)
                    kept[name] = int(value) if value is not None and value >= 0 else None
            out["nh"] = kept
        checked = _number(sample.get("nt"))
        if checked is not None and checked > 0:
            out["nt"] = int(checked)
    return out


_FETCHED = re.compile(rb'"fetched_at":\s*([0-9.]+)')
_SOURCE = re.compile(rb'"source":\s*("(?:[^"\\]|\\.)*")')
# An empty listing at the end, optionally followed by numeric fields (touch() wrote
# ``used_at`` after ``files`` in 0.7.36).
_EMPTY = re.compile(rb'"files":\s*\[\s*\]\s*(?:,\s*"[a-z_]+":\s*[0-9.eE+-]+\s*)*}\s*$')


def _entry_glance(path):
    """(source, fetched_at, empty) from the start and end of a cached listing, without parsing it all."""
    with open(path, "rb") as handle:
        head = handle.read(16384)
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(max(0, size - 64))
        tail = handle.read()
    source, fetched = _SOURCE.search(head), _FETCHED.search(head)
    return (json.loads(source.group(1).decode("utf-8")) if source else None,
            float(fetched.group(1)) if fetched else None, bool(_EMPTY.search(tail)))


def widget_row_counts(cache_root, ttl=None, now=None):
    """Cached rows, rows whose last refresh failed, rows failing three times or more and,
    when ``ttl(source)`` is given, rows due a refresh (stale) and rows that are empty.

    Reads the small per-row health records and only the first and last bytes of each
    cached listing, never a whole listing.
    """
    entries, health = os.path.join(cache_root, "entries"), os.path.join(cache_root, "health")
    try:
        cached = {name for name in os.listdir(entries) if name.endswith(".json")}
    except OSError:
        return dict({"cached": 0, "failing": 0, "persistent": 0}, **({"stale": 0, "empty": 0} if ttl else {}))
    failing = persistent = 0
    try:
        names = [name for name in os.listdir(health) if name in cached]
    except OSError:
        names = []
    for name in names:
        try:
            with open(os.path.join(health, name), encoding="utf-8") as handle:
                record = json.load(handle)
            count = int(record.get("failures", 0)) if isinstance(record, dict) else 0
        except (OSError, ValueError, TypeError):
            continue
        if count >= 1:
            failing += 1
        if count >= 3:
            persistent += 1
    counts = {"cached": len(cached), "failing": failing, "persistent": persistent}
    if ttl:
        now = time.time() if now is None else now
        stale = empty = 0
        for name in cached:
            try:
                source, fetched, is_empty = _entry_glance(os.path.join(entries, name))
                if source and fetched is not None and now - fetched > ttl(source):
                    stale += 1
                empty += is_empty
            except (OSError, ValueError, UnicodeError):
                continue
        counts.update(stale=stale, empty=empty)
    return counts


def process_started_at(proc="/proc", pid="self"):
    """When this (Kodi) process started, as a Unix time; None where /proc can't say."""
    try:
        with open(os.path.join(proc, str(pid), "stat"), encoding="utf-8") as handle:
            ticks = int(handle.read().rsplit(") ", 1)[1].split()[19])
        with open(os.path.join(proc, "stat"), encoding="utf-8") as handle:
            boot = next(int(line.split()[1]) for line in handle if line.startswith("btime "))
        hertz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        return int(boot + ticks / float(hertz or 100))
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def build_sample(now, memory=None, internet=None, rows=None, last_probe=None, started=None):
    """One sample from figures the service already has. ``internet`` is netwatch's newest result."""
    sample: Dict[str, Any] = {"t": int(now)}
    memory = memory or {}
    if memory.get("status") not in (None, "unknown"):
        for key, name in (("ma", "available_mb"), ("mt", "total_mb"), ("mk", "kodi_mb"), ("sw", "swap_used_pct")):
            if _number(memory.get(name)) is not None:
                sample[key] = memory[name]
    if internet and internet.get("status") in _STATUSES and internet.get("checked_at") != last_probe:
        sample["ns"] = internet["status"]
        sample["nt"] = int(internet.get("checked_at") or now)
        sample["nh"] = {str(h.get("name"))[:40]: (None if h.get("seconds") is None else int(round(float(h["seconds"]) * 1000)))
                        for h in (internet.get("hosts") or [])[:_HOST_LIMIT] if isinstance(h, dict) and h.get("name")}
    if rows:
        sample["rc"], sample["rf"], sample["rp"] = rows.get("cached", 0), rows.get("failing", 0), rows.get("persistent", 0)
    if started:
        sample["kp"] = int(started)
    return clean_sample(sample)


class MetricsHistory:
    def __init__(self, path, retention=RETENTION, resolution=RESOLUTION, max_samples=MAX_SAMPLES,
                 max_bytes=MAX_BYTES, clock=time.time):
        self.path, self.retention, self.resolution = path, retention, resolution
        self.max_samples, self.max_bytes, self.clock = max_samples, max_bytes, clock
        self._behind_since = None  # time.monotonic() when this clock was first seen behind the history

    # How long this clock may stay behind most of the stored history (see record) before
    # that history is taken to be the wrong one (stamped by a clock that ran ahead).
    BEHIND_GRACE = 6 * 3600

    def load(self) -> List[Dict[str, Any]]:
        """Stored samples, oldest first. A missing or damaged file is an empty history."""
        try:
            # _bounded() caps the samples; the file adds a small wrapper around them.
            if os.path.getsize(self.path) > self.max_bytes + 4096:
                return []
            with open(self.path, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        raw = data.get("samples") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            return []
        samples = [s for s in (clean_sample(item) for item in raw[-self.max_samples * 2:]) if s]
        samples.sort(key=lambda s: s["t"])
        return samples

    def _bounded(self, samples, now):
        oldest = now - self.retention
        samples = [s for s in samples if oldest <= s["t"] <= now + 300][-self.max_samples:]
        while samples and len(json.dumps(samples, separators=(",", ":"))) > self.max_bytes:
            samples = samples[max(1, len(samples) // 10):]
        return samples

    def record(self, sample, now=None):
        """Append ``sample`` unless one was stored within the resolution. Returns True when stored."""
        now = self.clock() if now is None else now
        sample = clean_sample(sample)
        if not sample:
            return False
        with _lock, path_lock(self.path):
            stored = self.load()
            samples = [s for s in stored if s["t"] <= now + 300]
            ahead = len(stored) - len(samples)
            if ahead > 1 and ahead > len(samples):
                # Most of the history is later than now: this clock is probably behind (the
                # TV just started and has not set its clock yet). Skip this sample rather
                # than erase the history, unless the clock has stayed behind for hours.
                if self._behind_since is None:
                    self._behind_since = time.monotonic()
                if time.monotonic() - self._behind_since < self.BEHIND_GRACE:
                    return False
            else:
                self._behind_since = None
            # Otherwise samples stamped later than now (the clock was ahead, then corrected) are dropped.
            if samples and sample["t"] - samples[-1]["t"] < self.resolution * 0.9:
                return False
            samples = self._bounded(samples + [sample], now)
            atomic_write_json(self.path, {"version": VERSION, "resolution": self.resolution, "samples": samples},
                              fsync=False, separators=(",", ":"))
        return True

    def last_probe(self):
        for sample in reversed(self.load()):
            if "nt" in sample:
                return sample["nt"]
        return None

    def series(self, days: Union[int, str] = 7, now=None):
        """Columns for the dashboard: aligned arrays, ``None`` where a figure is missing."""
        now = self.clock() if now is None else now
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise ValueError("days must be a whole number from 1 to 7") from None
        if not 1 <= days <= 7:
            raise ValueError("days must be a whole number from 1 to 7")
        since = now - days * 86400
        samples = [s for s in self.load() if since <= s["t"] <= now + 300]
        hosts = []
        for sample in samples:
            for name in sample.get("nh", {}):
                if name not in hosts and len(hosts) < _HOST_LIMIT:
                    hosts.append(name)
        out = {"t": [s["t"] for s in samples]}
        for key, name in _NUMBER_KEYS.items():
            out[name] = [s.get(key) for s in samples]
        out["network_status"] = [s.get("ns") for s in samples]
        latency = {name: [s["nh"].get(name) if "nh" in s else None for s in samples] for name in hosts}
        # Every Kodi start inside the window (restart, crash, Android closing it) is a marker.
        starts = sorted({s["kp"] for s in samples if "kp" in s and since <= s["kp"] <= now})
        return {"resolution_seconds": self.resolution, "retention_days": int(self.retention // 86400),
                "days": days, "now": int(now), "count": len(samples), "series": out,
                "latency_ms": latency, "hosts": hosts, "kodi_starts": starts}


class Sampler:
    """Called from the watchdog loop: one sample per ``RESOLUTION`` while the TV is quiet."""

    def __init__(self, history, memory, internet, rows, clock=time.time, first_after=60, started=process_started_at):
        self.history, self.memory, self.internet, self.rows, self.clock = history, memory, internet, rows, clock
        self.started = started
        self.next_at = clock() + first_after
        self.last_probe = None
        self.loaded = False

    def tick(self, quiet):
        now = self.clock()
        if not quiet or now < self.next_at:
            return False
        self.next_at = now + self.history.resolution
        if not self.loaded:
            self.loaded = True
            self.last_probe = self.history.last_probe()
        internet = self.internet()
        sample = build_sample(now, memory=self.memory(), internet=internet, rows=self.rows(), last_probe=self.last_probe,
                              started=self.started() if self.started else None)
        stored = self.history.record(sample, now)
        if stored and sample and "nt" in sample:
            self.last_probe = sample["nt"]
        return stored

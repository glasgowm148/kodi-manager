"""Background refresh of cached widget rows (service side; see widget_cache.py).

Kept apart from widget_cache.py, which every widget invocation loads: only the service needs this.
"""
import threading
import time

try:
    from . import widget_cache as _cache
except ImportError:
    import widget_cache as _cache


class Refresher:
    """Background, one-at-a-time refresh of queued widget rows (service side).

    Refreshing runs the source add-on (often POV) once per row, so it only
    happens while the TV is quiet: nothing playing, no busy or progress dialog
    (POV searching for sources) and no remote presses for a while. A failed or
    very short playback does not trigger a full refresh, and full refreshes
    are rate-limited.

    While nobody is watching (``is_unattended``: screensaver, display off or
    no input for an hour) nothing is fetched: each fetch runs the source
    add-on, and doing that all night grows Kodi's memory for rows nobody
    sees. The first tick after someone returns sweeps stale rows at once.
    """

    EVERYTHING_EVERY = 30 * 60   # at most one full refresh per 30 minutes
    SHORT_PLAYBACK = 120         # seconds; shorter plays are treated as failed starts
    MAX_ROWS_PER_TICK = 2
    WORK_BUDGET = 10
    BATCH_PAUSE = 10
    ROW_PAUSE = 1.5              # seconds between rows so Kodi stays responsive
    stop: threading.Event        # set by the service (service_workers.start_widget_refresher)

    def __init__(self, cache, jsonrpc, is_playing, bump, log=lambda msg: None, clock=time.time,
                 external_reload=lambda: "", is_busy=lambda: False, sleep=None,
                 is_unattended=lambda: False):
        self.cache, self.jsonrpc, self.is_playing, self.bump, self.log, self.clock = cache, jsonrpc, is_playing, bump, log, clock
        self.is_busy = is_busy
        self.is_unattended = is_unattended
        self.unattended = False
        self.sleep = sleep or (lambda seconds: None)
        self.next_work = clock()
        self.next_sweep = clock() + 20
        self.after_playback = []
        self.playback_started_at = None
        self.last_everything = float("-inf")
        # Add-ons such as TMDb Helper bump their own reload property after a
        # Trakt sync; follow it so personal rows refresh at the same time.
        self.external_reload = external_reload
        self.last_external = None

    def playback_started(self):
        self.playback_started_at = self.clock()

    def playback_stopped(self):
        now = self.clock()
        started, self.playback_started_at = self.playback_started_at, None
        if started is not None and now - started < self.SHORT_PLAYBACK:
            # A failed start or a quick back-out: watched state barely changed.
            # Keep a full refresh still pending from an earlier, real playback.
            self.after_playback = [(now + 5, "progress")] + [job for job in self.after_playback if job[1] == "everything"]
            return
        # Progress rows first (POV updates its local state on stop), then
        # again plus everything else once Trakt has had time to sync.
        self.after_playback = [(now + 5, "progress"), (now + 120, "everything")]

    def _quiet(self):
        try:
            return not self.is_playing() and not self.is_busy()
        except Exception:
            return False

    def _away(self):
        try:
            return bool(self.is_unattended())
        except Exception:
            return False

    def tick(self, should_stop=lambda: False):
        if should_stop():
            return 0
        now = self.clock()
        if self._away():
            self.unattended = True
            return 0
        if self.unattended:
            self.unattended = False
            self.next_sweep = min(self.next_sweep, now)  # catch up on rows that went stale
        if not self._quiet() or now < self.next_work:
            return 0
        token = self.external_reload()
        if token != self.last_external:
            if self.last_external is not None:
                self.cache.queue_stale(now, progress_only=True)
            self.last_external = token
        due = [kind for at, kind in self.after_playback if at <= now]
        self.after_playback = [(at, kind) for at, kind in self.after_playback if at > now]
        for kind in due:
            if kind == "everything":
                if now - self.last_everything < self.EVERYTHING_EVERY:
                    kind = "stale"
                else:
                    self.last_everything = now
            self.cache.queue_stale(now, progress_only=kind == "progress", everything=kind == "everything")
        if now >= self.next_sweep:
            self.next_sweep = now + 300
            self.cache.queue_stale(now)
            self.cache.prune(now)
        changed = done = attempted = 0
        started = self.clock()
        first = True
        for source in self.cache.take_queue(limit=self.MAX_ROWS_PER_TICK,
                                                 ready=lambda value: self.cache.retry_ready(value, self.clock())):
            if (should_stop() or not self._quiet() or attempted >= self.MAX_ROWS_PER_TICK
                    or self.clock() - started >= self.WORK_BUDGET
                    or not self.cache.retry_ready(source, self.clock())):
                self.cache.request(source, priority=_cache.is_progress(source))
                continue
            if not first:
                self.sleep(self.ROW_PAUSE)
            first = False
            if should_stop() or not self._quiet():
                self.cache.request(source, priority=_cache.is_progress(source))
                continue
            current = self.cache.load(source)
            if current is not None and self.clock() - self.cache.used_at(
                    current, self.cache._mtime(self.cache.entry_path(source))) > _cache.PRUNE_AFTER:
                continue  # Queued before the skin stopped showing it: let prune() drop it.
            try:
                attempted += 1
                _cache.validate_source(source)
                pages = self.cache.pages_for(source)
                files, more, next_art = _cache.fetch_listing(self.jsonrpc, source, pages)
                if should_stop():
                    self.cache.request(source, priority=_cache.is_progress(source))
                    continue  # The loop head re-queues the rest of this claimed batch.
                previous = self.cache.load(source)
                if not files and previous and previous.get("files") and not _cache.is_progress(source):
                    # Many providers report a failed fetch as a successful empty directory.
                    # Do not erase useful discovery rows on that ambiguous result.
                    self.cache.record_failure(source, self.clock(), "unexpected_empty")
                    self.cache.request(source)
                    continue
                changed += bool(self.cache.save(source, files, self.clock(), pages=pages, more=more, next_art=next_art))
                done += 1
            except Exception as exc:
                if should_stop():
                    self.cache.request(source, priority=_cache.is_progress(source))
                    continue  # The loop head re-queues the rest of this claimed batch.
                self.cache.record_failure(source, self.clock())
                if current is not None or self.cache.load(source) is not None:
                    self.cache.request(source, priority=_cache.is_progress(source))
                # else: a never-cached row is fetched again by serve() when the skin next shows it.
                self.log("Widget refresh failed (%s); preserving cached row" % type(exc).__name__)
        if attempted:
            self.next_work = self.clock() + self.BATCH_PAUSE
        if changed and not should_stop():
            self.bump(str(int(self.clock())))
            self.log("Widget cache refreshed %d rows, %d changed" % (done, changed))
        return done

"""Spot a stuck connection or low memory before playback fails.

While the TV is quiet, the service makes a tiny plain-HTTP request to a few
services that streaming add-ons depend on. If most of them stop answering,
or memory and swap run low, Kodi shows one notification that says what to do,
instead of an add-on failing later with a cryptic timeout.
"""
import http.client as http_client
import threading
import time
from typing import Any, Dict

# Plain HTTP on port 80: every host answers with a redirect, which proves a
# full request/response round trip without depending on TLS certificates.
DEFAULT_HOSTS = (("TorBox", "api.torbox.app"), ("Trakt", "api.trakt.tv"), ("TMDb", "api.themoviedb.org"))

LAST: Dict[str, Any] = {"internet": None, "memory": None}   # read by the Health page
_LOCK = threading.Lock()


def probe(host, timeout=8.0, connection_class=None):
    """Seconds for one HTTP round trip, or None when it fails or times out."""
    connection_class = connection_class or http_client.HTTPConnection
    started = time.time()
    conn = connection_class(host, 80, timeout=timeout)
    try:
        conn.request("HEAD", "/", headers={"User-Agent": "KodiManager-watchdog"})
        conn.getresponse().read()
        return time.time() - started
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


class Watchdog:
    stop: threading.Event   # set by the service (service_workers.start_watchdog)
    CHECK_EVERY = 10 * 60      # seconds between checks while healthy
    RECHECK_EVERY = 90         # seconds between checks after a failure
    NOTIFY_AGAIN_AFTER = 6 * 3600

    def __init__(self, notify, is_quiet, memory=lambda: {"status": "unknown"}, hosts=DEFAULT_HOSTS,
                 probe=probe, clock=time.time, log=lambda msg: None):
        self.notify, self.is_quiet, self.memory, self.hosts = notify, is_quiet, memory, hosts
        self.probe, self.clock, self.log = probe, clock, log
        self.next_check = clock() + 120
        self.failures = 0
        self.notified = {}
        self.pending = {}   # problems found as playback started: checked again once quiet

    def _quiet(self):
        try:
            return bool(self.is_quiet())
        except Exception:
            return False

    def _notify_once(self, key, title, message):
        now = self.clock()
        if now - self.notified.get(key, float("-inf")) < self.NOTIFY_AGAIN_AFTER:
            return
        # A check can take half a minute: playback may have started meanwhile.
        if not self._quiet():
            self.pending[key] = (title, message)
            return
        self.pending.pop(key, None)
        self.notified[key] = now
        self.log("%s: %s" % (title, message))
        self.notify(title, message)

    def check_internet(self, should_stop=lambda: False):
        """Probe each host in turn; None if ``should_stop`` turns true part way (service exit)."""
        results = []
        for name, host in self.hosts:
            if should_stop():
                return None
            results.append((name, self.probe(host)))
        failed = [name for name, seconds in results if seconds is None]
        slow = [name for name, seconds in results if seconds is not None and seconds > 4]
        status = "error" if len(failed) * 2 > len(results) else "warning" if failed or slow else "ok"
        parts = ["%s %s" % (name, "timed out" if s is None else "%.1fs" % s) for name, s in results]
        result = {"status": status, "detail": " · ".join(parts), "checked_at": int(self.clock()),
                  "failed": failed,
                  "hosts": [{"name": name, "seconds": None if s is None else round(s, 3)} for name, s in results]}
        with _LOCK:
            LAST["internet"] = result
        return result

    def tick(self, should_stop=lambda: False):
        now = self.clock()
        if self.pending and now < self.next_check and self._quiet():
            # A notification held back during playback is never replayed as it was: the
            # problem may have cleared during the film. Check again now instead.
            self.next_check = now
        if now < self.next_check:
            return None
        quiet = self._quiet()
        if not quiet:
            self.next_check = now + 60
            return None
        # This check decides afresh what to say; a problem that is still there notifies again.
        self.pending = {}
        result = self.check_internet(should_stop)
        if result is None:   # the service is stopping
            return None
        if result["status"] == "error":
            self.failures += 1
            self.next_check = now + self.RECHECK_EVERY
            if self.failures >= 2:
                self._notify_once("internet", "Internet connection stuck",
                                  "%s not answering. Restart the Shield if streams fail." % ", ".join(result["failed"]))
        else:
            self.failures = 0
            self.next_check = now + self.CHECK_EVERY
        memory = self.memory()
        with _LOCK:
            LAST["memory"] = memory
        # "Tight" memory (full swap, under a quarter free) is explained on the dashboard only:
        # the TV notification is for memory that is actually running out.
        if memory.get("status") == "warning" and memory.get("pressure") != "tight":
            self._notify_once("memory", "Kodi is low on memory",
                              "Close apps you're not using, or restart Kodi if add-ons start timing out.")
        return result


def latest_internet():
    """The newest connection check as recorded (None before the first one)."""
    with _LOCK:
        result = LAST["internet"]
    return dict(result) if result else None


def internet_check():
    """Health-page entry for the last connection check (None before the first one)."""
    with _LOCK:
        result = LAST["internet"]
    if not result:
        return None
    age = int(time.time() - result["checked_at"])
    return {"id": "internet", "label": "Internet (add-on services)", "status": result["status"],
            "detail": "%s · checked %s min ago" % (result["detail"], age // 60)}

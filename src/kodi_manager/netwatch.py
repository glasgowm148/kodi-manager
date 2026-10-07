"""Spot a stuck connection or low memory before playback fails.

While the TV is quiet, the service makes a tiny plain-HTTP request to a few
services that streaming add-ons depend on. If most of them stop answering,
or memory and swap run low, Kodi shows one notification that says what to do,
instead of an add-on failing later with a cryptic timeout.
"""
import threading
import time

try:
    import http.client as http_client
except ImportError:  # pragma: no cover - Python 2 is not supported
    http_client = None

# Plain HTTP on port 80: every host answers with a redirect, which proves a
# full request/response round trip without depending on TLS certificates.
DEFAULT_HOSTS = (("TorBox", "api.torbox.app"), ("Trakt", "api.trakt.tv"), ("TMDb", "api.themoviedb.org"))

LAST = {"internet": None, "memory": None}   # read by the Health page
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

    def _notify_once(self, key, title, message):
        now = self.clock()
        if now - self.notified.get(key, float("-inf")) >= self.NOTIFY_AGAIN_AFTER:
            self.notified[key] = now
            self.log("%s: %s" % (title, message))
            self.notify(title, message)

    def check_internet(self):
        results = [(name, self.probe(host)) for name, host in self.hosts]
        failed = [name for name, seconds in results if seconds is None]
        slow = [name for name, seconds in results if seconds is not None and seconds > 4]
        status = "error" if len(failed) * 2 > len(results) else "warning" if failed or slow else "ok"
        parts = ["%s %s" % (name, "timed out" if s is None else "%.1fs" % s) for name, s in results]
        result = {"status": status, "detail": " · ".join(parts), "checked_at": int(self.clock()),
                  "failed": failed}
        with _LOCK:
            LAST["internet"] = result
        return result

    def tick(self):
        now = self.clock()
        if now < self.next_check:
            return None
        try:
            quiet = self.is_quiet()
        except Exception:
            quiet = False
        if not quiet:
            self.next_check = now + 60
            return None
        result = self.check_internet()
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
        if memory.get("status") == "warning":
            self._notify_once("memory", "Kodi is low on memory",
                              "Close apps you're not using, or restart Kodi if add-ons start timing out.")
        return result


def internet_check():
    """Health-page entry for the last connection check (None before the first one)."""
    with _LOCK:
        result = LAST["internet"]
    if not result:
        return None
    age = int(time.time() - result["checked_at"])
    return {"id": "internet", "label": "Internet (add-on services)", "status": result["status"],
            "detail": "%s · checked %s min ago" % (result["detail"], age // 60)}

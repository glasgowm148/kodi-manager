"""Quiet-time housekeeping run from the service's watchdog thread.

* Nightly checkpoint: one stack backup per night after 03:00 local time while
  the TV is idle; the newest 7 nightly checkpoints are kept.
* Protected settings: compared shortly after start and every 6 hours.
* Accounts: Trakt and TorBox checked twice a day.
Each problem raises at most one TV notification per day, and never while
something is playing: a problem found during playback is checked again at the
next quiet moment and shown only if it is still there. A checkpoint interrupted
by playback, or by an add-on keeping a database busy, is discarded and retried later.
"""
import threading
import time

LAST = {"baseline": None, "accounts": [], "nightly": None}
_LOCK = threading.Lock()

NIGHTLY_HOUR = 3
NIGHTLY_KEEP = 7


def snapshot():
    with _LOCK:
        return {"baseline": LAST["baseline"], "accounts": list(LAST["accounts"]), "nightly": LAST["nightly"]}


class Maintenance:
    BASELINE_EVERY = 6 * 3600
    ACCOUNTS_EVERY = 12 * 3600
    NOTIFY_AGAIN_AFTER = 24 * 3600
    RETRY_DEFERRED_AFTER = 10 * 60
    # Checkpoints stopped by a busy database are retried this many times a day; then
    # the night is recorded as failed (an add-on holding a database locked for hours).
    BUSY_RETRIES = 6

    def __init__(self, notify, baseline=None, accounts=lambda: [], checkpoint=None, clock=time.time,
                 localtime=time.localtime, log=lambda msg: None, last_nightly_day=None, is_quiet=None,
                 stopping=lambda: False):
        self.notify, self.baseline, self.accounts, self.checkpoint = notify, baseline, accounts, checkpoint
        # True once the service is exiting: no further Kodi calls between or after steps.
        self.stopping = stopping
        self.clock, self.localtime, self.log = clock, localtime, log
        # Asked again just before a notification: checks can outlast the quiet spell.
        self.is_quiet = is_quiet
        now = clock()
        self.next_baseline = now + 90
        self.next_accounts = now + 180
        self.next_nightly = float("-inf")
        self.last_nightly_day = last_nightly_day
        self.notified = {}
        self.pending = {}
        self.busy_day, self.busy_retries = None, 0

    def _quiet_now(self):
        if self.is_quiet is None:
            return True
        try:
            return bool(self.is_quiet())
        except Exception:
            return False

    def _notify_once(self, key, title, message):
        now = self.clock()
        if now - self.notified.get(key, float("-inf")) < self.NOTIFY_AGAIN_AFTER:
            return
        if not self._quiet_now():
            self.pending[key] = (title, message)
            return
        self.pending.pop(key, None)
        self.notified[key] = now
        self.log("%s: %s" % (title, message))
        self.notify(title, message)

    def tick(self, quiet):
        """Run whatever is due. ``quiet`` is True when the TV is idle."""
        now = self.clock()
        ran = []
        if quiet and self.pending:
            # Held notifications are not replayed as they were: the setting may have been
            # re-applied or the account renewed meanwhile. Their checks run again now and
            # notify only if the problem is still there.
            if any(key.startswith("baseline:") for key in self.pending):
                self.next_baseline = min(self.next_baseline, now)
            if any(key.startswith("account:") for key in self.pending):
                self.next_accounts = min(self.next_accounts, now)
            self.pending = {}
        if quiet and self.checkpoint is not None and now >= self.next_nightly:
            local = self.localtime(now)
            day = time.strftime("%Y-%m-%d", local)
            if local.tm_hour >= NIGHTLY_HOUR and day != self.last_nightly_day:
                previous_day, self.last_nightly_day = self.last_nightly_day, day
                try:
                    result = self.checkpoint()
                    with _LOCK:
                        LAST["nightly"] = {"status": "ok", "at": int(now), "backup_id": (result or {}).get("backup_id")}
                except Exception as exc:
                    busy = getattr(exc, "reason", None) == "busy_database"
                    if busy and day != self.busy_day:
                        self.busy_day, self.busy_retries = day, 0
                    if getattr(exc, "deferred", False) and not (busy and self.busy_retries >= self.BUSY_RETRIES):
                        # The partial checkpoint was discarded: try again later the same night.
                        self.last_nightly_day = previous_day
                        self.next_nightly = self.clock() + self.RETRY_DEFERRED_AFTER
                        if busy:
                            # An add-on kept writing a database while it was copied.
                            self.busy_retries += 1
                            with _LOCK:
                                LAST["nightly"] = {"status": "retrying", "at": int(now), "error": "busy_database"}
                            self.log("Nightly checkpoint postponed: an add-on was writing its database; "
                                     "retrying in %d minutes" % (self.RETRY_DEFERRED_AFTER // 60))
                        else:
                            self.log("Nightly checkpoint postponed: the TV is in use")
                        ran.append("nightly")
                        return ran
                    error = "busy_database" if busy else type(exc).__name__
                    with _LOCK:
                        LAST["nightly"] = {"status": "error", "at": int(now), "error": error}
                    self.log("Nightly checkpoint failed: %s" % error)
                ran.append("nightly")
        if self.stopping():
            return ran
        if quiet and self.baseline is not None and now >= self.next_baseline:
            self.next_baseline = now + self.BASELINE_EVERY
            rows = self.baseline.check()
            if self.stopping():
                return ran
            drift = [row for row in rows if not row["ok"] and not row["missing"]]
            with _LOCK:
                LAST["baseline"] = {"at": int(now), "total": len(rows), "drifted": drift}
            if drift:
                names = ", ".join(row["label"] for row in drift[:2]) + (" and more" if len(drift) > 2 else "")
                self._notify_once("baseline:" + ",".join(sorted(row["key"] for row in drift)),
                                  "Settings changed", "%s changed (often after an update). Re-apply in Kodi Manager → Health." % names)
            ran.append("baseline")
        if self.stopping():
            return ran
        if quiet and now >= self.next_accounts:
            self.next_accounts = now + self.ACCOUNTS_EVERY
            results = [r for r in self.accounts() if r]
            if self.stopping():
                return ran
            with _LOCK:
                LAST["accounts"] = results
            for result in results:
                if result["status"] != "ok":
                    self._notify_once("account:%s:%s" % (result["id"], result["status"]), result["label"], result["detail"][:120])
            ran.append("accounts")
        return ran


def nightly_checkpoint(make_backup, list_backups, delete_backup, keep=NIGHTLY_KEEP):
    """Take a nightly stack backup and keep only the newest ``keep`` nightly ones."""
    result = make_backup()
    nightly = [b for b in list_backups() if b.get("note") == "nightly"]
    nightly.sort(key=lambda b: str(b.get("timestamp") or b.get("backup_id")), reverse=True)
    for old in nightly[keep:]:
        try:
            delete_backup(old["backup_id"])
        except Exception:
            pass
    return result

"""Quiet-time housekeeping run from the service's watchdog thread.

* Nightly checkpoint: one stack backup per night after 03:00 local time while
  the TV is idle; the newest 7 nightly checkpoints are kept.
* Protected settings: compared shortly after start and every 6 hours.
* Accounts: Trakt and TorBox checked twice a day.
Each problem raises at most one TV notification per day.
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

    def __init__(self, notify, baseline=None, accounts=lambda: [], checkpoint=None, clock=time.time,
                 localtime=time.localtime, log=lambda msg: None, last_nightly_day=None):
        self.notify, self.baseline, self.accounts, self.checkpoint = notify, baseline, accounts, checkpoint
        self.clock, self.localtime, self.log = clock, localtime, log
        now = clock()
        self.next_baseline = now + 90
        self.next_accounts = now + 180
        self.last_nightly_day = last_nightly_day
        self.notified = {}

    def _notify_once(self, key, title, message):
        now = self.clock()
        if now - self.notified.get(key, float("-inf")) >= self.NOTIFY_AGAIN_AFTER:
            self.notified[key] = now
            self.log("%s: %s" % (title, message))
            self.notify(title, message)

    def tick(self, quiet):
        """Run whatever is due. ``quiet`` is True when the TV is idle."""
        now = self.clock()
        ran = []
        if quiet and self.checkpoint is not None:
            local = self.localtime(now)
            day = time.strftime("%Y-%m-%d", local)
            if local.tm_hour >= NIGHTLY_HOUR and day != self.last_nightly_day:
                self.last_nightly_day = day
                try:
                    result = self.checkpoint()
                    with _LOCK:
                        LAST["nightly"] = {"status": "ok", "at": int(now), "backup_id": (result or {}).get("backup_id")}
                except Exception as exc:
                    with _LOCK:
                        LAST["nightly"] = {"status": "error", "at": int(now), "error": type(exc).__name__}
                    self.log("Nightly checkpoint failed: %s" % type(exc).__name__)
                ran.append("nightly")
        if quiet and self.baseline is not None and now >= self.next_baseline:
            self.next_baseline = now + self.BASELINE_EVERY
            rows = self.baseline.check()
            drift = [row for row in rows if not row["ok"] and not row["missing"]]
            with _LOCK:
                LAST["baseline"] = {"at": int(now), "total": len(rows), "drifted": drift}
            if drift:
                names = ", ".join(row["label"] for row in drift[:2]) + (" and more" if len(drift) > 2 else "")
                self._notify_once("baseline:" + ",".join(sorted(row["key"] for row in drift)),
                                  "Settings changed", "%s changed (often after an update). Re-apply in Kodi Manager → Health." % names)
            ran.append("baseline")
        if quiet and now >= self.next_accounts:
            self.next_accounts = now + self.ACCOUNTS_EVERY
            results = [r for r in self.accounts() if r]
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

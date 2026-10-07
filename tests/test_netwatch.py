from kodi_manager import netwatch
from kodi_manager.netwatch import Watchdog, internet_check


class Clock:
    def __init__(self, t=10 ** 6):
        self.t = t

    def __call__(self):
        return self.t


def make(results, quiet=True, memory=None):
    clock, notes = Clock(), []
    answers = dict(results)
    dog = Watchdog(lambda title, msg: notes.append((title, msg)), lambda: quiet,
                   memory=memory or (lambda: {"status": "ok"}),
                   probe=lambda host: answers[host], clock=clock)
    dog.next_check = 0
    return dog, clock, notes


HOSTS = {"api.torbox.app": 0.2, "api.trakt.tv": 0.3, "api.themoviedb.org": 0.2}


def test_healthy_connection_is_ok_and_quiet():
    dog, clock, notes = make(HOSTS)
    assert dog.tick()["status"] == "ok" and notes == []
    assert internet_check()["status"] == "ok"
    assert dog.next_check == clock.t + Watchdog.CHECK_EVERY


def test_stuck_connection_notifies_once_after_two_failed_checks():
    dog, clock, notes = make({"api.torbox.app": None, "api.trakt.tv": None, "api.themoviedb.org": 0.4})
    assert dog.tick()["status"] == "error" and notes == []      # one failure could be a blip
    clock.t = dog.next_check
    dog.tick()
    assert len(notes) == 1 and "TorBox, Trakt" in notes[0][1]
    for _ in range(3):
        clock.t = dog.next_check
        dog.tick()
    assert len(notes) == 1                                       # no repeat for 6 hours
    assert "timed out" in internet_check()["detail"]


def test_waits_while_tv_is_busy():
    dog, clock, notes = make(HOSTS, quiet=False)
    assert dog.tick() is None and netwatch.LAST is not None


def test_low_memory_notifies():
    dog, clock, notes = make(HOSTS, memory=lambda: {"status": "warning"})
    dog.tick()
    assert notes and notes[0][0] == "Kodi is low on memory"


def test_probe_reports_failures_as_none():
    class Broken:
        def __init__(self, *a, **k):
            pass
        def request(self, *a, **k):
            raise OSError("timed out")
        def close(self):
            pass
    assert netwatch.probe("example.invalid", connection_class=Broken) is None

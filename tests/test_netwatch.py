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


def test_notification_waits_when_playback_starts_during_the_check():
    """The check itself can take half a minute; a film may have started meanwhile."""
    state = {"quiet": True}
    clock, notes = Clock(), []

    def slow_probe(host):
        if not state.get("started"):
            state["quiet"] = False      # playback starts while probing
            state["started"] = True
        return None
    dog = Watchdog(lambda title, msg: notes.append(title), lambda: state["quiet"], probe=slow_probe, clock=clock)
    dog.next_check = 0
    dog.failures = 1
    dog.tick()
    assert notes == []
    dog.tick()                          # still playing
    assert notes == []
    state["quiet"] = True
    dog.tick()                          # checked again at the next quiet moment: still stuck
    assert notes == ["Internet connection stuck"]


def test_a_problem_that_cleared_during_the_film_is_not_announced_afterwards():
    state = {"quiet": True, "up": False, "memory": "warning"}
    clock, notes = Clock(), []

    def probe(host):
        if not state["up"]:
            state["quiet"] = False      # a film starts during the probes
        return 0.2 if state["up"] else None
    dog = Watchdog(lambda title, msg: notes.append(title), lambda: state["quiet"],
                   memory=lambda: {"status": state["memory"]}, probe=probe, clock=clock)
    dog.next_check = 0
    dog.failures = 1
    dog.tick()
    assert notes == [] and set(dog.pending) == {"internet", "memory"}
    for _ in range(480):                # a two-hour film, ticking every 15 s
        clock.t += 15
        dog.tick()
    state.update(up=True, memory="ok")  # the connection and memory recovered meanwhile
    state["quiet"] = True
    clock.t += 15
    dog.tick()
    assert notes == [] and dog.pending == {}


def test_probes_stop_when_the_service_is_exiting():
    calls = []
    dog = Watchdog(lambda title, msg: None, lambda: True, probe=lambda host: calls.append(host) or 0.1,
                   clock=Clock())
    dog.next_check = 0
    stop = {"set": False}

    def stopping():
        if calls:
            stop["set"] = True
        return stop["set"]
    assert dog.tick(stopping) is None
    assert calls == ["api.torbox.app"]  # no further 8-second probes once Kodi asks to stop


import time

import pytest

from kodi_manager import maintenance
from kodi_manager import account_health
from kodi_manager.account_health import run_checks, torbox_status, trakt_status
from kodi_manager.baseline import Baseline
from kodi_manager.maintenance import Maintenance, nightly_checkpoint


class FakeKodi:
    def __init__(self):
        self.addon = {("plugin.video.pov", "reuse_language_invoker"): "false"}
        self.kodi = {"general.addonupdates": 1}

    def get_addon_setting(self, addon, sid):
        return self.addon.get((addon, sid), "")

    def set_addon_setting(self, addon, sid, value):
        self.addon[(addon, sid)] = value

    def jsonrpc(self, method, params):
        if method == "Settings.GetSettingValue":
            return {"result": {"value": self.kodi.get(params["setting"])}}
        self.kodi[params["setting"]] = params["value"]
        return {"result": True}


@pytest.fixture
def setup(tmp_path):
    addon_dir = tmp_path / "plugin.video.pov"
    addon_dir.mkdir()
    (addon_dir / "addon.xml").write_text('<addon><extension point="xbmc.python.pluginsource">'
                                         '<reuselanguageinvoker>false</reuselanguageinvoker></extension></addon>')
    kodi = FakeKodi()
    base = Baseline(str(tmp_path / "baseline.json"), kodi, addon_path=lambda aid: str(tmp_path / aid))
    base.capture([
        {"kind": "addon_setting", "addon": "plugin.video.pov", "id": "reuse_language_invoker", "label": "POV invoker setting"},
        {"kind": "kodi_setting", "id": "general.addonupdates", "label": "Add-on updates"},
        {"kind": "addon_xml", "addon": "plugin.video.pov", "tag": "reuselanguageinvoker", "label": "POV addon.xml invoker"},
    ])
    return kodi, base, addon_dir


def test_update_drift_is_found_and_reapplied(setup):
    kodi, base, addon_dir = setup
    assert all(row["ok"] for row in base.check())
    # A POV update rewrites addon.xml and its setting; a Kodi change turns auto-updates back on.
    (addon_dir / "addon.xml").write_text('<addon><reuselanguageinvoker>true</reuselanguageinvoker></addon>')
    kodi.addon[("plugin.video.pov", "reuse_language_invoker")] = "true"
    kodi.kodi["general.addonupdates"] = 0
    assert len(base.drifted()) == 3
    result = base.apply()
    assert len(result["applied"]) == 3 and result["restart_required"] and not result["failed"]
    assert "<reuselanguageinvoker>false</reuselanguageinvoker>" in (addon_dir / "addon.xml").read_text()
    assert base.drifted() == []


def test_unsafe_items_are_refused(setup):
    _, base, _ = setup
    for bad in ({"kind": "kodi_setting", "id": "services.webserverauthentication", "value": False},
                {"kind": "addon_setting", "addon": "service.kodi.addonadmin", "id": "auth_token", "value": "x"},
                {"kind": "addon_xml", "addon": "../etc", "tag": "x", "value": "y"},
                {"kind": "shell", "id": "x"}):
        with pytest.raises(ValueError):
            base.capture([bad])


def test_addon_xml_values_cannot_inject_markup(setup):
    _, base, addon_dir = setup
    original = (addon_dir / "addon.xml").read_text()
    for bad in ("false</reuselanguageinvoker><extension point=\"x\"/><reuselanguageinvoker>", "a & b", "1\n2"):
        with pytest.raises(ValueError):
            base.capture([{"kind": "addon_xml", "addon": "plugin.video.pov", "tag": "reuselanguageinvoker", "value": bad}])
    # A hand-edited baseline.json is refused at apply time too.
    items = base.items()
    for item in items:
        if item["kind"] == "addon_xml":
            item["value"] = "true</reuselanguageinvoker><broken>"
    base.save(items)
    result = base.apply()
    assert [f["key"] for f in result["failed"]] == ["xml:plugin.video.pov:reuselanguageinvoker"]
    assert (addon_dir / "addon.xml").read_text() == original


def test_missing_items_are_not_reported_as_drift(setup):
    _, base, _ = setup
    base.capture([{"kind": "addon_xml", "addon": "plugin.video.gone", "tag": "x", "value": "1"}])
    assert all(r["key"] != "xml:plugin.video.gone:x" for r in base.drifted())


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_nightly_runs_once_per_night_only_when_quiet():
    clock = Clock(time.mktime((2026, 10, 8, 2, 0, 0, 0, 0, -1)))
    runs = []
    m = Maintenance(lambda *a: None, checkpoint=lambda: runs.append(1) or {"backup_id": "x"}, clock=clock)
    m.tick(True)
    assert runs == []                    # before 03:00
    clock.t += 2 * 3600
    m.tick(False)
    assert runs == []                    # TV in use
    m.tick(True)
    m.tick(True)
    assert runs == [1]                   # once that night
    assert maintenance.snapshot()["nightly"]["status"] == "ok"
    clock.t += 24 * 3600
    m.tick(True)
    assert runs == [1, 1]


def test_nightly_keeps_newest_seven():
    backups = [{"backup_id": "202610%02d-030000-x" % d, "timestamp": "202610%02d" % d, "note": "nightly"} for d in range(1, 11)]
    backups.append({"backup_id": "manual", "timestamp": "20260101", "note": ""})
    deleted = []
    nightly_checkpoint(lambda: {"backup_id": "new"}, lambda: backups, deleted.append)
    assert sorted(deleted) == ["20261001-030000-x", "20261002-030000-x", "20261003-030000-x"]


def test_drift_and_account_problems_notify_once_a_day(setup):
    kodi, base, _ = setup
    kodi.kodi["general.addonupdates"] = 0
    clock, notes = Clock(10 ** 9), []
    m = Maintenance(lambda title, msg: notes.append(title), baseline=base, clock=clock,
                    accounts=lambda: [{"id": "torbox", "label": "TorBox subscription", "status": "warning", "detail": "Ends soon"}])
    clock.t += 200
    m.tick(True)
    assert notes == ["Settings changed", "TorBox subscription"]
    clock.t += 7 * 3600
    m.tick(True)
    assert notes == ["Settings changed", "TorBox subscription"]


def test_trakt_status():
    now = 10 ** 9
    settings = {"trakt.token": "t", "trakt.expires": str(now + 3 * 86400), "trakt_user": "me"}
    get = lambda addon, sid: settings.get(sid, "")  # noqa: E731
    assert trakt_status(get, now)["status"] == "ok"
    settings["trakt.expires"] = str(now - 5 * 86400)
    assert trakt_status(get, now)["status"] == "warning"
    settings["trakt.token"] = ""
    assert trakt_status(get, now) is None


def test_torbox_status():
    get = lambda addon, sid: {"tb.token": "t", "tb.enabled": "true"}.get(sid, "")  # noqa: E731
    now = time.mktime((2027, 7, 30, 0, 0, 0, 0, 0, 0)) - time.timezone
    ok = {"success": True, "data": {"premium_expires_at": "2027-08-05T17:55:13Z"}}
    assert torbox_status(get, now=now - 100 * 86400, fetch=lambda t: ok)["status"] == "ok"
    assert torbox_status(get, now=now, fetch=lambda t: ok)["status"] == "warning"
    assert torbox_status(get, now=now + 30 * 86400, fetch=lambda t: ok)["status"] == "error"
    assert torbox_status(get, now=now, fetch=lambda t: {"success": False})["status"] == "warning"
    def boom(t):
        raise OSError("timed out")
    assert "Could not reach" in torbox_status(get, now=now, fetch=boom)["detail"]



def test_torbox_expiry_does_not_use_datetime_strptime(monkeypatch):
    """On Kodi's Python 3.8, datetime.strptime raises TypeError ('NoneType' object is not
    callable) once another add-on's sub-interpreter has used it and exited."""
    class Broken:
        @staticmethod
        def strptime(*args):
            raise TypeError("'NoneType' object is not callable")
    monkeypatch.setattr(account_health, "datetime", Broken, raising=False)
    get = lambda addon, sid: {"tb.token": "t", "tb.enabled": "true"}.get(sid, "")  # noqa: E731
    ok = {"success": True, "data": {"premium_expires_at": "2027-08-05T17:55:13Z"}}
    expires = 1817488513  # 2027-08-05T17:55:13Z
    result = torbox_status(get, now=expires - 3 * 86400, fetch=lambda t: ok)
    assert result["status"] == "warning" and "(3 days)" in result["detail"]
    assert torbox_status(get, now=expires + 1, fetch=lambda t: ok)["status"] == "error"


def test_one_crashing_account_check_does_not_hide_the_others():
    logged = []

    def crash():
        raise TypeError("boom")
    ok = {"id": "trakt", "status": "ok"}
    assert run_checks([crash, lambda: ok], logged.append) == [ok]
    assert logged == ["Account check failed: TypeError"]


def test_problem_found_while_quiet_waits_if_playback_starts_before_the_notification(setup):
    kodi, base, _ = setup
    kodi.kodi["general.addonupdates"] = 0
    state = {"quiet": True}
    clock, notes = Clock(10 ** 9), []

    def accounts():
        if not state.get("started"):
            state["quiet"] = False      # playback starts while the accounts are checked
            state["started"] = True
        return [{"id": "torbox", "label": "TorBox subscription", "status": "warning", "detail": "Ends soon"}]
    m = Maintenance(lambda title, msg: notes.append(title), clock=clock, accounts=accounts,
                    is_quiet=lambda: state["quiet"])
    clock.t += 200
    m.tick(True)
    assert notes == []
    m.tick(False)
    assert notes == []
    state["quiet"] = True
    m.tick(True)
    assert notes == ["TorBox subscription"]



def test_held_notifications_are_dropped_when_the_problem_cleared_during_playback(setup):
    kodi, base, _ = setup
    kodi.kodi["general.addonupdates"] = 0
    state = {"quiet": False, "torbox": "warning"}
    clock, notes = Clock(10 ** 9), []
    m = Maintenance(lambda title, msg: notes.append(title), baseline=base, clock=clock,
                    accounts=lambda: [{"id": "torbox", "label": "TorBox subscription",
                                       "status": state["torbox"], "detail": "Ends soon"}],
                    is_quiet=lambda: state["quiet"])
    clock.t += 200
    m.tick(True)                        # both found just as a film starts
    assert notes == [] and len(m.pending) == 2
    clock.t += 2 * 3600
    m.tick(False)
    kodi.kodi["general.addonupdates"] = 1   # re-applied from the Health page during the film
    state["torbox"] = "ok"                  # and the subscription renewed
    state["quiet"] = True
    m.tick(True)
    assert notes == [] and m.pending == {}


def test_nightly_checkpoint_stops_when_the_service_exits(monkeypatch):
    import threading
    from types import SimpleNamespace
    from kodi_manager import addon_index, backup, dashboard_data, service
    seen = {}

    def stack_backup(addons, kodi_version="", note="", should_stop=None):
        seen["should_stop"] = should_stop
        return {"backup_id": "x"}
    monkeypatch.setattr(backup, "create_stack_backup", stack_backup)
    monkeypatch.setattr(backup, "list_backups", lambda **kwargs: [])
    monkeypatch.setattr(dashboard_data, "stack_backup_addons", lambda kodi, index: [])
    monkeypatch.setattr(dashboard_data, "make_baseline", lambda kodi: None)
    monkeypatch.setattr(addon_index, "AddonIndex", lambda kodi: SimpleNamespace(refresh=lambda force=False, should_stop=None: seen.update(index_should_stop=should_stop)))
    kodi = SimpleNamespace(log=lambda msg: None, notify=lambda *a: None, get_kodi_version=lambda: "22",
                           get_addon_setting=lambda addon, sid: "")
    stop = threading.Event()
    m = service.start_maintenance(kodi, is_busy=lambda: False, stopping=stop.is_set)
    m.checkpoint()
    assert seen["should_stop"]() is False
    assert seen["index_should_stop"]() is False
    stop.set()                          # Kodi is quitting or switching profile
    assert seen["should_stop"]() is True
    assert seen["index_should_stop"]() is True

def test_nightly_checkpoint_interrupted_by_playback_is_retried_later():
    class Deferred(Exception):
        deferred = True
    clock = Clock(time.mktime((2026, 10, 8, 3, 30, 0, 0, 0, -1)))
    outcomes = [Deferred(), {"backup_id": "x"}]
    runs = []

    def checkpoint():
        runs.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
    m = Maintenance(lambda *a: None, checkpoint=checkpoint, clock=clock)
    before = maintenance.snapshot()["nightly"]
    m.tick(True)
    assert runs == [1] and maintenance.snapshot()["nightly"] == before   # not reported as a failure
    clock.t += 60
    m.tick(True)
    assert runs == [1]                   # backs off instead of re-copying every tick
    clock.t += Maintenance.RETRY_DEFERRED_AFTER
    m.tick(True)
    assert runs == [1, 1] and maintenance.snapshot()["nightly"]["status"] == "ok"
    m.tick(True)
    assert runs == [1, 1]

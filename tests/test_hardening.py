import time

import pytest

from kodi_manager import maintenance
from kodi_manager.account_health import torbox_status, trakt_status
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

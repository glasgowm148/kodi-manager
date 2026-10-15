"""The dashboard's bounded 7-day history: sampling, retention, bounds, atomic writes and its endpoints."""
import http.client
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from kodi_manager import metrics
from kodi_manager.metrics import MetricsHistory, Sampler, build_sample, clean_sample, widget_row_counts

DAY = 86400
NOW = 1_800_000_000
MEMORY = {"status": "ok", "available_mb": 1200, "total_mb": 2900, "kodi_mb": 610, "swap_used_pct": 40}
PROBE = {"status": "ok", "checked_at": NOW - 30,
         "hosts": [{"name": "TorBox", "seconds": 0.412}, {"name": "Trakt", "seconds": None}, {"name": "TMDb", "seconds": 0.2}]}


def history(tmp_path, **kwargs):
    return MetricsHistory(str(tmp_path / "metrics_history.json"), **kwargs)


def test_sample_holds_memory_rows_and_a_new_probe_in_milliseconds():
    sample = build_sample(NOW, memory=MEMORY, internet=PROBE, rows={"cached": 18, "failing": 2, "persistent": 1})
    assert sample == {"t": NOW, "ma": 1200, "mt": 2900, "mk": 610, "sw": 40, "ns": "ok", "nt": NOW - 30,
                      "nh": {"TorBox": 412, "Trakt": None, "TMDb": 200}, "rc": 18, "rf": 2, "rp": 1}


def test_a_probe_already_recorded_is_not_repeated_and_unknown_memory_is_left_out():
    sample = build_sample(NOW, memory={"status": "unknown"}, internet=PROBE, last_probe=NOW - 30)
    assert sample == {"t": NOW}


def test_damaged_or_hostile_samples_are_dropped_or_cleaned():
    assert clean_sample({"t": "x"}) is None
    assert clean_sample([1, 2]) is None
    assert clean_sample({"t": -5}) is None
    cleaned = clean_sample({"t": NOW, "ma": float("nan"), "mt": True, "rc": -3, "ns": "<b>", "nh": {"x": 1}, "extra": "y"})
    assert cleaned == {"t": NOW}
    cleaned = clean_sample({"t": NOW, "ns": "error", "nh": {"A": 5, "B": "slow", "": 3, "C" * 50: 1}})
    assert cleaned == {"t": NOW, "ns": "error", "nh": {"A": 5, "B": None}}


def test_record_keeps_one_sample_per_resolution(tmp_path):
    h = history(tmp_path)
    assert h.record({"t": NOW, "ma": 1}, now=NOW)
    assert not h.record({"t": NOW + 60, "ma": 2}, now=NOW + 60)
    assert h.record({"t": NOW + metrics.RESOLUTION, "ma": 3}, now=NOW + metrics.RESOLUTION)
    assert [s["ma"] for s in h.load()] == [1, 3]


def test_samples_older_than_seven_days_are_dropped(tmp_path):
    h = history(tmp_path)
    for i in range(8 * 4):
        h.record({"t": NOW + i * DAY // 4, "ma": i}, now=NOW + i * DAY // 4)
    samples = h.load()
    last = NOW + 31 * DAY // 4
    assert samples[-1]["t"] == last
    assert min(s["t"] for s in samples) >= last - 7 * DAY
    assert len(samples) == 29


def test_sample_count_and_file_size_are_capped(tmp_path):
    h = history(tmp_path, max_samples=50, resolution=60)
    for i in range(80):
        h.record({"t": NOW + i * 60, "ma": i}, now=NOW + i * 60)
    assert len(h.load()) == 50 and h.load()[-1]["ma"] == 79
    small = MetricsHistory(str(tmp_path / "small.json"), resolution=60, max_bytes=2000)
    for i in range(200):
        small.record(build_sample(NOW + i * 60, memory=MEMORY, internet=dict(PROBE, checked_at=NOW + i), rows={"cached": 1}), now=NOW + i * 60)
    assert os.path.getsize(tmp_path / "small.json") < 2200
    assert small.load()[-1]["t"] == NOW + 199 * 60


def test_seven_days_at_fifteen_minutes_stays_small(tmp_path):
    h = history(tmp_path)
    for i in range(7 * 96):
        t = NOW + i * metrics.RESOLUTION
        h.record(build_sample(t, memory=MEMORY, internet=dict(PROBE, checked_at=t), rows={"cached": 20, "failing": 1, "persistent": 0}), now=t)
    assert len(h.load()) == 7 * 96
    assert os.path.getsize(h.path) < metrics.MAX_BYTES


def test_writes_are_atomic_and_a_failed_write_keeps_the_old_history(tmp_path):
    h = history(tmp_path)
    h.record({"t": NOW, "ma": 1}, now=NOW)
    before = Path(h.path).read_bytes()
    with patch.object(metrics, "atomic_write_json", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            h.record({"t": NOW + metrics.RESOLUTION, "ma": 2}, now=NOW + metrics.RESOLUTION)
    assert Path(h.path).read_bytes() == before
    assert [p.name for p in tmp_path.iterdir()] == ["metrics_history.json"]
    data = json.loads(before)
    assert data["version"] == 1 and data["resolution"] == metrics.RESOLUTION


def test_a_damaged_file_starts_a_fresh_history(tmp_path):
    h = history(tmp_path)
    Path(h.path).write_text("{not json")
    assert h.load() == []
    assert h.record({"t": NOW, "ma": 5}, now=NOW)
    Path(h.path).write_text(json.dumps({"samples": "nope"}))
    assert h.load() == []
    Path(h.path).write_text(json.dumps({"samples": [{"t": NOW, "ma": 1}, "junk", {"t": NOW - 900, "ma": 2}]}))
    assert [s["ma"] for s in h.load()] == [2, 1]


def test_samples_from_a_clock_far_in_the_future_are_dropped(tmp_path):
    h = history(tmp_path)
    h.record({"t": NOW + 10 * DAY, "ma": 9}, now=NOW + 10 * DAY)
    h.record({"t": NOW, "ma": 1}, now=NOW)
    assert [s["ma"] for s in h.load()] == [1]


def test_series_are_aligned_columns_with_gaps_as_null(tmp_path):
    h = history(tmp_path)
    h.record(build_sample(NOW - 2 * 3600, memory=MEMORY, internet=PROBE, rows={"cached": 3, "failing": 1, "persistent": 0}), now=NOW - 2 * 3600)
    h.record(build_sample(NOW - 3600, memory={"status": "unknown"}, rows={"cached": 3, "failing": 0, "persistent": 0}), now=NOW - 3600)
    data = h.series(7, now=NOW)
    assert data["count"] == 2 and data["resolution_seconds"] == 900 and data["retention_days"] == 7
    assert data["series"]["memory_available_mb"] == [1200, None]
    assert data["series"]["rows_failing"] == [1, 0]
    assert data["series"]["network_status"] == ["ok", None]
    assert data["hosts"] == ["TorBox", "Trakt", "TMDb"]
    assert data["latency_ms"]["TorBox"] == [412, None]
    assert h.series(1, now=NOW + 2 * DAY)["count"] == 0
    for bad in (0, 8, "x", None):
        with pytest.raises(ValueError):
            h.series(bad, now=NOW)


def test_widget_row_counts_read_only_health_records(tmp_path):
    (tmp_path / "entries").mkdir()
    (tmp_path / "health").mkdir()
    for name in ("a", "b", "c", "d"):
        (tmp_path / "entries" / (name + ".json")).write_text("{}")
    (tmp_path / "health" / "a.json").write_text('{"failures": 1}')
    (tmp_path / "health" / "b.json").write_text('{"failures": 4}')
    (tmp_path / "health" / "c.json").write_text("broken")
    (tmp_path / "health" / "gone.json").write_text('{"failures": 9}')
    assert widget_row_counts(str(tmp_path)) == {"cached": 4, "failing": 2, "persistent": 1}
    assert widget_row_counts(str(tmp_path / "missing")) == {"cached": 0, "failing": 0, "persistent": 0}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def test_sampler_runs_only_while_quiet_and_never_probes(tmp_path):
    clock = Clock(NOW)
    probe = dict(PROBE)
    memory = Mock(return_value=MEMORY)
    sampler = Sampler(history(tmp_path, clock=clock), memory, lambda: probe, lambda: {"cached": 2}, clock=clock, first_after=60)
    assert not sampler.tick(True)                      # not due yet
    clock.t += 60
    assert not sampler.tick(False)                     # TV busy: nothing read at all
    memory.assert_not_called()
    assert sampler.tick(True)
    assert "nh" in sampler.history.load()[-1]
    clock.t += metrics.RESOLUTION
    assert sampler.tick(True)
    assert "nh" not in sampler.history.load()[-1], "the same probe is not recorded twice"
    probe["checked_at"] = clock.t
    clock.t += metrics.RESOLUTION
    assert sampler.tick(True)
    assert sampler.history.load()[-1]["nt"] == probe["checked_at"]


def test_sampler_remembers_the_last_recorded_probe_across_restarts(tmp_path):
    clock = Clock(NOW)
    h = history(tmp_path, clock=clock)
    h.record(build_sample(NOW - 3600, internet=PROBE), now=NOW - 3600)
    sampler = Sampler(h, lambda: MEMORY, lambda: PROBE, lambda: None, clock=clock, first_after=0)
    assert sampler.tick(True)
    assert "nh" not in h.load()[-1]


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import server  # noqa: E402
import dashboard_data  # noqa: E402
import api_status  # noqa: E402


@pytest.fixture
def dashboard(tmp_path):
    calls = []
    replies = {"Player.GetActivePlayers": {"result": []}, "Profiles.GetCurrentProfile": {"result": {"label": "Kids"}}}

    def jsonrpc(method, params=None):
        calls.append(method)
        return replies.get(method, {})
    state = SimpleNamespace(
        kodi=SimpleNamespace(jsonrpc=jsonrpc, get_kodi_version=lambda: "22.0", get_log_lines=lambda n=300: []),
        index=SimpleNamespace(refresh=Mock(), get=lambda aid: None, addons={}, list=lambda: []),
        config={"auth_token": "tok", "host": "127.0.0.1", "write_enabled": False, "allowed_addons_csv": ""},
        log=lambda message: None, logs=[], web_root="")
    path = tmp_path / "metrics_history.json"
    h = MetricsHistory(str(path))
    h.record(build_sample(NOW - 3600, memory=MEMORY, internet=PROBE, rows={"cached": 3, "failing": 1, "persistent": 0}), now=NOW - 3600)
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def call(target, token="tok"):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
        conn.request("GET", target, headers={"Authorization": "Bearer " + token} if token else {})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        return response.status, body
    real_translate = server.translate
    fake_translate = lambda p: str(path) if p == server.HISTORY_FILE else str(tmp_path / "cache") if p == server.WIDGET_CACHE_DIR else real_translate(p)  # noqa: E731
    with patch.object(api_status, "translate", fake_translate), patch.object(dashboard_data, "translate", fake_translate), \
            patch.object(server.time, "time", return_value=NOW), \
            patch.object(dashboard_data, "list_backups", return_value=[{"backup_id": "20260101-030000-x", "timestamp": "20260101-030000", "note": "nightly", "total_bytes": 2048}]), \
            patch.object(dashboard_data, "make_baseline", side_effect=RuntimeError("no baseline")), \
            patch.object(dashboard_data, "protection_for_kodi", side_effect=RuntimeError("no fixes")):
        yield SimpleNamespace(call=call, calls=calls, replies=replies)
    httpd.shutdown()
    httpd.server_close()
    thread.join()


def test_history_endpoint_needs_the_token_and_returns_columns(dashboard):
    status, body = dashboard.call("/api/metrics/history", token="")
    assert status == 401
    status, body = dashboard.call("/api/metrics/history?days=2")
    assert status == 200 and body["data"]["count"] == 1
    assert body["data"]["series"]["memory_available_mb"] == [1200]
    assert body["data"]["latency_ms"]["TorBox"] == [412]
    status, body = dashboard.call("/api/metrics/history?days=30")
    assert status == 400 and body["error"]["code"] == "bad_request"


def test_overview_works_read_only_and_reports_playback(dashboard):
    status, body = dashboard.call("/api/overview")
    data = body["data"]
    assert status == 200
    assert data["profile"] == "Kids" and data["write_enabled"] is False
    assert data["playback"] == {"active": False, "type": "", "title": ""}
    assert data["backups"]["count"] == 1 and data["backups"]["last"]["total_bytes"] == 2048
    assert data["rows"] == {"cached": 0, "failing": 0, "persistent": 0, "stale": 0, "empty": 0}
    assert data["protection"]["baseline"] is None and data["protection"]["fixes"]["healthy"] is None
    dashboard.replies["Player.GetActivePlayers"] = {"result": [{"playerid": 1, "type": "video"}]}
    dashboard.replies["Player.GetItem"] = {"result": {"item": {"type": "episode", "title": "The Pool", "showtitle": "Bluey"}}}
    data = dashboard.call("/api/overview")[1]["data"]
    assert data["playback"] == {"active": True, "type": "video", "title": "Bluey: The Pool", "media": "episode"}
    assert "Addons.GetAddons" not in dashboard.calls, "the overview never scans add-ons"


def test_connection_check_lists_each_service_for_the_charts():
    from kodi_manager.netwatch import Watchdog, latest_internet
    answers = {"api.torbox.app": 0.25, "api.trakt.tv": None, "api.themoviedb.org": 4.5}
    dog = Watchdog(lambda *a: None, lambda: True, probe=lambda host: answers[host], clock=lambda: NOW)
    result = dog.check_internet()
    assert result["hosts"] == [{"name": "TorBox", "seconds": 0.25}, {"name": "Trakt", "seconds": None}, {"name": "TMDb", "seconds": 4.5}]
    assert latest_internet()["hosts"] == result["hosts"]
    assert "timed out" in result["detail"], "the Health detail text is unchanged"


def test_account_checks_carry_days_left():
    from kodi_manager.account_health import torbox_status, trakt_status
    settings = {"trakt.token": "t", "trakt.expires": str(NOW + 5 * DAY + 10), "trakt_user": "", "tb.token": "x", "tb.enabled": "true"}
    trakt = trakt_status(lambda addon, key: settings.get(key, ""), now=NOW)
    assert trakt["days_left"] == 5 and trakt["renews"] is True and trakt["status"] == "ok"
    reply = {"success": True, "data": {"premium_expires_at": "2027-01-24T08:00:00Z"}}
    torbox = torbox_status(lambda addon, key: settings.get(key, ""), now=NOW, fetch=lambda token: reply)
    assert torbox["days_left"] == 9 and torbox["status"] == "warning"


def test_cached_row_status_offers_a_small_poster_preview(tmp_path):
    from kodi_manager.widget_cache import WidgetCache, preview_items
    files = [{"label": "[B]Bluey[/B]", "file": "x", "art": {"poster": "https://image.tmdb.org/t/p/w342/a.jpg"}},
             {"label": "Local", "file": "y", "art": {"poster": "file:///private/x.jpg"}},
             {"title": "No art", "file": "z"}] + [{"label": str(i), "file": str(i)} for i in range(10)]
    preview = preview_items(files)
    assert len(preview) == 6
    assert preview[0] == {"title": "Bluey", "poster": "https://image.tmdb.org/t/p/w342/a.jpg"}
    assert preview[1]["poster"] == "", "only HTTPS artwork is passed on"
    cache = WidgetCache(str(tmp_path))
    cache.save("plugin://plugin.video.pov/?mode=x", files[:1], now=NOW - 100)
    entry = cache.status(now=NOW)["entries"][0]
    assert entry["fetched_at"] == NOW - 100 and entry["preview"][0]["title"] == "Bluey"


def test_checkpoints_record_their_size(tmp_path, monkeypatch):
    from kodi_manager import backup
    root = tmp_path / "backups"
    live = tmp_path / "live"
    live.mkdir()
    (live / "settings.xml").write_bytes(b"x" * 300)
    monkeypatch.setattr(backup, "backup_root", lambda: str(root))
    manifest = backup.create_stack_backup([{"addon_id": "plugin.video.pov", "addon_data_path": str(live)}])
    assert manifest["total_bytes"] == 300


def test_a_sample_taken_before_the_clock_is_set_never_erases_the_history(tmp_path, monkeypatch):
    h = history(tmp_path)
    for i in range(96):  # a day of samples, every 15 minutes
        t = NOW - DAY + i * 900
        assert h.record({"t": t, "ma": 900}, now=t)
    boot = NOW - 300 * DAY  # the TV starts with its clock months behind, before it is set
    assert not h.record({"t": boot, "ma": 1500}, now=boot)
    assert len(h.load()) == 96
    assert h.series(7, now=NOW + 600)["count"] == 96
    assert h.record({"t": NOW + 900, "ma": 800}, now=NOW + 900)  # clock set: recording resumes
    assert len(h.load()) == 97


def test_history_from_a_clock_that_ran_ahead_is_replaced_after_hours(tmp_path, monkeypatch):
    h = history(tmp_path)
    for i in range(4):
        t = NOW + 10 * DAY + i * 900
        h.record({"t": t, "ma": 9}, now=t)
    ticks = [1000.0]
    monkeypatch.setattr(metrics.time, "monotonic", lambda: ticks[0])
    assert not h.record({"t": NOW, "ma": 1}, now=NOW)
    ticks[0] += MetricsHistory.BEHIND_GRACE
    assert h.record({"t": NOW + 900, "ma": 2}, now=NOW + 900)
    assert [s["ma"] for s in h.load()] == [2]

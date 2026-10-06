"""Regression tests for the 2026-10-05 review fixes."""
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "kodi_manager"))
import auth  # noqa: E402
import backup  # noqa: E402
import fix_protection  # noqa: E402
import pipeline  # noqa: E402
import service  # noqa: E402


class FakeAddon:
    def __init__(self):
        self.settings = {"auth_token": "existing-token"}

    def getSetting(self, key):
        return self.settings.get(key, "")

    def setSetting(self, key, value):
        self.settings[key] = value


def test_installer_seed_is_applied_once_and_user_changes_persist(tmp_path):
    (tmp_path / "installer_seed.json").write_text(json.dumps({"allow_lan": True, "host": "0.0.0.0", "port": 8765}))
    addon = FakeAddon()
    with patch.object(service, "translate", return_value=str(tmp_path)):
        first = service.load_config(addon)
        assert first["allow_lan"] is True and first["host"] == "0.0.0.0"
        result = tmp_path / "installer_result.json"
        assert json.loads(result.read_text())["auth_token"] == "existing-token"
        # The user switches LAN off and deletes the token handoff file.
        addon.setSetting("allow_lan", "false")
        addon.setSetting("host", "127.0.0.1")
        result.unlink()
        second = service.load_config(addon)
    assert second["allow_lan"] is False and second["host"] == "127.0.0.1"
    assert not result.exists()


def test_changed_installer_seed_is_applied_again(tmp_path):
    seed = tmp_path / "installer_seed.json"
    seed.write_text(json.dumps({"allow_lan": True, "port": 8765}))
    addon = FakeAddon()
    with patch.object(service, "translate", return_value=str(tmp_path)):
        service.load_config(addon)
        addon.setSetting("port", "9000")
        seed.write_text(json.dumps({"allow_lan": True, "port": 8766, "installer_nonce": "new"}))
        assert service.load_config(addon)["port"] == 8766


def test_allow_secret_replacement_setting_is_gone(tmp_path):
    with patch.object(service, "translate", return_value=str(tmp_path)):
        assert "allow_secret_replacement" not in service.load_config(FakeAddon())


@pytest.mark.parametrize("header", ["Bearer tökén", "Bearer \udcff", "Basic abc", "", None])
def test_auth_rejects_bad_headers_without_raising(header):
    assert auth.authorized(header, "real-token") is False


def test_auth_accepts_exact_token():
    assert auth.authorized("Bearer real-token", "real-token") is True


@pytest.fixture
def storage(tmp_path, monkeypatch):
    root = tmp_path / "backups"
    root.mkdir()
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(backup, "backup_root", lambda: str(root))
    backup.set_retention(20)
    yield root, live, {"addon_id": "plugin.video.pov", "addon_data_path": str(live)}
    backup.set_retention(20)


def test_retention_keeps_newest_snapshots(storage, monkeypatch):
    root, live, info = storage
    (live / "settings.xml").write_text("x")
    backup.set_retention(3)
    stamps = iter("20260101-12000%d" % i for i in range(6))
    monkeypatch.setattr(backup.time, "strftime", lambda *_: next(stamps))
    ids = [backup.create_backup(info)["backup_id"] for _ in range(6)]
    kept = sorted(os.listdir(root / info["addon_id"]))
    assert kept == sorted(ids[-3:])


def test_restore_removes_files_created_after_the_snapshot(storage):
    root, live, info = storage
    (live / "settings.xml").write_text("original")
    snap = backup.create_backup(info)
    (live / "settings.xml").write_text("changed")
    (live / "new.db").write_text("later")
    (live / "cache").mkdir()
    (live / "cache" / "x").write_text("later")
    backup.restore_backup(info, snap["backup_id"])
    assert sorted(p.name for p in live.iterdir()) == ["settings.xml"]
    assert (live / "settings.xml").read_text() == "original"


def test_self_snapshot_skips_and_preserves_backup_store(tmp_path, monkeypatch):
    data = tmp_path / "service.kodi.addonadmin"
    store = data / "backups"
    store.mkdir(parents=True)
    (data / "settings.xml").write_text("original")
    monkeypatch.setattr(backup, "backup_root", lambda: str(store))
    info = {"addon_id": backup.SELF_ID, "addon_data_path": str(data)}
    snap = backup.create_backup(info)
    copied = store / backup.SELF_ID / snap["backup_id"] / "addon_data"
    assert (copied / "settings.xml").exists() and not (copied / "backups").exists()
    (data / "settings.xml").write_text("changed")
    backup.restore_backup(info, snap["backup_id"])
    assert (data / "settings.xml").read_text() == "original"
    assert (store / backup.SELF_ID / snap["backup_id"]).is_dir()


def test_stack_restore_uses_default_path_when_index_has_none(storage, monkeypatch, tmp_path):
    root, live, info = storage
    (live / "settings.xml").write_text("original")
    stack = backup.create_stack_backup([info])
    pathless = {"addon_id": info["addon_id"], "addon_data_path": None}
    target = tmp_path / "default"
    monkeypatch.setattr(backup, "translate", lambda _: str(target))
    result = backup.restore_stack_backup(SimpleNamespace(get=lambda aid: pathless), stack["backup_id"])
    assert result["restored"] == [info["addon_id"]]
    assert (target / "settings.xml").read_text() == "original"


def test_switch_player_takes_no_snapshot(monkeypatch):
    index = SimpleNamespace(get=lambda aid: {"addon_id": aid, "installed": True})
    called = []
    monkeypatch.setattr(pipeline, "pipeline_backup", lambda *a, **k: called.append(1))
    result = pipeline.switch_player(object(), index, "plugin.video.pov", write_enabled=True)
    assert result["supported"] is False and result["backup_id"] is None and not called


def test_two_fix_repairs_in_one_second_do_not_collide(tmp_path, monkeypatch):
    addon = tmp_path / "addons" / "plugin.test"
    addon.mkdir(parents=True)
    (addon / "addon.xml").write_text('<addon version="1.0"/>')
    live = addon / "code.py"
    bundle = tmp_path / "bundle"
    (bundle / "files/plugin.test").mkdir(parents=True)
    (bundle / "files/plugin.test/code.py").write_text("patched")
    live.write_text("original")
    entry = {"path": "plugin.test/code.py", "sha256": fix_protection.digest(bundle / "files/plugin.test/code.py"),
             "restore_from": [fix_protection.digest(live)]}
    (bundle / "manifest.json").write_text(json.dumps({"groups": [{"id": "t", "label": "Fix", "addon_id": "plugin.test", "version": "1.0", "files": [entry]}]}))
    monkeypatch.setattr(fix_protection.time, "strftime", lambda *_: "20260101-120000")
    protection = fix_protection.FixProtection(tmp_path / "addons", tmp_path / "fix_backups", bundle)
    first = protection.repair()["backup"]
    live.write_text("original")
    second = protection.repair()["backup"]
    assert first != second and live.read_text() == "patched"

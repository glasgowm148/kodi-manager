import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kodi_manager import backup, fsutil, portable_api, skin_layout
from kodi_manager import tvos_storage as storage


@pytest.fixture
def tvos(tmp_path, monkeypatch):
    root = tmp_path / "userdata"
    root.mkdir()
    values = {}
    fail = {"write": False, "read": False}

    class File:
        def __init__(self, path, mode="r"):
            self.path, self.mode = path, mode

        def readBytes(self, limit):
            if fail["read"]:
                raise OSError("Synthetic VFS failure")
            return values[self.path][:limit]

        def write(self, data):
            values[self.path] = bytes(data)
            if fail["write"]:
                fail["write"] = False
                return False
            return True

        def close(self):
            pass

    def listing(path):
        folder = Path(path)
        dirs = [p.name for p in folder.iterdir() if p.is_dir()]
        files = [p.name for p in folder.iterdir() if p.is_file()]
        files += [Path(p).name for p in values if Path(p).parent == folder]
        return dirs, files

    def delete(path):
        values.pop(path, None)
        return True

    vfs = SimpleNamespace(File=File, translatePath=lambda path: str(root),
                          exists=lambda path: path in values, listdir=listing, delete=delete)
    monkeypatch.setattr(storage, "xbmcvfs", vfs)
    monkeypatch.setattr(storage, "is_tvos", lambda: True)
    monkeypatch.setattr(storage, "application_active", lambda: True)
    monkeypatch.setattr(backup, "backup_root", lambda: str(root / "backups"))
    (root / "backups").mkdir()
    return root, values, fail


def test_virtual_settings_win_over_stale_physical_shadow(tvos):
    root, values, _fail = tvos
    path = root / "settings.xml"
    path.write_bytes(b"stale physical")
    values[str(path)] = b"actual Kodi setting"
    assert skin_layout._read(str(path)) == b"actual Kodi setting"
    fsutil.atomic_write_bytes(str(path), b"updated")
    assert storage.read_bytes(path) == b"updated"
    assert path.read_bytes() == b"stale physical"
    storage.remove(path)
    assert not path.exists() and str(path) not in values


def test_failed_virtual_write_rolls_back_original(tvos):
    root, values, fail = tvos
    path = root / "settings.xml"
    values[str(path)] = b"original"
    fail["write"] = True
    with pytest.raises(OSError, match="write failed"):
        fsutil.atomic_write_bytes(str(path), b"candidate")
    assert values[str(path)] == b"original"


def test_virtual_read_failure_never_falls_back_to_shadow(tvos):
    root, values, fail = tvos
    path = root / "settings.xml"
    path.write_bytes(b"stale")
    values[str(path)] = b"actual"
    fail["read"] = True
    with pytest.raises(OSError):
        storage.read_bytes(path)
    from kodi_manager import kodi_api
    with pytest.raises(OSError):
        kodi_api.read_text(str(path))


def test_virtual_backup_restore_undo_and_prune(tvos):
    root, values, _fail = tvos
    live = root / "addon_data/plugin.video.example"
    live.mkdir(parents=True)
    path = str(live / "settings.xml")
    values[path] = b"original"
    addon = {"addon_id": "plugin.video.example", "addon_data_path": str(live)}
    snapshot = backup.create_backup(addon)
    assert snapshot["files_copied"] == 1
    values[path] = b"current"
    restored = backup.restore_backup(addon, snapshot["backup_id"])
    assert values[path] == b"original"
    backup.restore_backup(addon, restored["undo_backup_id"])
    assert values[path] == b"current"
    target = root / "backups/plugin.video.example" / snapshot["backup_id"]
    storage.rmtree(target)
    assert not any(p.startswith(str(target) + os.sep) for p in values)


@pytest.mark.parametrize("active", [False, None])
def test_inactive_or_unreadable_kodi_blocks_layout_before_work(tvos, monkeypatch, active):
    monkeypatch.setattr(storage, "application_active", lambda: active)
    with pytest.raises(ValueError, match="not confirmed active"):
        skin_layout.apply_layout(None, None, {}, True)


def test_native_getter_failure_is_unknown(monkeypatch):
    monkeypatch.setattr(storage, "is_tvos", lambda: True)
    import ctypes
    monkeypatch.setattr(ctypes, "CDLL", lambda *args: (_ for _ in ()).throw(OSError()))
    assert storage.application_active() is None


@pytest.mark.parametrize("active", [False, None])
def test_background_work_defers_when_tvos_focus_is_not_active(tvos, monkeypatch, active):
    from kodi_manager import service_workers
    monkeypatch.setattr(storage, "application_active", lambda: active)
    assert service_workers.tv_busy() is True


def test_portable_read_confined_to_active_profile_and_text(tvos, monkeypatch):
    root, _values, _fail = tvos
    profile = root / "profiles/Kids"
    profile.mkdir(parents=True)
    addons = root.parent / "addons"
    addons.mkdir()
    mapping = {"special://masterprofile/": str(root), "special://profile/": str(profile), "special://home/addons/": str(addons)}
    monkeypatch.setattr(portable_api, "translate", mapping.__getitem__)
    assert portable_api.profile_root() == "userdata/profiles/Kids"
    assert portable_api.file_path("userdata/profiles/Kids/guisettings.xml") == str(profile / "guisettings.xml")
    for path in ["userdata/guisettings.xml", "userdata/profiles/Adults/guisettings.xml", "addons/../secret.xml", "addons/foo/script.py", "/etc/passwd", "addons/foo//addon.xml"]:
        with pytest.raises(ValueError):
            portable_api.file_path(path)
    link = profile / "link"
    try:
        link.symlink_to(root.parent)
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError):
        portable_api.file_path("userdata/profiles/Kids/link/outside.xml")


def test_manager_identity_stable_across_profiles_and_corruption_refused(tvos, monkeypatch):
    root, values, _fail = tvos
    path = str(root / "addon_data/service.kodi.addonadmin/device_identity.xml")
    monkeypatch.setattr(portable_api, "translate", lambda _: path)
    first = portable_api.device_identity()
    assert portable_api.device_identity() == first
    values[path] = b"<device id='corrupt'/>"
    with pytest.raises(ValueError, match="identity"):
        portable_api.device_identity()


def test_master_profile_does_not_allow_reads_from_another_profile(tvos, monkeypatch):
    root, _values, _fail = tvos
    monkeypatch.setattr(portable_api, "translate", lambda _: str(root))
    with pytest.raises(ValueError, match="active Kodi profile"):
        portable_api.file_path("userdata/profiles/Kids/guisettings.xml")


def test_pipeline_file_snapshot_and_size_use_virtual_contents(tvos):
    root, values, _fail = tvos
    path = root / "guisettings.xml"
    values[str(path)] = b"persistent virtual configuration"
    snapshot = backup.create_file_backup("pipeline", {"core/guisettings.xml": str(path)})
    saved = root / "backups/pipeline" / snapshot["backup_id"] / "core/guisettings.xml"
    assert snapshot["included_files"] == ["core/guisettings.xml"]
    assert storage.read_bytes(saved) == values[str(path)]
    assert storage.size(saved) == len(values[str(path)])


def test_restoring_manager_cannot_replace_live_access_or_identity(tvos):
    root, values, _fail = tvos
    live = root / "addon_data" / backup.SELF_ID
    live.mkdir(parents=True)
    identity, settings = str(live / "device_identity.xml"), str(live / "settings.xml")
    values.update({identity: b"original identity", settings: b"old private access"})
    addon = {"addon_id": backup.SELF_ID, "addon_data_path": str(live)}
    snapshot = backup.create_backup(addon)
    values.update({identity: b"live identity", settings: b"current private access"})
    backup.restore_backup(addon, snapshot["backup_id"])
    assert values[identity] == b"live identity"
    assert values[settings] == b"current private access"


def test_virtual_widget_conversion_retains_real_original_backup(tvos):
    from kodi_manager import widget_autocache
    root, values, _fail = tvos
    folder = root / "addon_data/script.skinshortcuts"
    folder.mkdir(parents=True)
    name = "skin.bingie-moviehub.DATA.xml"
    path = str(folder / name)
    original = b'<shortcuts><shortcut><action>ActivateWindow(Videos,plugin://plugin.video.pov/?mode=build_movie_list,return)</action></shortcut></shortcuts>'
    values[path] = original
    changed = widget_autocache.autocache(str(folder), now=0)
    assert changed == {name: 1}
    assert b"plugin://service.kodi.addonadmin" in values[path]
    snapshots = [v for p, v in values.items() if "kodi-manager-backups" in p]
    assert snapshots == [original]


def test_pipeline_player_discovery_includes_virtual_xml(tvos):
    from kodi_manager import pipeline
    root, values, _fail = tvos
    data = root / "addon_data/plugin.video.tmdb.helper"
    (data / "players").mkdir(parents=True)
    values[str(data / "players/custom.xml")] = b"plugin.video.pov"
    result = pipeline._player_files({"addon_data_path": str(data)})
    assert result["files"][0]["filename"] == "custom.xml"
    assert "plugin.video.pov" in result["refs"][0]["refs"]


def test_missing_target_symlink_is_not_an_optional_shortcut(tvos):
    root, _values, _fail = tvos
    path = root / "shortcut.xml"
    try:
        path.symlink_to(root / "missing.xml")
    except OSError:
        pytest.skip("Symlinks unavailable")
    with pytest.raises(ValueError, match="symlinks"):
        skin_layout._read(str(path), optional=True)

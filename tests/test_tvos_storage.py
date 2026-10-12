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

        def size(self):
            return len(values[self.path])

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

    vfs = SimpleNamespace(File=File, Stat=lambda path: SimpleNamespace(st_size=lambda: len(values[path])),
                          translatePath=lambda path: str(root),
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


@pytest.mark.parametrize("name", ["customcontroller.SiriRemote.xml", "CustomController.SIRIREMOTE.alt.xml"])
def test_siri_remote_xml_uses_physical_storage_and_backup(tvos, name):
    root, values, _fail = tvos
    path = root / name
    path.write_bytes(b"original")
    assert not storage.virtual_xml(path)
    assert storage.read_bytes(path) == b"original"
    fsutil.atomic_write_bytes(str(path), b"updated")
    snapshot = root / "backups" / name
    backup._copy_file(str(path), str(snapshot))
    assert path.read_bytes() == snapshot.read_bytes() == b"updated"
    assert str(path) not in values and str(snapshot) not in values
    storage.remove(path)
    assert not path.exists()


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


def test_backup_path_alias_keeps_xml_in_virtual_storage(tvos, monkeypatch):
    root, values, _fail = tvos
    alias = root.parent / "userdata-alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable")
    monkeypatch.setattr(storage.xbmcvfs, "translatePath", lambda _: str(alias))
    monkeypatch.setattr(backup, "backup_root", lambda: str(alias / "backups"))
    live = alias / "addon_data/plugin.video.example"
    live.mkdir(parents=True)
    path = str(live / "settings.xml")
    values[path] = b"original"
    addon = {"addon_id": "plugin.video.example", "addon_data_path": str(live)}
    snapshot = backup.create_backup(addon)
    stored = os.path.join(backup._backup_path(addon["addon_id"], snapshot["backup_id"]), "addon_data", "settings.xml")
    assert storage.virtual_xml(stored) and values[stored] == b"original"
    assert not os.path.exists(stored)
    values[path] = b"current"
    result = backup.restore_backup(addon, snapshot["backup_id"])
    assert values[path] == b"original"
    backup.restore_backup(addon, result["undo_backup_id"])
    assert values[path] == b"current"


def test_missing_virtual_backup_key_refuses_physical_shadow(tvos):
    root, values, _fail = tvos
    live = root / "addon_data/plugin.video.example"
    live.mkdir(parents=True)
    path = str(live / "settings.xml")
    values[path] = b"snapshot"
    addon = {"addon_id": "plugin.video.example", "addon_data_path": str(live)}
    snapshot = backup.create_backup(addon)
    stored = os.path.join(backup._backup_path(addon["addon_id"], snapshot["backup_id"]), "addon_data", "settings.xml")
    del values[stored]
    Path(stored).write_bytes(b"physical shadow")
    values[path] = b"current"
    with pytest.raises(ValueError, match="incomplete"):
        backup.restore_backup(addon, snapshot["backup_id"])
    assert values[path] == b"current" and Path(stored).read_bytes() == b"physical shadow"


@pytest.mark.parametrize("kind", ["addon", "stack"])
@pytest.mark.parametrize("virtual", [False, True])
def test_failed_self_restore_preserves_access_changes_after_undo_snapshot(tvos, monkeypatch, kind, virtual):
    root, values, _fail = tvos
    monkeypatch.setattr(storage, "is_tvos", lambda: virtual)
    live = root / "addon_data" / backup.SELF_ID
    live.mkdir(parents=True)
    settings, identity, content = [str(live / name) for name in ("settings.xml", "device_identity.xml", "content.xml")]

    def put(items):
        for path, data in items.items():
            if virtual:
                values[path] = data
            else:
                Path(path).write_bytes(data)

    put({settings: b"snapshot access", identity: b"snapshot owner", content: b"snapshot content"})
    addon = {"addon_id": backup.SELF_ID, "addon_data_path": str(live)}
    index = SimpleNamespace(get=lambda aid: addon if aid == backup.SELF_ID else None)
    snapshot = backup.create_backup(addon) if kind == "addon" else backup.create_stack_backup([addon])
    put({settings: b"access at undo", identity: b"live owner", content: b"live content"})
    original, attempts = backup._restore_folder, []

    def interrupted(*args):
        attempts.append(True)
        original(*args)
        if len(attempts) == 1:
            # Kodi's settings UI can rotate access while restoration is in flight.
            put({settings: b"new access after undo"})
            raise OSError("synthetic restore failure")

    monkeypatch.setattr(backup, "_restore_folder", interrupted)
    with pytest.raises(OSError, match="synthetic restore failure"):
        if kind == "addon":
            backup.restore_backup(addon, snapshot["backup_id"])
        else:
            backup.restore_stack_backup(index, snapshot["backup_id"])
    assert storage.read_bytes(settings) == b"new access after undo"
    assert storage.read_bytes(identity) == b"live owner" and storage.read_bytes(content) == b"live content"


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


def test_silent_partial_vfs_read_is_not_backed_up(tvos, monkeypatch):
    root, values, _fail = tvos
    live = root / "addon_data/plugin.video.example"
    live.mkdir(parents=True)
    values[str(live / "settings.xml")] = b"complete original XML"
    original = storage.xbmcvfs.File

    class PartialFile(original):
        def readBytes(self, limit):
            return super().readBytes(limit)[:4]

    monkeypatch.setattr(storage.xbmcvfs, "File", PartialFile)
    with pytest.raises(OSError, match="incomplete"):
        backup.create_backup({"addon_id": "plugin.video.example", "addon_data_path": str(live)})
    assert values[str(live / "settings.xml")] == b"complete original XML"
    assert not list((root / "backups").rglob("manifest.json"))


@pytest.mark.parametrize("candidate", [b"", b"x" * 2_000_001])
def test_invalid_virtual_write_is_refused_before_mutation(tvos, candidate):
    root, values, _fail = tvos
    path = str(root / "settings.xml")
    values[path] = b"original"
    with pytest.raises(ValueError, match="size limit"):
        fsutil.atomic_write_bytes(path, candidate)
    assert values[path] == b"original"


def test_missing_tvos_directory_cannot_create_false_empty_backup(tvos):
    root, values, _fail = tvos
    live = root / "addon_data/plugin.video.example"
    values[str(live / "settings.xml")] = b"persistent XML after cache purge"
    with pytest.raises(ValueError, match="cannot be enumerated"):
        backup.create_backup({"addon_id": "plugin.video.example", "addon_data_path": str(live)})
    assert values[str(live / "settings.xml")] == b"persistent XML after cache purge"


def test_self_restore_never_transiently_changes_live_owner(tvos, monkeypatch):
    root, values, _fail = tvos
    live = root / "addon_data" / backup.SELF_ID
    live.mkdir(parents=True)
    identity, settings = str(live / "device_identity.xml"), str(live / "settings.xml")
    values.update({identity: b"old identity", settings: b"old token", str(live / "other.xml"): b"original"})
    addon = {"addon_id": backup.SELF_ID, "addon_data_path": str(live)}
    snapshot = backup.create_backup(addon)
    values.update({identity: b"current identity", settings: b"current token"})
    original = backup._copy_file

    def observed(src, dst):
        assert values[identity] == b"current identity" and values[settings] == b"current token"
        assert dst not in (identity, settings)
        original(src, dst)

    monkeypatch.setattr(backup, "_copy_file", observed)
    backup.restore_backup(addon, snapshot["backup_id"])
    assert values[identity] == b"current identity" and values[settings] == b"current token"


def test_master_profile_blocks_nonstandard_other_profile_directory(tvos, monkeypatch):
    root, values, _fail = tvos
    values[str(root / "profiles.xml")] = b"<profiles><profile><directory pathversion='1'>Kids/</directory></profile></profiles>"
    monkeypatch.setattr(portable_api, "translate", lambda _: str(root))
    with pytest.raises(ValueError, match="active Kodi profile"):
        portable_api.file_path("userdata/Kids/guisettings.xml")


@pytest.mark.parametrize("active", ["Adults", "Adults/Kids"])
def test_nested_profiles_cannot_read_each_other(tvos, monkeypatch, active):
    root, values, _fail = tvos
    (root / "Adults/Kids").mkdir(parents=True)
    values[str(root / "profiles.xml")] = (
        b"<profiles><profile><directory>special://masterprofile/</directory></profile>"
        b"<profile><directory>Adults/</directory></profile>"
        b"<profile><directory>Adults/Kids/</directory></profile></profiles>"
    )
    mapping = {"special://masterprofile/": str(root), "special://profile/": str(root / active)}
    monkeypatch.setattr(portable_api, "translate", mapping.__getitem__)
    assert portable_api.file_path("userdata/" + active + "/settings.json") == str(root / active / "settings.json")
    other = "Adults/Kids" if active == "Adults" else "Adults"
    with pytest.raises(ValueError, match="active"):
        portable_api.file_path("userdata/" + other + "/settings.json")


def test_profile_boundaries_keep_translated_vfs_path_alias(tvos, monkeypatch):
    root, values, _fail = tvos
    alias = root.parent / "userdata-alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable")
    (root / "Adults/Kids").mkdir(parents=True)
    values[str(alias / "profiles.xml")] = b"<profiles><profile><directory>Adults/Kids/</directory></profile></profiles>"
    mapping = {"special://masterprofile/": str(alias), "special://profile/": str(alias / "Adults")}
    monkeypatch.setattr(portable_api, "translate", mapping.__getitem__)
    monkeypatch.setattr(storage.xbmcvfs, "translatePath", lambda _: str(alias))
    with pytest.raises(ValueError, match="active Kodi profile"):
        portable_api.file_path("userdata/Adults/Kids/settings.json")


def test_file_path_uses_captured_profile_when_special_path_changes(tvos, monkeypatch):
    root, _values, _fail = tvos
    first, second = root / "profiles/A", root / "profiles/B"
    first.mkdir(parents=True)
    second.mkdir()
    calls = []

    def translate(path):
        if path == "special://profile/":
            calls.append(path)
            return str(first if len(calls) == 1 else second)
        return str(root)

    monkeypatch.setattr(portable_api, "translate", translate)
    assert portable_api.file_path("userdata/profiles/A/guisettings.xml") == str(first / "guisettings.xml")
    assert len(calls) == 1


def test_missing_virtual_file_never_reports_empty_success(tvos, monkeypatch):
    root, _values, _fail = tvos

    def unopened(*args):
        pytest.fail("A missing key must be refused before opening")

    monkeypatch.setattr(storage.xbmcvfs, "File", unopened)
    with pytest.raises(FileNotFoundError):
        storage.read_bytes(root / "missing.xml")


def test_failed_native_open_cannot_mask_existing_virtual_contents(tvos, monkeypatch):
    root, values, _fail = tvos
    path = root / "settings.xml"
    values[str(path)] = b"original contents"
    original = storage.xbmcvfs.File

    class FailedOpen(original):
        def size(self):
            return 0  # The real Python wrapper does not raise when Open returns false.

        def readBytes(self, limit):
            return b""

    monkeypatch.setattr(storage.xbmcvfs, "File", FailedOpen)
    with pytest.raises(OSError, match="length is unreadable"):
        fsutil.atomic_write_bytes(str(path), b"candidate")
    assert values[str(path)] == b"original contents"


def test_parent_traversal_handles_windows_short_path_aliases(monkeypatch):
    import ntpath
    path_api = SimpleNamespace(dirname=ntpath.dirname, normcase=ntpath.normcase, normpath=ntpath.normpath,
                               realpath=lambda p: p.replace('RUNNER~1', 'runneradmin'))
    monkeypatch.setattr(portable_api, 'os', SimpleNamespace(path=path_api))
    source = r'C:\Users\RUNNER~1\Kodi\settings.xml'
    assert list(portable_api._parents(source, r'C:\Users\runneradmin\Kodi')) == [source, ntpath.dirname(source)]


def test_parent_traversal_cannot_loop_above_missing_boundary(tmp_path):
    from itertools import islice
    with pytest.raises(ValueError, match='leaves its directory'):
        list(islice(portable_api._parents(str(tmp_path / 'settings.xml'), str(tmp_path / 'unrelated')), 100))


@pytest.mark.parametrize('directory,requested', [('profiles/Kids', 'userdata/Profiles/Kids/settings.json'), ('Kids', 'userdata/kIDS/guisettings.xml')])
def test_other_profile_directory_case_alias_is_refused(tvos, monkeypatch, directory, requested):
    root, values, _fail = tvos
    values[str(root / 'profiles.xml')] = ('<profiles><profile><directory>%s</directory></profile></profiles>' % directory).encode()
    monkeypatch.setattr(portable_api, 'translate', lambda _: str(root))
    with pytest.raises(ValueError, match='active Kodi profile'):
        portable_api.file_path(requested)

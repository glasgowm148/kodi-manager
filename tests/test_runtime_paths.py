"""Kodi hands out ``special://`` paths: everything that touches files must use real ones."""
import os
import types

import pytest

from kodi_manager import addon_index, backup, kodi_api, path_probe
from kodi_manager.pipeline import pipeline_backup

POV = "plugin.video.pov"


@pytest.fixture
def kodi_fs(tmp_path, monkeypatch):
    """A fake xbmcvfs whose listdir/exists accept special:// paths, as Kodi's do."""
    roots = {"special://profile/": tmp_path / "home/userdata/profiles/Kids",
             "special://masterprofile/": tmp_path / "home/userdata",
             "special://home/": tmp_path / "home", "special://xbmc/": tmp_path / "xbmc"}
    for folder in roots.values():
        folder.mkdir(parents=True, exist_ok=True)

    def translate(path):
        for prefix, real in roots.items():
            if path.startswith(prefix):
                return os.path.join(str(real), path[len(prefix):])
        return path

    def listdir(path):
        real = translate(path)
        names = os.listdir(real)
        return ([n for n in names if os.path.isdir(os.path.join(real, n))],
                [n for n in names if not os.path.isdir(os.path.join(real, n))])

    fake = types.SimpleNamespace(translatePath=translate, listdir=listdir,
                                 exists=lambda p: os.path.exists(translate(p)))
    monkeypatch.setattr(path_probe, "xbmcvfs", fake)
    monkeypatch.setattr(kodi_api, "xbmcvfs", fake)
    monkeypatch.setattr(path_probe, "ANDROID_KODI_ROOTS", [])
    monkeypatch.chdir(tmp_path)
    return tmp_path, roots


class _Kodi:
    installer_seed = {}

    def list_addons(self):
        return []

    def get_addon_details(self, aid):
        return {}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def test_backups_copy_and_restore_real_files_when_kodi_lists_special_paths(kodi_fs):
    tmp, roots = kodi_fs
    live = roots["special://profile/"] / "addon_data" / POV
    _write(live / "settings.xml", b"original")
    _write(roots["special://profile/"] / "addon_data/skin.bingie/settings.xml", b"skin")
    index = addon_index.AddonIndex(_Kodi())
    pov = index.get(POV)
    assert os.path.normpath(pov["addon_data_path"]) == os.path.normpath(str(live))
    single = backup.create_backup(pov)
    assert single["files_copied"] == 1
    stack = backup.create_stack_backup([pov])
    assert stack["included_folders"] == [POV] and stack["file_counts"] == {POV: 1}
    assert POV in pipeline_backup(index)["included_components"]
    (live / "settings.xml").write_bytes(b"changed")
    backup.restore_backup(pov, single["backup_id"])
    assert (live / "settings.xml").read_bytes() == b"original"
    (live / "settings.xml").write_bytes(b"changed")
    backup.restore_stack_backup(index, stack["backup_id"])
    assert (live / "settings.xml").read_bytes() == b"original"
    assert not (tmp / "special:").exists()


def test_backup_functions_translate_a_special_path_they_are_given(kodi_fs):
    tmp, roots = kodi_fs
    live = roots["special://profile/"] / "addon_data" / POV
    _write(live / "settings.xml", b"original")
    info = {"addon_id": POV, "addon_data_path": "special://profile/addon_data/" + POV}
    single = backup.create_backup(info)
    assert single["files_copied"] == 1
    assert backup.create_stack_backup([info])["included_folders"] == [POV]
    index = types.SimpleNamespace(get=lambda aid: info if aid == POV else None)
    assert POV in pipeline_backup(index)["included_components"]
    (live / "settings.xml").write_bytes(b"changed")
    backup.restore_backup(info, single["backup_id"])
    assert (live / "settings.xml").read_bytes() == b"original"
    assert not (tmp / "special:").exists()


def test_a_sparse_profile_never_resolves_addon_data_to_the_master_profile(kodi_fs):
    tmp, roots = kodi_fs
    # The master profile holds every expected add-on; the active profile only POV.
    for aid in path_probe.EXPECTED_ADDON_DATA_IDS:
        _write(roots["special://masterprofile/"] / "addon_data" / aid / "settings.xml", b"master")
    _write(roots["special://profile/"] / "addon_data" / POV / "settings.xml", b"kids")
    index = addon_index.AddonIndex(_Kodi())
    assert os.path.normpath(index.get(POV)["addon_data_path"]) == os.path.normpath(str(roots["special://profile/"] / "addon_data" / POV))
    # Add-ons with data only in the master profile are not attributed to this profile.
    assert index.get("skin.bingie") is None

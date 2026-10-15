"""Published package integrity, Kodi repository layout, and update selection."""

import hashlib
import importlib.util
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("build_repository", ROOT / "scripts/build_repository.py")
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)


def release(tmp_path, metadata=None, extra=None):
    addon = tmp_path / "service.kodi.addonadmin-0.7.37.zip"
    with ZipFile(addon, "w") as archive:
        archive.writestr("service.kodi.addonadmin/addon.xml", metadata or (
            '<addon id="service.kodi.addonadmin" version="0.7.37">'
            '<extension point="xbmc.addon.metadata"><assets>'
            '<icon>resources/icon.png</icon></assets></extension></addon>'
        ))
        archive.writestr("service.kodi.addonadmin/resources/icon.png", b"synthetic-icon")
        if extra:
            archive.writestr(extra, b"invalid")
    checksum = tmp_path / "SHA256SUMS"
    checksum.write_text(hashlib.sha256(addon.read_bytes()).hexdigest() + "  " + addon.name + "\n")
    return addon, checksum


def test_kodi_can_resolve_every_package_and_asset(tmp_path):
    addon, checksums = release(tmp_path)
    output = repo.build(addon, checksums, tmp_path / "site")
    xml = (output / "addons.xml").read_bytes()
    assert (output / "addons.xml.sha256").read_text().strip() == hashlib.sha256(xml).hexdigest()
    for metadata in ET.fromstring(xml):
        package = output / metadata.attrib["id"] / (
            metadata.attrib["id"] + "-" + metadata.attrib["version"] + ".zip"
        )
        with ZipFile(package) as archive:
            packaged = ET.fromstring(archive.read(metadata.attrib["id"] + "/addon.xml"))
            assert packaged.attrib == metadata.attrib
        for asset in metadata.findall("./extension[@point='xbmc.addon.metadata']/assets/*"):
            assert (output / metadata.attrib["id"] / asset.text).is_file()
    assert (output / repo.SERVICE_ID / addon.name).read_bytes() == addon.read_bytes()
    installer = output / "repository.kodi-manager.zip"
    assert installer.read_bytes() == (output / repo.REPO_ID / "repository.kodi-manager-1.0.0.zip").read_bytes()
    assert 'href="repository.kodi-manager.zip"' in (output / "index.html").read_text()
    with ZipFile(installer) as archive:
        metadata = ET.fromstring(archive.read(repo.REPO_ID + "/addon.xml"))
    directory = metadata.find("./extension[@point='xbmc.addon.repository']/dir")
    base = directory.findtext("datadir")
    assert directory.attrib["minversion"] == "19.0.0"
    assert directory.findtext("info") == base + "addons.xml"
    assert directory.findtext("checksum") == base + "addons.xml.sha256"
    assert base.startswith("https://")
    second = repo.build(addon, checksums, tmp_path / "second")
    assert installer.read_bytes() == (second / installer.name).read_bytes()


@pytest.mark.parametrize("content", ["", "0" * 64 + "  service.kodi.addonadmin-0.7.37.zip\n"])
def test_refuse_missing_or_changed_checksum(tmp_path, content):
    addon, checksums = release(tmp_path)
    checksums.write_text(content)
    with pytest.raises(ValueError, match="checksum"):
        repo.build(addon, checksums, tmp_path / "site")
    assert not (tmp_path / "site").exists()


def test_refuse_duplicate_checksum(tmp_path):
    addon, checksums = release(tmp_path)
    checksums.write_text(checksums.read_text() * 2)
    with pytest.raises(ValueError, match="checksum"):
        repo.build(addon, checksums, tmp_path / "site")


@pytest.mark.parametrize("metadata,extra", [
    ('<addon id="other" version="0.7.37"/>', None),
    ('<addon id="service.kodi.addonadmin" version="0.7.36"/>', None),
    (None, "service.kodi.addonadmin/../unexpected"),
    (None, "other/file"),
])
def test_refuse_wrong_release_or_paths(tmp_path, metadata, extra):
    addon, checksums = release(tmp_path, metadata, extra)
    with pytest.raises(ValueError):
        repo.build(addon, checksums, tmp_path / "site")


def test_refuse_stale_output(tmp_path):
    addon, checksums = release(tmp_path)
    site = tmp_path / "site"
    site.mkdir()
    (site / "old-package.zip").touch()
    with pytest.raises(ValueError, match="empty"):
        repo.build(addon, checksums, site)


def test_newest_published_version_not_release_date_or_event_order():
    assert repo.latest_release([
        {"tag_name": "v0.7.9"}, {"tag_name": "v0.7.37", "prerelease": True},
        {"tag_name": "v0.8.0", "draft": True}, {"tag_name": "v0.7.36"},
        {"tag_name": "unrelated-tag"},
    ]) == "v0.7.37"
    with pytest.raises(ValueError, match="No published"):
        repo.latest_release([])


def test_previous_cached_index_can_still_download_its_package(tmp_path):
    addon, checksums = release(tmp_path)
    older = tmp_path / "v0.7.36"
    older.mkdir()
    package = older / "service.kodi.addonadmin-0.7.36.zip"
    with ZipFile(package, "w") as archive:
        archive.writestr("service.kodi.addonadmin/addon.xml",
                         '<addon id="service.kodi.addonadmin" version="0.7.36"/>')
    (older / "SHA256SUMS").write_text(hashlib.sha256(package.read_bytes()).hexdigest() + "  " + package.name)
    site = repo.build(addon, checksums, tmp_path / "site", [older])
    assert (site / repo.SERVICE_ID / package.name).read_bytes() == package.read_bytes()
    metadata = ET.parse(site / "addons.xml").find("./addon[@id='service.kodi.addonadmin']")
    assert metadata.attrib["version"] == "0.7.37"
    (older / "SHA256SUMS").write_text("invalid")
    with pytest.raises(ValueError, match="checksum"):
        repo.build(addon, checksums, tmp_path / "second", [older])

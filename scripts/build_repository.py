"""Build a Kodi repository from a checksum-verified, already published service ZIP."""

import argparse
import hashlib
import re
import shutil
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
SERVICE_ID = "service.kodi.addonadmin"
REPO_ID = "repository.kodi-manager"


def latest_release(releases):
    """Include previews, exclude drafts, and never let an older release event downgrade users."""
    candidates = []
    for release in releases:
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", release["tag_name"])
        if match and not release.get("draft"):
            candidates.append((tuple(map(int, match.groups())), release["tag_name"]))
    if not candidates:
        raise ValueError("No published Kodi Manager release")
    return max(candidates)[1]


def write_zip(target, entries):
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for name, data in sorted(entries.items()):
            info = ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)


def read_release(addon, checksums):
    addon, checksums = Path(addon), Path(checksums)
    entries = [line.split() for line in checksums.read_text().splitlines() if line.strip()]
    matches = [parts[0] for parts in entries if len(parts) == 2 and parts[1] == addon.name]
    if len(matches) != 1 or hashlib.sha256(addon.read_bytes()).hexdigest() != matches[0]:
        raise ValueError("Missing, duplicate or mismatched release checksum")
    with ZipFile(addon) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            not name.startswith(SERVICE_ID + "/") or ".." in PurePosixPath(name).parts
            or "\\" in name for name in names
        ):
            raise ValueError("Unexpected service ZIP layout")
        service = ET.fromstring(archive.read(SERVICE_ID + "/addon.xml"))
        version = service.get("version", "")
        if (service.tag != "addon" or service.get("id") != SERVICE_ID
                or not re.fullmatch(r"\d+\.\d+\.\d+", version)
                or addon.name != SERVICE_ID + "-" + version + ".zip"):
            raise ValueError("Service ID/version does not match the release ZIP")
        assets = {}
        for element in service.findall("./extension[@point='xbmc.addon.metadata']/assets/*"):
            asset = element.text or ""
            if (not asset or PurePosixPath(asset).is_absolute()
                    or ".." in PurePosixPath(asset).parts or "\\" in asset):
                raise ValueError("Invalid metadata asset path")
            assets[asset] = archive.read(SERVICE_ID + "/" + asset)
    return service, assets


def build(addon, checksums, output, archives=()):
    addon, output = Path(addon), Path(output)
    service, assets = read_release(addon, checksums)
    previous = []
    for directory in map(Path, archives):
        packages = list(directory.glob(SERVICE_ID + "-*.zip"))
        if len(packages) != 1:
            raise ValueError("Each archived release must contain exactly one service ZIP")
        metadata, _ = read_release(packages[0], directory / "SHA256SUMS")
        if tuple(map(int, metadata.attrib["version"].split("."))) > tuple(
            map(int, service.attrib["version"].split("."))
        ):
            raise ValueError("The index must select the newest archived version")
        previous.append(packages[0])

    repository_xml = (ROOT / "repository/addon.xml").read_bytes()
    repository = ET.fromstring(repository_xml)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output must be empty to avoid publishing stale packages")
    output.mkdir(parents=True, exist_ok=True)
    service_dir = output / SERVICE_ID
    service_dir.mkdir()
    for package in previous:
        shutil.copyfile(package, service_dir / package.name)
    shutil.copyfile(addon, service_dir / addon.name)  # Preserve exact published bytes.
    for name, data in assets.items():
        target = service_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    repo_dir = output / REPO_ID
    repo_dir.mkdir()
    repo_zip = repo_dir / (REPO_ID + "-" + repository.attrib["version"] + ".zip")
    write_zip(repo_zip, {
        REPO_ID + "/addon.xml": repository_xml,
        REPO_ID + "/LICENSE": (ROOT / "LICENSE").read_bytes(),
    })
    shutil.copyfile(repo_zip, output / (REPO_ID + ".zip"))
    index = ET.Element("addons")
    index.extend([repository, service])
    data = ET.tostring(index, encoding="utf-8", xml_declaration=True) + b"\n"
    (output / "addons.xml").write_bytes(data)
    (output / "addons.xml.sha256").write_text(hashlib.sha256(data).hexdigest() + "\n")
    (output / ".nojekyll").touch()
    # Publish only the explicit public website and synthetic documentation images.
    # Keep the Kodi installer/index/package paths and verified release bytes intact.
    shutil.copytree(ROOT / "website", output, dirs_exist_ok=True)
    for name, source in {
        "logo.svg": "docs/images/logo.svg",
        "dashboard.png": "docs/images/dashboard.png",
        "settings-demo-poster.png": "docs/media/settings-demo-poster.png",
    }.items():
        shutil.copyfile(ROOT / source, output / "assets" / name)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--addon", required=True, type=Path)
    parser.add_argument("--checksums", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--archive-dir", type=Path,
                        help="Release directories with older ZIPs and their SHA256SUMS")
    args = parser.parse_args()
    archives = sorted(path for path in args.archive_dir.iterdir() if path.is_dir()) if args.archive_dir else ()
    print(build(args.addon, args.checksums, args.output, archives))

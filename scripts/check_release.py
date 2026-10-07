"""Inspect release archives and write/verify SHA256SUMS without extracting files."""
import argparse
import hashlib
import io
import re
import stat
import tarfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

PRIVATE_PARTS = {".private", ".venv", "__pycache__", "backups", "device_fixes"}
PRIVATE_SUFFIXES = {".apk", ".jar", ".key", ".pem", ".keystore", ".log", ".db", ".sqlite"}
ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "service.kodi.addonadmin"
# Files the Kodi add-on cannot work without, besides everything addon.xml itself names.
ADDON_REQUIRED = ("addon.xml", "resources/settings.xml", "resources/language/resource.language.en_gb/strings.po",
                  "resources/web/index.html", "resources/web/core.js", "resources/web/app.js")
MAX_MEMBER = 10_000_000
MAX_TOTAL = 100_000_000


def check_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Unsafe archive path: " + name)
    if (PRIVATE_PARTS.intersection(path.parts) or path.suffix.lower() in PRIVATE_SUFFIXES
            or any(p.startswith(".env") and p != ".env.example" for p in path.parts)):
        raise ValueError("Private or device artifact in release: " + name)


def inspect_zip(data, depth=0):
    if depth > 2:
        raise ValueError("Unexpected nested archive depth")
    with ZipFile(io.BytesIO(data)) as archive:
        total = 0
        for item in archive.infolist():
            check_name(item.filename)
            total += item.file_size
            if item.file_size > MAX_MEMBER or total > MAX_TOTAL:
                raise ValueError("Archive exceeds release inspection bounds")
            if stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Archive contains a symlink")
            if item.filename.endswith(".zip"):
                inspect_zip(archive.read(item), depth + 1)
        if archive.testzip() is not None:
            raise ValueError("Archive integrity check failed")


def source_version():
    namespace = {}
    exec((ROOT / "src/kodi_manager/version.py").read_text(encoding="utf-8"), namespace)
    return namespace["VERSION"]


def check_addon_zip(data):
    """The Kodi ZIP has one top folder, its entry points and assets, and a matching version."""
    with ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        prefix = ADDON_ID + "/"
        if not names or any(not name.startswith(prefix) for name in names):
            raise ValueError("Add-on ZIP must contain only the %s folder" % ADDON_ID)
        metadata = archive.read(prefix + "addon.xml").decode("utf-8") if prefix + "addon.xml" in names else ""
        needed = set(ADDON_REQUIRED)
        needed.update(re.findall(r'library="([^"]+)"', metadata))
        needed.update(re.findall(r"<(?:icon|fanart|banner|clearlogo|screenshot)>([^<]+)</", metadata))
        missing = sorted(name for name in needed if prefix + name not in names)
        if missing:
            raise ValueError("Add-on ZIP is missing required files: " + ", ".join(missing))
        match = re.search(r'<addon[^>]+version="([^"]+)"', metadata)
        return match.group(1) if match else ""


def archive_version(path):
    """Version stated by an archive's file name (wheel, sdist or add-on ZIP)."""
    match = (re.match(r"[A-Za-z0-9_.]+-([0-9][^-]*)-[^-]+-[^-]+-[^-]+\.whl$", path.name)
             or re.match(r"[A-Za-z0-9_.-]+?-([0-9][0-9A-Za-z.+]*)\.(?:tar\.gz|zip)$", path.name))
    return match.group(1) if match else ""


def inspect_archive(path):
    if path.suffix in (".whl", ".zip"):
        inspect_zip(path.read_bytes())
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            total = 0
            for item in archive:
                check_name(item.name)
                total += item.size
                if item.size > MAX_MEMBER or total > MAX_TOTAL:
                    raise ValueError("Archive exceeds release inspection bounds")
                if not item.isfile() and not item.isdir():
                    raise ValueError("Archive contains a link or special file")
                if item.isfile() and item.name.endswith(".zip"):
                    inspect_zip(archive.extractfile(item).read())
    else:
        raise ValueError("Expected a wheel, ZIP or source tar.gz")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    parser.add_argument("--write-checksums", type=Path)
    parser.add_argument("--verify-checksums", type=Path)
    parser.add_argument("--version", help="expected release version (default: src/kodi_manager/version.py)")
    args = parser.parse_args()
    expected_version = args.version or source_version()
    if len({p.name for p in args.archives}) != len(args.archives):
        raise ValueError("Release filenames must be distinct")
    rows = {}
    for path in args.archives:
        inspect_archive(path)
        versions = {archive_version(path)}
        if path.name.startswith(ADDON_ID + "-") and path.suffix == ".zip":
            versions.add(check_addon_zip(path.read_bytes()))
        if versions != {expected_version}:
            raise ValueError("%s has version %s, expected %s" % (path.name, ", ".join(sorted(versions)), expected_version))
        rows[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    if args.verify_checksums:
        expected = {}
        for line in args.verify_checksums.read_text().splitlines():
            checksum, name = line.split("  ", 1)
            if name in expected or Path(name).name != name:
                raise ValueError("Invalid checksum filename")
            expected[name] = checksum
        for name, checksum in rows.items():
            if expected.get(name) != checksum:
                raise ValueError("Checksum mismatch: " + name)
    if args.write_checksums:
        args.write_checksums.write_text("".join(rows[n] + "  " + n + "\n" for n in sorted(rows)))
    print("Verified %d release archives" % len(rows))


if __name__ == "__main__":
    main()

"""Build a deterministic Kodi companion ZIP from the canonical Python/web sources."""
import argparse
import hashlib
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
ADDON_ID = "service.kodi.addonadmin"


def build(destination=None):
    addon = ROOT / "addon" / ADDON_ID
    metadata = (addon / "addon.xml").read_text(encoding="utf-8")
    version = re.search(r'<addon[^>]+version="([^"]+)"', metadata).group(1)
    namespace = {}
    exec((ROOT / "src/kodi_manager/version.py").read_text(), namespace)
    if version != namespace["VERSION"]:
        raise ValueError("Library and Kodi companion versions differ")
    out = Path(destination or ROOT / "dist")
    out.mkdir(parents=True, exist_ok=True)
    target = out / (ADDON_ID + "-" + version + ".zip")
    entries = {
        "addon.xml": addon / "addon.xml", "LICENSE": ROOT / "LICENSE",
        "resources/settings.xml": addon / "settings.xml",
    }
    for source, prefix, extensions in (
        (ROOT / "src/kodi_manager", "resources/lib", {".py", ".sh"}),
        (ROOT / "web", "resources/web", {".js", ".css", ".html"}),
        (addon / "language", "resources/language", {".po"}),
    ):
        for path in source.rglob("*"):
            if path.is_file() and path.suffix in extensions and "__pycache__" not in path.parts:
                entries[prefix + "/" + path.relative_to(source).as_posix()] = path
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for relative, source in sorted(entries.items()):
            info = ZipInfo(ADDON_ID + "/" + relative, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source.read_bytes())
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(checksum + "  " + target.name + "\n")
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    print(build(parser.parse_args().output))

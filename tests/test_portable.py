import importlib.util
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import pytest

from kodi_manager import ManagerClient, ManagerError, __version__
from kodi_manager.backup import restore_backup, restore_stack_backup
from kodi_manager.fix_protection import FixProtection
from kodi_manager.service import load_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def http_service():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            calls.append((self.path, self.headers.get("Authorization")))
            if self.path == "/api/redirect":
                self.send_response(302)
                self.send_header("Location", "/api/status")
                self.end_headers()
                return
            data = {"ok": True, "data": {"service_version": __version__}}
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%s" % server.server_port, calls
    server.shutdown()
    server.server_close()
    thread.join()


def test_client_authenticated_read_and_redirect_refusal(http_service):
    url, calls = http_service
    client = ManagerClient(url, "synthetic-client-token")
    assert client.status() == {"service_version": __version__}
    assert calls == [("/api/status", "Bearer synthetic-client-token")]
    with pytest.raises(ManagerError, match="302"):
        client.request("/api/redirect")
    assert len(calls) == 2  # No follow-up request sent with the token.


def test_client_writes_and_paths_fail_before_network(http_service):
    url, calls = http_service
    client = ManagerClient(url, "synthetic-client-token")
    with pytest.raises(ManagerError, match="write mode"):
        client.apply_layout({})
    with pytest.raises(ManagerError, match="write mode"):
        client.request("/api/widgets/browse", "PATCH", {})
    for path in ("https://other.example/api/status", "/api/../status", "/api/x?token=secret"):
        with pytest.raises(ValueError):
            client.request(path)
    assert calls == []


def test_read_only_first_run_and_missing_patch_bundle(tmp_path):
    class Addon:
        def getSetting(self, _):
            return ""

        def setSetting(self, *_):
            pass

    with patch("kodi_manager.service.translate", return_value=str(tmp_path)):
        config = load_config(Addon())
    assert not config["write_enabled"]
    assert not config["allow_lan"]
    assert config["host"] == "127.0.0.1"
    assert config["auth_token"]
    fixes = FixProtection(tmp_path / "addons", tmp_path / "backups", tmp_path / "absent")
    assert fixes.status()["bundled"] is False
    assert fixes.status()["healthy"] is None
    with pytest.raises(ValueError, match="safely"):
        fixes.repair()


def test_restore_cannot_traverse_or_follow_backup_symlink(tmp_path):
    root = tmp_path / "backups"
    root.mkdir()
    with patch("kodi_manager.backup.backup_root", return_value=str(root)):
        for value in ("../escape", "..", "/tmp/escape", "x/y", "x\\y", ""):
            with pytest.raises(ValueError):
                restore_stack_backup(object(), value)
            with pytest.raises(ValueError):
                restore_backup({"addon_id": "plugin.test"}, value)
        if os.name != "nt":
            (root / "plugin.test").symlink_to(tmp_path, target_is_directory=True)
            with pytest.raises(ValueError, match="leaves"):
                restore_backup({"addon_id": "plugin.test"}, "synthetic")


def test_companion_uses_canonical_sources_and_is_deterministic(tmp_path):
    spec = importlib.util.spec_from_file_location("build_addon", ROOT / "scripts/build_addon.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    artifact = builder.build(tmp_path)
    original = artifact.read_bytes()
    assert builder.build(tmp_path).read_bytes() == original
    with ZipFile(artifact) as archive:
        paths = archive.namelist()
        assert all(p.startswith("service.kodi.addonadmin/") for p in paths)
        assert not any(x in p for p in paths for x in ("device_fixes", ".env", "tests/", "__pycache__"))
        assert archive.read("service.kodi.addonadmin/resources/lib/skin_layout.py") == (ROOT / "src/kodi_manager/skin_layout.py").read_bytes()
        assert archive.read("service.kodi.addonadmin/resources/web/widgets.js") == (ROOT / "web/widgets.js").read_bytes()
        assert ('version="%s"' % __version__).encode() in archive.read("service.kodi.addonadmin/addon.xml")

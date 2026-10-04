"""Exercise an installed wheel using synthetic local HTTP/storage; never contact a TV."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from kodi_manager import ManagerClient, ManagerError, __version__, flatten_settings, parse_schema
from kodi_manager import backup


def main():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            assert self.headers.get("Authorization") == "Bearer synthetic-token"
            if self.path == "/api/redirect":
                self.send_response(302)
                self.send_header("Location", "/api/status")
                self.end_headers()
                return
            body = json.dumps({"ok": True, "data": {"service_version": __version__}}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ManagerClient("http://127.0.0.1:%s" % server.server_port, "synthetic-token")
        assert client.status()["service_version"] == __version__
        for action in (lambda: client.apply_layout({}), lambda: client.request("/api/redirect")):
            try:
                action()
            except ManagerError:
                pass
            else:
                raise AssertionError("Expected write/redirect refusal")
        with TemporaryDirectory() as directory:
            root = Path(directory)
            schema = root / "schema.xml"
            schema.write_text('<settings><category label="Test"><setting id="password" type="text" label="Password" default=""/></category></settings>')
            settings = root / "settings.xml"
            settings.write_text('<settings><setting id="password">synthetic-private-value</setting></settings>')
            assert "synthetic-private-value" not in str(flatten_settings(parse_schema(str(schema), str(root), str(settings))))
            info = {"addon_id": "plugin.video.synthetic", "addon_data_path": str(root)}
            with patch("kodi_manager.backup.backup_root", return_value=str(root / "snapshots")), patch("kodi_manager.backup.time.strftime", return_value="20260101-120000"):
                # Snapshot a separate data folder: do not include backups recursively.
                live = root / "live"
                live.mkdir()
                info["addon_data_path"] = str(live)
                file = live / "settings.xml"
                file.write_bytes(b"original")
                first = backup.create_backup(info)
                file.write_bytes(b"changed")
                second = backup.create_backup(info)
                assert first["backup_id"] != second["backup_id"]
                result = backup.restore_backup(info, first["backup_id"])
                assert file.read_bytes() == b"original"
                backup.restore_backup(info, result["undo_backup_id"])
                assert file.read_bytes() == b"changed"
        print("Installed Kodi Manager %s: client, secret masking, backup/restore/undo passed" % __version__)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()

"""ManagerClient reports the service's own error code instead of a generic failure."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kodi_manager.client import ManagerClient, ManagerError

REPLIES = {
    "/api/write": (403, {"ok": False, "code": "write_disabled",
                         "error": {"code": "write_disabled", "message": "Writes disabled in service settings"}}),
    "/api/busy": (400, {"ok": False, "code": "playback_active",
                        "error": {"code": "playback_active", "message": "Stop playback, then try again"}}),
    "/api/missing": (404, {"ok": False, "code": "not_found",
                           "error": {"code": "not_found", "message": "Route not found"}}),
    "/api/broken": (500, {"ok": False, "code": "server_error", "error": {"code": "server_error", "message": "boom"}}),
    "/api/html": (502, "<html>bad gateway</html>"),
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        status, body = REPLIES[self.path]
        data = (json.dumps(body) if isinstance(body, dict) else body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def client():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
    thread.start()
    yield ManagerClient("http://%s:%s" % httpd.server_address, "tok", timeout=5)
    httpd.shutdown()
    httpd.server_close()


@pytest.mark.parametrize("path, status, code, words, unsupported", [
    ("/api/write", 403, "write_disabled", "Writes disabled", False),
    ("/api/busy", 400, "playback_active", "Stop playback", False),
    ("/api/missing", 404, "not_found", "Route not found", True),
    ("/api/broken", 500, "server_error", "boom", False),
    ("/api/html", 502, None, "(502)", False),
])
def test_errors_carry_the_service_code(client, path, status, code, words, unsupported):
    with pytest.raises(ManagerError) as caught:
        client.request(path)
    error = caught.value
    assert (error.status, error.code, error.unsupported) == (status, code, unsupported)
    assert words in str(error)
    if code:
        assert code in str(error)

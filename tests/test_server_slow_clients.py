"""Clients that drip their headers must not lock the dashboard out."""
import http.client
import socket
import threading
import time
import re
from types import SimpleNamespace

import pytest

from kodi_manager import server


def _state():
    return SimpleNamespace(kodi=SimpleNamespace(jsonrpc=lambda method, params=None: {"result": []}), logs=[],
                           index=SimpleNamespace(refresh=lambda **k: None), log=lambda *a: None,
                           config={"auth_token": "tok", "host": "127.0.0.1", "port": 0})


@pytest.fixture
def serve():
    servers = []

    def start(server_class, handler=None):
        httpd = server_class(("127.0.0.1", 0), handler or server.make_handler(_state()))
        thread = threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True)
        thread.start()
        servers.append((httpd, thread))
        return httpd
    yield start
    for httpd, thread in servers:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def _get(address):
    started = time.time()
    conn = http.client.HTTPConnection(*address, timeout=10)
    conn.request("GET", "/api/logs", headers={"Authorization": "Bearer tok"})
    status = conn.getresponse().status
    conn.close()
    return status, time.time() - started


def _wait_for(condition, timeout=10.0):
    """Poll instead of sleeping a fixed time: a loaded machine accepts connections slowly."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.02)


def _drip(address, count):
    socks = []
    for _ in range(count):
        sock = socket.create_connection(address)
        sock.sendall(b"GET /api/logs HTTP/1.1\r\n")
        socks.append(sock)
    return socks


def _keep_dripping(socks, stop):
    while not stop.wait(0.2):
        for sock in socks:
            try:
                sock.sendall(b"X-a: b\r\n")
            except OSError:
                pass


class QuickDeadline(server.BoundedThreadingHTTPServer):
    header_deadline = 1.0
    # Long enough that a loaded test machine still gets the slot the deadline frees;
    # without the deadline the drippers keep every slot and the request is refused.
    slot_wait = 10.0
    accepted = 0

    def process_request(self, request, client_address):
        self.accepted += 1
        return server.BoundedThreadingHTTPServer.process_request(self, request, client_address)


def test_dripping_headers_cannot_hold_every_slot(serve):
    httpd = serve(QuickDeadline)
    socks = _drip(httpd.server_address, server.MAX_HANDLERS)
    stop = threading.Event()
    threading.Thread(target=_keep_dripping, args=(socks, stop), daemon=True).start()
    try:
        _wait_for(lambda: httpd.accepted >= server.MAX_HANDLERS)    # every dripper reached the server
        status, took = _get(httpd.server_address)   # waits for a slot freed by the deadline
        assert status == 200 and took < QuickDeadline.slot_wait
    finally:
        stop.set()
        for sock in socks:
            sock.close()


def test_headers_cut_off_by_the_deadline_are_never_acted_on(serve):
    httpd = serve(QuickDeadline)
    sock = socket.create_connection(httpd.server_address)
    sock.sendall(b"GET /api/logs HTTP/1.0\r\nAuthorization: Bearer tok\r\n")
    sock.settimeout(5)
    assert sock.recv(100) == b""      # closed at the deadline without a response
    sock.close()


class OneLanClient(QuickDeadline):
    """Treat the dripping sockets as one LAN device and the dashboard as another."""
    header_deadline = 30.0
    slot_wait = 0.5
    drippers = set()

    def client_key(self, client_address):
        return "192.168.1.66" if client_address[1] in self.drippers else "192.168.1.20"


def test_one_client_cannot_take_every_slot(serve):
    httpd = serve(OneLanClient)
    socks = []
    for _ in range(server.MAX_HANDLERS):
        sock = socket.create_connection(httpd.server_address)
        OneLanClient.drippers.add(sock.getsockname()[1])
        sock.sendall(b"GET /api/logs HTTP/1.1\r\n")
        socks.append(sock)
    try:
        _wait_for(lambda: httpd._clients.get("192.168.1.66") == server.MAX_HANDLERS_PER_CLIENT)
        # Served, not refused after slot_wait: the per-client cap left slots free for others.
        status, _ = _get(httpd.server_address)
        assert status == 200
    finally:
        for sock in socks:
            try:
                sock.sendall(b"\r\n")         # finish the request so the server can answer it
                sock.settimeout(5)
                sock.recv(100)
            except OSError:
                pass
            sock.close()


def body_server(serve, consume_body=True):
    state = _state()
    state.config["write_enabled"] = True
    writes, entered = [], threading.Event()
    handler = server.make_handler(state)
    handler.route_table += (("POST", re.compile(r"^/api/probe$"), "probe", True, "bad_request"),)
    original_body = handler.body

    def read_body(self):
        entered.set()
        return original_body(self)

    handler.body = read_body

    def probe(self):
        data = self.body() if consume_body else {}
        writes.append(data)
        return data

    handler.api_probe = probe

    class BodyDeadline(QuickDeadline):
        body_deadline = 0.6

    return serve(BodyDeadline, handler), writes, entered


def post_headers(length):
    return ("POST /api/probe HTTP/1.0\r\nHost: 127.0.0.1\r\nAuthorization: Bearer tok\r\n"
            "Content-Length: %d\r\n\r\n" % length).encode()


@pytest.mark.parametrize("change,status", [("auth_token", 401), ("write_enabled", 403), ("retired", 409), ("profile", 409)])
def test_delayed_body_cannot_outlive_access_or_profile(serve, monkeypatch, change, status):
    from kodi_manager import http_base
    current = {"profile": "profile-a"}
    monkeypatch.setattr(http_base, "profile_path", lambda: current["profile"], raising=False)
    httpd, writes, entered = body_server(serve)
    httpd.body_deadline = 5
    state = httpd.RequestHandlerClass.state
    state.profile_path = "profile-a"
    body = b'{"enabled":true}'
    with socket.create_connection(httpd.server_address, timeout=5) as sock:
        sock.sendall(post_headers(len(body)))
        assert entered.wait(5)
        if change == "retired":
            state.retired = True
        elif change == "profile":
            current["profile"] = "profile-b"
        else:
            state.config[change] = "replacement-token" if change == "auth_token" else False
        sock.sendall(body)
        assert str(status).encode() in sock.recv(4096)
    assert writes == []


def test_profile_change_during_read_cannot_return_profile_data(serve, monkeypatch):
    from kodi_manager import http_base
    current = {"profile": "profile-a"}
    monkeypatch.setattr(http_base, "profile_path", lambda: current["profile"])
    state = _state()
    state.profile_path = "profile-a"
    handler = server.make_handler(state)
    handler.route_table += (("GET", re.compile(r"^/api/profile-probe$"), "probe", False, "bad_request"),)

    def probe(self):
        current["profile"] = "profile-b"
        return {"value": "synthetic-private-profile-data"}

    handler.api_probe = probe
    httpd = serve(QuickDeadline, handler)
    conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
    try:
        conn.request("GET", "/api/profile-probe", headers={"Authorization": "Bearer tok"})
        response = conn.getresponse()
        assert response.status == 409 and b"synthetic-private" not in response.read()
    finally:
        conn.close()


def test_profile_change_during_addon_lookup_blocks_mutation(serve, monkeypatch):
    from kodi_manager import http_base
    current, writes = {"profile": "profile-a"}, []
    monkeypatch.setattr(http_base, "profile_path", lambda: current["profile"])
    state = _state()
    state.profile_path = "profile-a"
    state.config["write_enabled"] = True
    state.index = SimpleNamespace(refresh=lambda: None, get=lambda aid: current.update(profile="profile-b") or {"addon_id": aid})
    handler = server.make_handler(state)
    handler.route_table += (("POST", re.compile(r"^/api/profile-probe$"), "probe", True, "bad_request"),)

    def probe(self):
        writes.append(self._addon("plugin.video.example"))
        return {"changed": True}

    handler.api_probe = probe
    httpd = serve(QuickDeadline, handler)
    conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
    try:
        conn.request("POST", "/api/profile-probe", body="{}", headers={"Authorization": "Bearer tok"})
        assert conn.getresponse().status == 409 and writes == []
    finally:
        conn.close()


def test_request_backup_root_stays_with_service_generation(serve, monkeypatch, tmp_path):
    from kodi_manager import http_base, backup
    current = {"profile": "profile-a"}
    monkeypatch.setattr(http_base, "profile_path", lambda: current["profile"])
    other = tmp_path / "profile-b-backups"
    monkeypatch.setattr(backup, "backup_root", lambda: str(other))
    live = tmp_path / "profile-a-data"
    live.mkdir()
    (live / "settings.xml").write_bytes(b"synthetic-profile-a-setting")
    state = _state()
    state.profile_path = "profile-a"
    state.backup_directory = str(tmp_path / "profile-a-backups")
    state.config["write_enabled"] = True
    handler = server.make_handler(state)
    handler.route_table += (("POST", re.compile(r"^/api/profile-probe$"), "probe", True, "bad_request"),)

    def probe(self):
        current["profile"] = "profile-b"
        return backup.create_backup({"addon_id": "plugin.video.example", "addon_data_path": str(live)})

    handler.api_probe = probe
    httpd = serve(QuickDeadline, handler)
    conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
    try:
        conn.request("POST", "/api/profile-probe", body="{}", headers={"Authorization": "Bearer tok"})
        assert conn.getresponse().status == 409
        assert list((tmp_path / "profile-a-backups").rglob("settings.xml")) and not other.exists()
    finally:
        conn.close()


@pytest.mark.parametrize("active", [False, None])
def test_tvos_inactive_state_blocks_even_body_free_action(serve, monkeypatch, active):
    from kodi_manager import tvos_storage
    monkeypatch.setattr(tvos_storage, "is_tvos", lambda: True)
    monkeypatch.setattr(tvos_storage, "application_active", lambda: active)
    httpd, writes, _ = body_server(serve, consume_body=False)
    conn = http.client.HTTPConnection(*httpd.server_address, timeout=3)
    try:
        conn.request("POST", "/api/probe", body="{}", headers={"Authorization": "Bearer tok"})
        assert conn.getresponse().status == 400
        assert writes == []
    finally:
        conn.close()


def test_portable_endpoints_keep_auth_and_bound_file_reads(serve, tmp_path, monkeypatch):
    import base64
    import json
    from kodi_manager import portable_api, tvos_storage
    root = tmp_path / "userdata"
    root.mkdir()
    (root / "guisettings.xml").write_bytes(b"<settings/>")
    mapping = {"special://masterprofile/": str(root), "special://profile/": str(root),
               "special://masterprofile/addon_data/service.kodi.addonadmin/device_identity.xml":
               str(root / "addon_data/service.kodi.addonadmin/device_identity.xml")}
    monkeypatch.setattr(portable_api, "translate", mapping.__getitem__)
    monkeypatch.setattr(tvos_storage, "application_active", lambda: True)
    state = _state()
    state.kodi.jsonrpc = lambda method: {"result": {"label": "Adults"}}
    httpd = serve(server.ThreadingHTTPServer, server.make_handler(state))

    def get(path, token="tok"):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=3)
        try:
            conn.request("GET", path, headers={"Authorization": "Bearer " + token})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    assert get("/api/portable/state", "wrong")[0] == 401
    status, data = get("/api/portable/state")
    assert status == 200 and len(data["data"]["device_id"]) == 32
    identifier = data["data"]["device_id"]
    status, data = get("/api/portable/file?path=userdata/guisettings.xml")
    assert status == 200 and base64.b64decode(data["data"]["base64"]) == b"<settings/>"
    assert data["data"]["device_id"] == identifier and data["data"]["profile_root"] == "userdata"
    assert get("/api/portable/file?path=userdata/guisettings.xml&device_id=" + "b" * 32)[0] == 400
    assert get("/api/portable/file?path=userdata/guisettings.xml&profile_root=userdata/profiles/Kids")[0] == 400
    assert get("/api/portable/file?path=userdata/../secret.xml")[0] == 400
    (root / "guisettings.xml").write_bytes(b"x" * 600_001)
    assert get("/api/portable/file?path=userdata/guisettings.xml")[0] == 400


@pytest.mark.parametrize("consume_body", [True, False])
def test_short_body_with_valid_json_never_performs_write(serve, consume_body):
    httpd, writes, _ = body_server(serve, consume_body)
    body = b'{"enabled":true}'
    with socket.create_connection(httpd.server_address, timeout=5) as sock:
        sock.sendall(post_headers(len(body) + 1) + body)
        sock.shutdown(socket.SHUT_WR)
        assert b"400" in sock.recv(4096)
    assert writes == []


def test_complete_body_can_perform_authorized_write(serve):
    httpd, writes, _ = body_server(serve)
    conn = http.client.HTTPConnection(*httpd.server_address, timeout=5)
    conn.request("POST", "/api/probe", body=b'{"enabled":true}', headers={"Authorization": "Bearer tok"})
    assert conn.getresponse().status == 200
    conn.close()
    assert writes == [{"enabled": True}]


def test_dripping_body_is_closed_and_frees_handler(serve):
    httpd, writes, entered = body_server(serve)
    stop = threading.Event()
    with socket.create_connection(httpd.server_address, timeout=3) as sock:
        sock.sendall(post_headers(1000) + b'{')
        assert entered.wait(5)

        def drip():
            while not stop.wait(0.1):
                try:
                    sock.sendall(b' ')
                except OSError:
                    return

        thread = threading.Thread(target=drip, daemon=True)
        thread.start()
        try:
            try:
                assert sock.recv(4096) == b""
            except ConnectionResetError:
                pass  # Windows may reset instead of returning EOF.
        finally:
            stop.set()
            thread.join()
    assert writes == []
    assert _get(httpd.server_address)[0] == 200

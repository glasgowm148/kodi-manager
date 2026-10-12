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

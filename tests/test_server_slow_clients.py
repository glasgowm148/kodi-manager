"""Clients that drip their headers must not lock the dashboard out."""
import http.client
import socket
import threading
import time
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

    def start(server_class):
        httpd = server_class(("127.0.0.1", 0), server.make_handler(_state()))
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
    slot_wait = 3.0


def test_dripping_headers_cannot_hold_every_slot(serve):
    httpd = serve(QuickDeadline)
    socks = _drip(httpd.server_address, server.MAX_HANDLERS)
    stop = threading.Event()
    threading.Thread(target=_keep_dripping, args=(socks, stop), daemon=True).start()
    try:
        time.sleep(0.3)
        status, took = _get(httpd.server_address)   # waits for a slot freed by the deadline
        assert status == 200 and took < 2.5
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
        time.sleep(0.3)
        assert httpd._clients.get("192.168.1.66") == server.MAX_HANDLERS_PER_CLIENT
        status, took = _get(httpd.server_address)
        assert status == 200 and took < 1.0
    finally:
        for sock in socks:
            try:
                sock.sendall(b"\r\n")         # finish the request so the server can answer it
                sock.settimeout(5)
                sock.recv(100)
            except OSError:
                pass
            sock.close()

"""A helper app checks it is talking to this Kodi Manager before it sends the token."""
import hashlib
import hmac
import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from kodi_manager import api_status, server
from kodi_manager.auth import IDENTITY_CONTEXT, identity_proof
from kodi_manager.operation_records import History

TOKEN = "synthetic-token"
NONCE = "0123456789abcdef" * 2


def expected(token, nonce):
    return hmac.new(token.encode(), IDENTITY_CONTEXT + nonce.encode(), hashlib.sha256).hexdigest()


def test_proof_is_an_hmac_of_the_client_nonce():
    assert identity_proof(TOKEN, NONCE) == expected(TOKEN, NONCE)
    assert identity_proof(TOKEN, NONCE) != identity_proof("other-token", NONCE)
    for bad in (None, "", "abc", NONCE.upper(), NONCE + "g", "0" * 130, 123):
        assert identity_proof(TOKEN, bad) is None
    assert identity_proof("", NONCE) is None


@pytest.fixture
def service(tmp_path, monkeypatch):
    state = SimpleNamespace(
        kodi=SimpleNamespace(jsonrpc=lambda *args: {"result": []}),
        config={"host": "127.0.0.1", "auth_token": TOKEN, "write_enabled": False},
        operations=History(tmp_path / "operations"), logs=[], log=lambda *args: None,
        retired=False, web_root="",
    )
    monkeypatch.setattr(api_status, "translate", lambda path: str(tmp_path / "x.json"))
    httpd = server.BoundedThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(state))
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()

    def post(path, body, token=None):
        conn = http.client.HTTPConnection(*httpd.server_address, timeout=3)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        conn.request("POST", path, body=json.dumps(body), headers=headers)
        response = conn.getresponse()
        result = response.status, json.loads(response.read())
        conn.close()
        return result
    yield post
    httpd.shutdown()
    httpd.server_close()
    thread.join(2)


def test_endpoint_answers_without_a_token_and_reveals_nothing_else(service):
    status, body = service("/api/identity/proof", {"nonce": NONCE})
    assert status == 200 and body["data"]["proof"] == expected(TOKEN, NONCE)
    assert TOKEN not in json.dumps(body)
    status, body = service("/api/identity/proof", {"nonce": "short"})
    assert status == 400 and body["code"] == "bad_request"
    # Every other route still needs the token.
    status, body = service("/api/search/voice", {"query": "x"})
    assert status == 401

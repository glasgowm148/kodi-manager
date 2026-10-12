"""The dashboard's HTTP layer: request checks, the JSON envelope, static files and the bounded server.

``RequestHandler`` answers every request; the API handlers are mixed in from api_*.py and the
route table from server.py (``make_handler``). Nothing here knows about Kodi beyond asking
whether something is playing.
"""
import json
import os
import posixpath
import socket
import threading
import time
import ipaddress
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlsplit
from typing import Any, Dict, Optional, Tuple

try:
    from .version import VERSION
    from .auth import authorized
    from .validation import redact, mask_query_secrets
    from .write_policy import WriteRefused
    from .netconfig import host_allowed, is_loopback
    from .addon_index import AddonIndex
except ImportError:
    from version import VERSION
    from auth import authorized
    from validation import redact, mask_query_secrets
    from write_policy import WriteRefused
    from netconfig import host_allowed, is_loopback
    from addon_index import AddonIndex

MAX_HANDLERS = 16
# A request line and headers must arrive within this many seconds in total. The handler
# timeout only bounds each read, so a client sending one header line every few seconds
# could otherwise hold a handler slot for many minutes.
HEADER_DEADLINE = 5.0
BODY_DEADLINE = 20.0
# Handler slots one (non-loopback) client address may hold at once; browsers open at most 6.
MAX_HANDLERS_PER_CLIENT = 8


class AdminState:
    def __init__(self, kodi, config, web_root):
        self.kodi = kodi
        self.config = config
        self.web_root = web_root
        self.index = AddonIndex(kodi)
        self.logs = []

    def log(self, msg):
        safe = str(redact({"msg": msg})["msg"])
        self.logs.append("%s %s" % (time.strftime("%H:%M:%S"), safe))
        self.logs = self.logs[-300:]
        self.kodi.log(safe)


def _private_client(ip):
    try:
        addr = ipaddress.ip_address(ip)
        return bool(addr.is_private or addr.is_loopback)
    except ValueError:
        return False


class ApiError(Exception):
    def __init__(self, status, code, message, details=None):
        super(ApiError, self).__init__(message)
        self.status, self.code, self.details = status, code, details


class RequestHandler(BaseHTTPRequestHandler):
    """Checks, envelope, dispatch and helpers shared by every API handler mixin.

    ``state`` (an ``AdminState``) and ``route_table`` are set by ``server.make_handler``.
    """
    server_version = "KodiManager/" + VERSION
    timeout = 20
    state: AdminState
    route_table: Tuple[Any, ...] = ()
    _body: Optional[Dict[str, Any]] = None

    def handle_one_request(self):
        # Close the connection if the request line and headers are not complete in time.
        self._header_lock = threading.Lock()
        self._header_state = "reading"
        deadline = getattr(self.server, "header_deadline", HEADER_DEADLINE)
        timer = threading.Timer(deadline, self._header_timeout)
        timer.daemon = True
        timer.start()
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # Disconnected clients cannot receive an error envelope.
        finally:
            timer.cancel()

    def _header_timeout(self):
        with self._header_lock:
            if self._header_state != "reading":
                return
            self._header_state = "expired"
        self.close_connection = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def parse_request(self):
        parsed = BaseHTTPRequestHandler.parse_request(self)
        with self._header_lock:
            expired = self._header_state == "expired"
            self._header_state = "done"
        if expired:
            # Headers cut short by the deadline: never act on them.
            self.close_connection = True
            return False
        return parsed

    def log_message(self, format, *args):
        # The request line can carry ?token=...: mask query secrets before logging.
        self.state.log(mask_query_secrets(format % args))

    # --- responses -------------------------------------------------------

    def _send(self, status, data, content_type="application/json"):
        body = data if isinstance(data, bytes) else json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def ok(self, data=None):
        self._send(200, {"ok": True, "data": data if data is not None else {}})

    def err(self, status, code, message, details=None):
        self._send(status, {"ok": False, "code": code,
                            "error": {"code": code, "message": str(redact(message)), "details": redact(details or {})}})

    # --- request checks ----------------------------------------------------

    def _target(self):
        """The request path, or None after answering 400 for a non-origin-form target."""
        raw = self.path
        if not raw.startswith("/") or raw.startswith("//"):
            self.err(400, "bad_request", "Request target must be a plain path")
            return None
        parts = urlsplit(raw)
        if parts.scheme or parts.netloc or parts.fragment:
            self.err(400, "bad_request", "Request target must be a plain path")
            return None
        path = parts.path
        decoded = unquote(path)
        segments = decoded.split("/")[1:]
        if "//" in path or "\\" in decoded or any(seg in (".", "..") for seg in segments) or "\x00" in decoded:
            self.err(400, "bad_request", "Request path is not normalised")
            return None
        return path

    def _client_allowed(self):
        if is_loopback(self.state.config.get("host")):
            return True
        if _private_client(self.client_address[0]):
            return True
        self.err(403, "forbidden", "Non-private client rejected")
        return False

    def _host_allowed(self):
        if host_allowed(self.headers.get("Host"), self.state.config.get("host")):
            return True
        self.err(403, "host_not_allowed", "Use the TV's IP address, a .local name or localhost")
        return False

    def _origin_allowed(self):
        """Browsers send Origin on cross-site writes; the dashboard itself is same-origin."""
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        try:
            parsed = urlsplit(origin.strip())
            origin_host = parsed.netloc.lower() if parsed.scheme in ("http", "https") else ""
        except ValueError:
            origin_host = ""
        if origin_host and host and origin_host == host:
            return True
        self.err(403, "origin_mismatch", "Cross-origin request rejected")
        return False

    def _auth(self, path):
        if path == "/api/bootstrap/status" and self._bootstrap_allowed():
            return True
        if not authorized(self.headers.get("Authorization"), self.state.config.get("auth_token")):
            self.err(401, "unauthorized", "Missing or invalid bearer token")
            return False
        if self.state.config.get("delete_installer_result_after_first_login"):
            try:
                os.remove(os.path.join(self.state.config.get("addon_data_dir", ""), "installer_result.json"))
            except Exception:
                pass
        return True

    def _bootstrap_allowed(self):
        data_dir = self.state.config.get("addon_data_dir", "")
        return os.path.exists(os.path.join(data_dir, "installer_seed.json")) and os.path.exists(os.path.join(data_dir, "installer_result.json"))

    # --- dispatch ----------------------------------------------------------

    def do_OPTIONS(self):
        # Same-origin dashboard: no CORS grant for other origins.
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PATCH(self):
        self._dispatch("PATCH")

    def _dispatch(self, method):
        self._body = None
        path = self._target()
        if path is None or not self._client_allowed() or not self._host_allowed():
            return
        is_api = path == "/api" or path.startswith("/api/")
        if not is_api:
            if method != "GET":
                self.err(404, "not_found", "Route not found")
                return
            try:
                self.static(path)
            except Exception as exc:
                self.err(500, "server_error", str(exc))
            return
        if method != "GET" and not self._origin_allowed():
            return
        if not self._auth(path):
            return
        self.route_api(method, path)

    def route_api(self, method, path):
        found = None
        for route_method, pattern, name, needs_write, value_code in self.route_table:
            if route_method != method:
                continue
            match = pattern.match(path)
            if match:
                found = (match, name, needs_write, value_code)
                break
        if found is None:
            self.err(404, "not_found", "Route not found")
            return
        match, name, needs_write, value_code = found
        try:
            if needs_write and not self.state.config.get("write_enabled"):
                raise PermissionError("Write Mode is disabled")
            if method in ("POST", "PATCH"):
                self.body()  # Validate framing before even handlers that take no body fields.
            result = getattr(self, "api_" + name.replace("-", "_"))(**match.groupdict())
            self.ok(result)
        except ApiError as exc:
            self.err(exc.status, exc.code, str(exc), exc.details)
        except WriteRefused as exc:
            self.err(403, exc.code, str(exc))
        except PermissionError as exc:
            self.err(403, "write_disabled", str(exc))
        except ValueError as exc:
            setting_id = getattr(exc, "setting_id", None)
            self.err(400, value_code, str(exc), {"setting_id": setting_id} if setting_id else None)
        except (LookupError, FileNotFoundError) as exc:
            self.err(404, "not_found", exc.args[0] if exc.args and isinstance(exc.args[0], str) else "Not found")
        except Exception as exc:
            self.err(500, "server_error", str(exc))

    def static(self, path):
        path = unquote(path)
        if path == "/":
            path = "/index.html"
        rel = posixpath.normpath(path).lstrip("/")
        full = os.path.abspath(os.path.join(self.state.web_root, rel))
        web_root = os.path.abspath(self.state.web_root)
        if os.path.commonpath([web_root, full]) != web_root or not os.path.isfile(full):
            self.err(404, "not_found", "File not found")
            return
        ctype = "text/html" if full.endswith(".html") else "text/css" if full.endswith(".css") else "application/javascript" if full.endswith(".js") else "application/octet-stream"
        with open(full, "rb") as fh:
            self._send(200, fh.read(), ctype)

    # --- helpers -----------------------------------------------------------

    def body(self):
        """The JSON request body as a dict ({} when empty); anything else is a 400."""
        if self._body is not None:
            return self._body
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            raise ValueError("Invalid Content-Length") from None
        if length < 0 or length > 1000000 or self.headers.get("Transfer-Encoding"):
            raise ValueError("Request body must be at most 1 MB with a fixed length")
        raw = b""
        if length:
            lock, expired = threading.Lock(), threading.Event()
            finished = False

            def deadline():
                with lock:
                    if finished:
                        return
                    expired.set()
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            timer = threading.Timer(getattr(self.server, "body_deadline", BODY_DEADLINE), deadline)
            timer.daemon = True
            timer.start()
            try:
                raw = self.rfile.read(length)
            finally:
                with lock:
                    finished = True
                timer.cancel()
            if expired.is_set() or len(raw) != length:
                raise ValueError("Request body is incomplete or timed out; no action performed")
        data = json.loads(raw.decode("utf-8")) if length else {}
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        self._body = data
        return data

    def query(self, name, default=""):
        return (parse_qs(urlsplit(self.path).query).get(name) or [default])[0]

    def _require_idle(self, message, status=400):
        players = self.state.kodi.jsonrpc("Player.GetActivePlayers")
        if not isinstance(players, dict) or "error" in players or players.get("result") != []:
            # Code playback_active. Restores answer 409 because {"force": true} overrides them;
            # actions that cannot be forced keep their historic 400.
            raise ApiError(status, "playback_active", message)

    def _playback_started(self, every=2.0):
        """A should_stop callback: true once a player is active, asking Kodi at most every ``every`` s."""
        last = {"at": float("-inf"), "playing": False}

        def playing():
            now = time.monotonic()
            if now - last["at"] >= every:
                last["at"] = now
                players = self.state.kodi.jsonrpc("Player.GetActivePlayers")
                last["playing"] = not isinstance(players, dict) or "error" in players or players.get("result") != []
            return last["playing"]
        return playing

    def _require_idle_unless_forced(self, message):
        force = self.body().get("force", False)
        if not isinstance(force, bool):
            raise ValueError("force must be boolean")
        if not force:
            self._require_idle(message, status=409)

    def _addon(self, aid):
        self.state.index.refresh()
        addon = self.state.index.get(aid)
        if not addon:
            raise LookupError("Add-on not found")
        return addon


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    """Daemon handler threads, at most MAX_HANDLERS at once.

    When every slot stays busy the connection is closed instead of queueing an
    unbounded number of threads that each wait on Kodi.
    """
    daemon_threads = True
    # Never join handler threads on close: one may be blocked in a Kodi call
    # while a profile change holds Kodi's GUI lock.
    block_on_close = False
    max_handlers = MAX_HANDLERS
    max_per_client = MAX_HANDLERS_PER_CLIENT
    header_deadline = HEADER_DEADLINE
    slot_wait = 5.0

    def __init__(self, *args, **kwargs):
        self._slots = threading.BoundedSemaphore(self.max_handlers)
        self._clients = {}
        self._clients_lock = threading.Lock()
        ThreadingHTTPServer.__init__(self, *args, **kwargs)

    def client_key(self, client_address):
        """The address a per-client limit applies to; None (no limit) for loopback clients,
        which share one address and are bounded by the header deadline instead."""
        host = client_address[0] if client_address else ""
        return None if is_loopback(host) else host

    def _claim_client(self, key):
        if key is None:
            return True
        with self._clients_lock:
            if self._clients.get(key, 0) >= self.max_per_client:
                return False
            self._clients[key] = self._clients.get(key, 0) + 1
            return True

    def _release_client(self, key):
        if key is None:
            return
        with self._clients_lock:
            left = self._clients.get(key, 0) - 1
            if left > 0:
                self._clients[key] = left
            else:
                self._clients.pop(key, None)

    def process_request(self, request, client_address):
        key = self.client_key(client_address)
        # One client may not take every slot: refuse at once rather than block accepting others.
        if not self._claim_client(key):
            self.shutdown_request(request)
            return
        if not self._slots.acquire(timeout=self.slot_wait):
            self._release_client(key)
            self.shutdown_request(request)
            return
        try:
            ThreadingHTTPServer.process_request(self, request, client_address)
        except Exception:
            self._slots.release()
            self._release_client(key)
            raise

    def process_request_thread(self, request, client_address):
        try:
            ThreadingHTTPServer.process_request_thread(self, request, client_address)
        finally:
            self._slots.release()
            self._release_client(self.client_key(client_address))

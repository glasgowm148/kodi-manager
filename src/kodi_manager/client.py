"""Dependency-free client for one explicitly configured Kodi Manager service."""
import json
import re
import socket
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from .operation_records import correlation, clean, next_step, REFUSALS

READ_POSTS = frozenset({
    "/api/widgets/browse", "/api/widgets/suggestions", "/api/widgets/row-preview",
    "/api/widgets/layout/preview", "/api/pipeline/rescan", "/api/playback/test",
    "/api/widget-cache/refresh",
})
MAX_BYTES = 4_000_000


class ManagerError(RuntimeError):
    """Value-free connection, API or capability error.

    ``status`` is the HTTP status (None for connection failures), ``code`` the service's
    error code (``write_disabled``, ``playback_active``, ``addon_not_allowed``...). Only a
    404 means the service lacks the endpoint (``unsupported``): a 400, 403, 409 or 500 from
    a current service is a refusal or a failure to act on, not a reason to upgrade.
    """

    def __init__(self, message, status=None, code=None, operation=None, outcome=None, correlation_id=None):
        super(ManagerError, self).__init__(message)
        self.status, self.code = status, code
        self.operation = operation
        self.outcome = outcome or (operation["outcome"] if operation else "refused" if code in REFUSALS else "failed")
        self.correlation_id = operation["correlation_id"] if operation else correlation_id
        self.next_step = next_step("outcome_unknown" if self.outcome == "unknown" else code)

    @property
    def unsupported(self):
        return self.status == 404 and (self.code is None or self.code == "not_found" and "Route not found" in str(self))


def _error_details(raw, token=""):
    """(code, message) from a service error envelope, or (None, None)."""
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None, None
    error = body.get("error") if isinstance(body, dict) else None
    source = error if isinstance(error, dict) else body if isinstance(body, dict) else {}
    code = source.get("code")
    if (not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", code)
            or (token and token in code)):
        code = None
    message = error.get("message") if isinstance(error, dict) and isinstance(error.get("message"), str) else None
    if message and token:
        message = message.replace(token, "[redacted]")
    return code, (message[:300] if message else None)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ManagerClient:
    """Authenticated LAN client; mutation requires allow_writes and service write mode.

    Folder/row previews execute provider code and may contact external providers.
    The library does not authorize disruptive actions on behalf of the viewer.
    """

    def __init__(self, base_url, token, *, allow_writes=False, timeout=20):
        origin = urlsplit(base_url)
        if (origin.scheme not in ("http", "https") or not origin.hostname
                or origin.username or origin.password or origin.query or origin.fragment
                or origin.path not in ("", "/")):
            raise ValueError("Use a single HTTP(S) origin without credentials or a path")
        if not isinstance(token, str) or not token or any(c.isspace() for c in token):
            raise ValueError("A bearer token is required")
        if not 0 < timeout <= 120:
            raise ValueError("timeout must be between 0 and 120 seconds")
        self._url = base_url.rstrip("/")
        self._token = token
        self.allow_writes = allow_writes
        self.timeout = timeout
        # Never forward the local bearer token through a proxy or redirect.
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())
        self.last_operation = None
        self.last_correlation_id = None

    def request(self, path, method="GET", body=None, *, correlation_id=None):
        self.last_operation = None
        self.last_correlation_id = correlation(None if correlation_id == self._token else correlation_id)
        if not re.fullmatch(r"/api/[a-zA-Z0-9._/-]+", path) or ".." in path:
            raise ValueError("Expected an API path without query, escapes or traversal")
        if method not in ("GET", "POST", "PATCH"):
            raise ValueError("Unsupported HTTP method")
        # Read-only POSTs (browse, preview, suggestions) cannot change anything on a lost reply.
        is_write = method != "GET" and not (method == "POST" and path in READ_POSTS)
        if is_write and not self.allow_writes:
            raise ManagerError("Client write mode is disabled", code="write_disabled", outcome="refused",
                               correlation_id=self.last_correlation_id)
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None and len(data) > 1_000_000:
            raise ValueError("Request exceeds 1 MB")
        request = Request(self._url + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self._token, "Content-Type": "application/json",
            "X-Correlation-ID": self.last_correlation_id,
        })
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ManagerError("Response exceeds 4 MB; narrow the request", code="invalid_response", outcome="failed" if not is_write else "unknown")
            result = json.loads(raw)
        except HTTPError as exc:
            operation = None
            try:
                raw = exc.read(65536)
                code, message = _error_details(raw, self._token)
                envelope = json.loads(raw)
                operation = clean(envelope.get("operation")) if isinstance(envelope, dict) else None
                if operation and (operation["correlation_id"] != self.last_correlation_id or self._token in json.dumps(operation)):
                    operation = None
            except (HTTPException, OSError, ValueError):
                code, message = None, None
            finally:
                exc.close()
            text = "Manager HTTP request failed (%s%s)" % (exc.code, " " + code if code else "")
            self.last_operation = operation
            outcome = "unknown" if is_write and exc.code >= 500 and operation is None else None
            raise ManagerError(text + (": " + message if message else ""), exc.code, code, operation, outcome, self.last_correlation_id) from None
        except (socket.timeout, TimeoutError):
            raise ManagerError("Manager timed out; inspect state before retrying", code="timeout" if not is_write else "outcome_unknown", outcome="failed" if not is_write else "unknown", correlation_id=self.last_correlation_id) from None
        except (ValueError, HTTPException):
            raise ManagerError("Manager returned an invalid response; inspect state before retrying", code="invalid_response", outcome="failed" if not is_write else "unknown", correlation_id=self.last_correlation_id) from None
        except (URLError, OSError) as exc:
            timed_out = isinstance(getattr(exc, "reason", exc), (socket.timeout, TimeoutError))
            ambiguous = is_write and not isinstance(getattr(exc, "reason", exc), ConnectionRefusedError)
            raise ManagerError("Manager connection failed; inspect state before retrying", code="outcome_unknown" if ambiguous else "timeout" if timed_out else "unreachable", outcome="unknown" if ambiguous else "failed", correlation_id=self.last_correlation_id) from None
        self.last_operation = clean(result.get("operation")) if isinstance(result, dict) else None
        if self.last_operation and (self.last_operation["correlation_id"] != self.last_correlation_id or self._token in json.dumps(self.last_operation)):
            self.last_operation = None
        if not isinstance(result, dict) or result.get("ok") is not True or "data" not in result:
            code, message = _error_details(raw, self._token)
            raise ManagerError("Manager returned an invalid or unsuccessful response"
                               + (": " + message if message else ""), 200, code or "invalid_response", self.last_operation,
                               "unknown" if is_write else "failed", self.last_correlation_id)
        return result["data"]

    def status(self):
        return self.request("/api/status")

    def health(self):
        return self.request("/api/health")

    def support_bundle(self):
        return self.request("/api/diagnostics/support")

    def pipeline(self):
        return self.request("/api/pipeline")

    def addons(self):
        return self.request("/api/addons")

    def settings(self, addon_id):
        if not re.fullmatch(r"[A-Za-z0-9._-]+", addon_id) or ".." in addon_id:
            raise ValueError("Invalid add-on ID")
        return self.request("/api/addons/%s/settings" % addon_id)

    def layout(self):
        return self.request("/api/widgets/layout")

    def sources(self):
        return self.request("/api/widgets/sources")

    def browse(self, path, *, start=0, limit=24):
        if not isinstance(start, int) or not isinstance(limit, int) or start < 0 or not 1 <= limit <= 48:
            raise ValueError("Use a non-negative offset and limit between 1 and 48")
        return self.request("/api/widgets/browse", "POST", {"path": path, "start": start, "limit": limit})

    def preview_layout(self, plan):
        return self.request("/api/widgets/layout/preview", "POST", plan)

    def apply_layout(self, plan):
        return self.request("/api/widgets/layout/apply", "POST", plan)

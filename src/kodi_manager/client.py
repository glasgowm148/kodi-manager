"""Dependency-free client for one explicitly configured Kodi Manager service."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

READ_POSTS = frozenset({
    "/api/widgets/browse", "/api/widgets/suggestions", "/api/widgets/row-preview",
    "/api/widgets/layout/preview", "/api/pipeline/rescan", "/api/playback/test",
    "/api/widget-cache/refresh",
})
MAX_BYTES = 4_000_000


class ManagerError(RuntimeError):
    """Value-free connection, API or capability error."""


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

    def request(self, path, method="GET", body=None):
        if not re.fullmatch(r"/api/[a-zA-Z0-9._/-]+", path) or ".." in path:
            raise ValueError("Expected an API path without query, escapes or traversal")
        if method not in ("GET", "POST", "PATCH"):
            raise ValueError("Unsupported HTTP method")
        if method != "GET" and not (method == "POST" and path in READ_POSTS) and not self.allow_writes:
            raise ManagerError("Client write mode is disabled")
        data = None if body is None else json.dumps(body).encode("utf-8")
        if data is not None and len(data) > 1_000_000:
            raise ValueError("Request exceeds 1 MB")
        request = Request(self._url + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self._token, "Content-Type": "application/json",
        })
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ManagerError("Response exceeds 4 MB; narrow the request")
            result = json.loads(raw)
        except HTTPError as exc:
            raise ManagerError("Manager HTTP request failed (%s)" % exc.code) from None
        except (URLError, OSError, ValueError):
            raise ManagerError("Manager connection or JSON response failed") from None
        if not isinstance(result, dict) or result.get("ok") is not True or "data" not in result:
            raise ManagerError("Manager returned an invalid or unsuccessful response")
        return result["data"]

    def status(self):
        return self.request("/api/status")

    def health(self):
        return self.request("/api/health")

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

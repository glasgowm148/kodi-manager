"""Run the real dashboard against a fake, in-memory Kodi for screenshots and design review.

    python3 scripts/demo_server.py [--port 8770] [--playing] [--read-only] [--profile Kids]
                                   [--now 2026-10-11T12:00:00]

Serves ../web on 127.0.0.1 only and prints a sign-in link with a fixed demo token. All data is
synthetic: 7 days of metrics history, a few failing home rows, an account about to expire, a
nightly-checkpoint timeline and made-up add-ons. Nothing here talks to Kodi, the LAN or the internet,
and the script is not part of the Kodi add-on. ``--now`` freezes the clock (with ``TZ=UTC`` the
data are then identical on every run), which the browser tests in e2e/ use for screenshots.

Toggles while it runs (no token needed, loopback only):
    /demo/playback   start or stop the fake playback
    /demo/writes     switch between "changes allowed" and view-only
    /demo/profile    switch between the Living room and Kids profiles
"""
import argparse
import calendar
import json
import math
import random
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

WEB = Path(__file__).resolve().parents[1] / "web"
TOKEN = "demo-token-0000"
VERSION = "0.7.11-demo"
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; "
       "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'")
TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css", ".js": "application/javascript"}
HOSTS = ("TorBox", "Trakt", "TMDb")
TITLES = ["The Lighthouse Keepers", "Paper Planets", "Northern Line", "A Quiet Harbour", "Copper Canyon", "Mabel and the Moon",
          "The Long Field", "Signal Fires", "Tidewater", "The Glasshouse", "Small Hours", "Orchard Road", "Kite Season",
          "The Last Ferry", "Blue Marble", "Fox and Fern", "Night Market", "Snowline"]
ROWS = [("Continue watching", "plugin.video.pov", "progress"), ("Trending movies", "plugin.video.pov", "trending"),
        ("Popular shows", "plugin.video.themoviedb.helper", "popular_tv"), ("Family movie night", "plugin.video.pov", "family"),
        ("New releases", "plugin.video.pov", "new"), ("Top rated", "plugin.video.themoviedb.helper", "top_rated"),
        ("Watchlist", "plugin.video.pov", "watchlist"), ("Animation", "plugin.video.themoviedb.helper", "animation"),
        ("Documentaries", "plugin.video.pov", "docs"), ("Award winners", "plugin.video.themoviedb.helper", "awards"),
        ("Next episodes", "plugin.video.pov", "next"), ("Kids TV", "plugin.video.pov", "kids_tv"),
        ("Comedy", "plugin.video.themoviedb.helper", "comedy"), ("Recently added", "plugin.video.pov", "recent")]
ADDONS = [("skin.bingie", "Bingie", "2.0.2"), ("plugin.video.pov", "POV", "6.3.1"),
          ("plugin.video.themoviedb.helper", "TMDb Helper", "6.9.0"), ("script.module.cocoscrapers", "CocoScrapers Module", "1.0.31"),
          ("script.skinshortcuts", "Skin Shortcuts", "2.0.3"), ("script.trakt", "Trakt", "3.6.1"),
          ("service.kodi.addonadmin", "Kodi Manager", VERSION), ("pvr.iptvsimple", "PVR IPTV Simple Client", "21.8.5"),
          ("plugin.video.youtube", "YouTube", "7.1.0"), ("script.module.requests", "Requests", "2.31.0")]


def source(addon, mode, label=None):
    name = label or mode.replace("_", " ").capitalize()
    return "plugin://%s/?mode=%s&name=%s" % (addon, mode, quote_plus(name))


class Demo:
    def __init__(self, playing, writes, profile, now=None):
        self.fixed = now
        self.now = int(now if now is not None else time.time())
        self.playing, self.writes, self.profile = playing, writes, profile
        self.rng = random.Random(7)
        self.history = self._history()
        self.backups = self._backups()
        self.saved_rows = [{"id": "r1", "label": "Family movie night", "source": source("plugin.video.pov", "family", "Family movie night"), "pages": 2, "hide_watched": True},
                           {"id": "r2", "label": "Kids TV", "source": source("plugin.video.pov", "kids_tv", "Kids TV"), "pages": 1, "hide_watched": False},
                           {"id": "r3", "label": "Weekend picks", "source": source("plugin.video.pov", "weekend"), "pages": 1, "hide_watched": False}]
        self.revision = "rev-1"

    def clock(self):
        """The current time: frozen with --now, otherwise the real clock."""
        return self.fixed if self.fixed is not None else time.time()

    # --- synthetic history -----------------------------------------------------------------
    def _history(self):
        rng, now, step = self.rng, self.now, 900
        start = now - 7 * 86400 + step
        t, cols = [], {k: [] for k in ("memory_available_mb", "memory_total_mb", "kodi_mb", "swap_used_pct",
                                         "rows_cached", "rows_failing", "rows_persistent", "network_status")}
        latency = {h: [] for h in HOSTS}
        for stamp in range(start - start % step, now, step):
            local = time.localtime(stamp)
            # Evenings in front of the TV: nothing is sampled while something plays.
            if 19 <= local.tm_hour < 22 and local.tm_yday % 3 != 0:
                continue
            if rng.random() < 0.03:
                continue
            hours_ago = (now - stamp) / 3600.0
            daily = math.sin((local.tm_hour + local.tm_min / 60) / 24 * 2 * math.pi)
            free = 1250 + 260 * daily + rng.uniform(-60, 60)
            if 44 < hours_ago < 47:
                free = 240 + rng.uniform(0, 60)        # a low-memory spell two days ago
            kodi = 520 + 120 * (local.tm_hour / 24) + rng.uniform(-20, 20)
            t.append(stamp)
            cols["memory_available_mb"].append(int(free))
            cols["memory_total_mb"].append(2900)
            cols["kodi_mb"].append(int(kodi))
            cols["swap_used_pct"].append(int(35 + 20 * (local.tm_hour / 24)))
            failing = 2 if hours_ago < 9 else (1 if 30 < hours_ago < 33 else 0)
            cols["rows_cached"].append(14 if hours_ago < 100 else 12)
            cols["rows_failing"].append(failing)
            cols["rows_persistent"].append(1 if hours_ago < 4 else 0)
            probe = rng.random() < 0.8
            status = None
            for host, base in zip(HOSTS, (310, 220, 140)):
                if not probe:
                    latency[host].append(None)
                    continue
                timed_out = host == "Trakt" and rng.random() < 0.02
                spike = 5 if rng.random() < 0.01 else 1
                latency[host].append(None if timed_out else int(base * spike + rng.uniform(-40, 60)))
                status = "warning" if timed_out or status == "warning" else "ok"
            cols["network_status"].append(status if probe else None)
        return {"t": t, "cols": cols, "latency": latency}

    def history_payload(self, days):
        since = self.now - days * 86400
        keep = [i for i, stamp in enumerate(self.history["t"]) if stamp >= since]
        pick = lambda values: [values[i] for i in keep]  # noqa: E731
        hosts = [h for h in HOSTS if any(self.history["latency"][h][i] is not None for i in keep)]
        return {"resolution_seconds": 900, "retention_days": 7, "days": days, "now": self.now, "count": len(keep),
                "series": dict({"t": pick(self.history["t"])}, **{k: pick(v) for k, v in self.history["cols"].items()}),
                "latency_ms": {h: pick(self.history["latency"][h]) for h in hosts}, "hosts": hosts,
                "kodi_starts": [t for t in (self.now - 3 * 86400 - 7000, self.now - 5 * 3600 - 1200) if t >= since]}

    def _backups(self):
        items = []
        for day in range(0, 30):
            if day in (4, 5, 11, 19):
                continue                               # nights the TV was busy or off
            stamp = self.now - day * 86400
            local = time.localtime(stamp)
            at = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 3, 12 + day % 30, 5, 0, 0, -1))
            if at > self.now:
                continue
            items.append(self._backup(at, "nightly"))
        for days_ago, hour in ((2, 20), (9, 18), (16, 11)):
            items.append(self._backup(self.now - days_ago * 86400 - hour * 60, "manual"))
        items.append(dict(self._backup(self.now - 6 * 86400, ""), kind="pipeline"))
        items.sort(key=lambda b: b["timestamp"], reverse=True)
        return items

    def _backup(self, at, note):
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(at))
        return {"backup_id": stamp + "-" + "%032x" % self.rng.getrandbits(128), "timestamp": stamp, "note": note,
                "kind": "stack", "component_count": 7, "skipped_count": 1 if note == "manual" else 0,
                "included_folders": [a[0] for a in ADDONS[:7]], "total_bytes": 1_800_000 + self.rng.randint(0, 900_000),
                "Kodi version": "22.0"}

    # --- current state -----------------------------------------------------------------------
    def stack(self):
        return {"skin": {"addon_id": "skin.bingie", "name": "Bingie", "version": "2.0.2", "bingie_like": True, "found": True, "active": True, "installed": True, "enabled": True, "config_present": True},
                "tmdbhelper": {"addon_id": "plugin.video.themoviedb.helper", "name": "TMDb Helper", "version": "6.9.0", "installed": True, "enabled": True, "config_present": True, "found": True},
                "pov": {"addon_id": "plugin.video.pov", "name": "POV", "version": "6.3.1", "installed": True, "enabled": True, "config_present": True, "found": True},
                "cocoscrapers": {"addon_id": "script.module.cocoscrapers", "name": "CocoScrapers Module", "version": "1.0.31", "installed": True, "enabled": True, "config_present": True, "found": True},
                "fenlight": {}, "fen": {},
                "trakt": {"addon_id": "script.trakt", "installed": True, "enabled": True, "config_present": True},
                "trakt_integration": {"status": "configured", "refs_found": 3, "providers": [{"name": "POV", "addon_id": "plugin.video.pov", "status": "configured"}]},
                "warnings": []}

    def status(self):
        return {"service_version": VERSION, "Kodi version": "22.0", "server": {"host": "127.0.0.1", "port": 0},
                "write_enabled": self.writes, "allow_lan": True, "current_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(self.clock())),
                "active_skin": {"addon_id": "skin.bingie", "name": "Bingie", "version": "2.0.2"}, "platform": "Demo", "stack": self.stack()}

    def cache_entries(self):
        out = []
        for i, (label, addon, mode) in enumerate(ROWS):
            failures = {3: 4, 8: 1}.get(i, 0)
            items = 0 if i == 13 else 20 + (i * 7) % 30
            age = {3: 9 * 3600, 8: 5 * 3600, 5: 30 * 3600}.get(i, 600 + i * 900)
            preview = [{"title": TITLES[(i * 3 + k) % len(TITLES)], "poster": ""} for k in range(6)] if items else []
            health = {"failures": failures, "last_failure": self.now - 1800, "reason": "unavailable" if i == 3 else "unexpected_empty",
                      "retry_at": self.now + 480} if failures else {}
            where = [["Home"], ["Movies hub"], ["TV shows hub"], ["Home", "Movies hub"]][i % 4]
            out.append({"source": source(addon, mode, label), "items": items, "age_seconds": age, "fetched_at": self.now - age,
                        "stale": i in (5, 9), "progress": mode in ("progress", "next"), "health": health, "preview": preview,
                        "title": label, "addon_name": "TMDb Helper" if "helper" in addon else "POV", "where": where,
                        "title_from": "skin" if i % 3 else "path"})
        return out

    def accounts_now(self):
        return [{"id": "trakt", "label": "Trakt sign-in (POV)", "status": "ok", "days_left": 61, "renews": True,
                 "detail": "Signed in · renews automatically (current sign-in valid 61 more days)"},
                {"id": "torbox", "label": "TorBox subscription", "status": "warning", "days_left": 9,
                 "detail": "Active until %s (9 days). Renew soon so streams keep working." % time.strftime("%Y-%m-%d", time.localtime(self.now + 9 * 86400))}]

    def overview(self):
        last = self.backups[0]
        return {"generated_at": self.now, "service_version": VERSION, "kodi_version": "22.0", "profile": self.profile,
                "write_enabled": self.writes,
                "playback": {"active": True, "type": "video", "title": "Paper Planets: The Comet", "media": "episode"} if self.playing else {"active": False, "type": "", "title": ""},
                "memory": {"status": "ok", "pressure": "ok", "detail": "Kodi uses 612 MB · 1180 MB of 2900 MB free · swap 96% used. Nearly full swap is normal on Android while enough memory is free.", "kodi_mb": 612, "available_mb": 1180, "total_mb": 2900, "swap_used_pct": 96},
                "kodi_started_at": self.now - 5 * 3600 - 1200,
                "internet": {"status": "ok", "detail": "TorBox 0.3s · Trakt 0.2s · TMDb 0.1s", "checked_at": self.now - 240, "age_seconds": 240, "failed": [],
                             "hosts": [{"name": "TorBox", "seconds": 0.312}, {"name": "Trakt", "seconds": 0.205}, {"name": "TMDb", "seconds": 0.141}]},
                "rows": {"cached": 14, "failing": 2, "persistent": 1, "stale": 2, "empty": 1},
                "backups": {"count": len([b for b in self.backups if b["kind"] == "stack"]), "last": {k: last.get(k) for k in ("backup_id", "timestamp", "note", "total_bytes")},
                            "times": [b["timestamp"] for b in self.backups if b["kind"] == "stack"], "nightly": {"status": "ok", "at": self.now - 9 * 3600}},
                "protection": {"fixes": {"healthy": True, "bundled": True, "attention": 0, "groups": 3}, "baseline": {"total": 6, "drifted": 0, "labels": []}},
                "accounts": self.accounts_now()}

    def health(self):
        checks = [{"id": "jsonrpc", "label": "Kodi JSON-RPC", "status": "ok", "detail": "22.0"},
                  {"id": "stack", "label": "Core stack", "status": "ok", "detail": "4/6 detected"},
                  {"id": "addon_data", "label": "Addon config path", "status": "ok", "detail": "/storage/.kodi/userdata/addon_data"},
                  {"id": "write_mode", "label": "Write mode", "status": "ok" if self.writes else "warning", "detail": "enabled" if self.writes else "disabled"},
                  {"id": "memory", "label": "Memory", "status": "ok", "detail": "Kodi uses 612 MB · 1180 MB of 2900 MB free · swap 41% used"},
                  {"id": "internet", "label": "Internet (add-on services)", "status": "ok", "detail": "TorBox 0.3s · Trakt 0.2s · TMDb 0.1s · checked 4 min ago"},
                  {"id": "baseline", "label": "Protected settings", "status": "ok", "detail": "6 settings as you set them"}]
        checks += [{"id": a["id"], "label": a["label"], "status": a["status"], "detail": a["detail"]} for a in self.accounts_now()]
        checks += [{"id": "nightly", "label": "Nightly checkpoint", "status": "ok", "detail": "Last taken today 03:12"},
                   {"id": "logs", "label": "Kodi log scan", "status": "warning", "detail": "0 errors · 3 warnings in last 200 lines"}]
        return {"status": "warning", "checks": checks,
                "stats": {"addons": len(ADDONS), "enabled_addons": len(ADDONS) - 1, "config_folders": 7, "stack_detected": 4, "kodi_log_errors": 0, "kodi_log_warnings": 3, "kodi_memory_mb": 612},
                "recent_errors": [], "recent_warnings": ["warning <general>: Skin has invalid include: DemoInclude", "warning <general>: Texture not found: demo.png", "warning <general>: Slow directory listing (2.1 s)"]}

    def addons(self):
        return [{"addon_id": aid, "name": name, "version": ver, "installed": True, "enabled": aid != "plugin.video.youtube",
                 "config_present": aid not in ("script.module.requests",)} for aid, name, ver in ADDONS]

    def settings(self, aid):
        name = dict((a, n) for a, n, _ in ADDONS).get(aid, aid)
        return {"addon_id": aid, "name": name, "adapter": "generic", "editable": True, "read_only_reason": "", "warnings": [],
                "groups": [{"label": "Playback", "settings": [
                    {"id": "auto_play", "label": "Play the first source automatically", "type": "bool", "value": "true", "default": "false", "default_known": True, "options": [], "editable": True, "masked": False, "description": "Start playing without showing the source list."},
                    {"id": "results.quality", "label": "Highest quality", "type": "select", "value": "1080p", "default": "4K", "default_known": True, "options": [{"value": "4K", "label": "4K"}, {"value": "1080p", "label": "1080p"}, {"value": "720p", "label": "720p"}], "editable": True, "masked": False, "description": "Sources above this quality are hidden."},
                    {"id": "timeout", "label": "Source search timeout", "type": "integer", "value": "20", "default": "20", "default_known": True, "options": [], "editable": True, "masked": False, "description": "Seconds to wait for sources."}]},
                    {"label": "Accounts", "settings": [
                        {"id": "tb.token", "label": "TorBox API key", "type": "text", "value": "demo-not-a-real-key", "default": "", "default_known": True, "options": [], "editable": True, "masked": False, "description": "TorBox access token used by this add-on."},
                        {"id": "trakt.user", "label": "Trakt user", "type": "text", "value": "demo-user", "default": "", "default_known": True, "options": [], "editable": False, "masked": False, "description": "Linked Trakt account."}]}]}

    def layout(self):
        def rows(section, labels):
            return [{"id": "%s-%d" % (section, i), "label": label, "path": source("plugin.video.pov", label.lower().replace(" ", "_")), "action": ""} for i, label in enumerate(labels)]
        sections = [{"id": "hub:movies", "label": "Movies", "kind": "hub", "editable": self.writes, "rows": rows("movies", ["Trending movies", "New releases", "Family movie night", "Top rated"])},
                    {"id": "hub:tvshows", "label": "Shows", "kind": "hub", "editable": self.writes, "rows": rows("tv", ["Next episodes", "Popular shows", "Kids TV"])},
                    {"id": "home", "label": "Home", "kind": "home", "editable": self.writes, "rows": rows("home", ["Continue watching", "Watchlist", "Recently added"])}]
        return {"revision": self.revision, "sections": sections, "inactive_sections": [], "max_rows": 20, "can_apply": self.writes,
                "new_section_available": False, "new_section_reasons": ["The skin's Custom hub is already used by Favourites."],
                "customhub_occupied": True, "customhub_menu_labels": ["Favourites"], "reasons": [] if self.writes else ["Write Mode is disabled. Enable it in Kodi Manager service settings to apply this layout."]}

    def media(self, n=12, seed=0):
        return [{"label": TITLES[(seed + k) % len(TITLES)], "title": TITLES[(seed + k) % len(TITLES)], "year": 2015 + (seed + k) % 10,
                 "mpaa": ["U", "PG", "12A"][(seed + k) % 3], "genre": ["Drama"], "type": "movie", "classification": "media",
                 "file": "plugin://plugin.video.pov/?demo=%d" % k, "art": {}} for k in range(n)]


def make_handler(demo):
    class Handler(BaseHTTPRequestHandler):
        server_version = "KodiManagerDemo"

        def log_message(self, fmt, *args):
            pass

        def send(self, status, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(data)

        def ok(self, data):
            self.send(200, {"ok": True, "data": data})

        def fail(self, status, code, message):
            self.send(status, {"ok": False, "code": code, "error": {"code": code, "message": message, "details": {}}})

        def do_GET(self):
            self.route("GET")

        def do_POST(self):
            self.route("POST")

        def do_PATCH(self):
            self.route("PATCH")

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(length) or b"{}") if length else {}
            except ValueError:
                return {}

        def route(self, method):
            parts = urlsplit(self.path)
            path, query = parts.path, parse_qs(parts.query)
            if path.startswith("/demo/"):
                return self.toggle(path)
            if not path.startswith("/api/"):
                return self.static(path)
            if self.headers.get("Authorization") != "Bearer " + TOKEN:
                return self.fail(401, "unauthorized", "Missing or invalid bearer token")
            body = self.body() if method != "GET" else {}
            try:
                result = self.api(method, path, query, body)
            except PermissionError:
                return self.fail(403, "write_disabled", "Write Mode is disabled")
            except LookupError as exc:
                return self.fail(exc.args[0], exc.args[1], exc.args[2])
            if result is None:
                return self.fail(404, "not_found", "Route not found")
            self.ok(result)

        def toggle(self, path):
            if path == "/demo/playback":
                demo.playing = not demo.playing
            elif path == "/demo/writes":
                demo.writes = not demo.writes
            elif path == "/demo/profile":
                demo.profile = "Kids" if demo.profile != "Kids" else "Living room"
            self.send(200, ("Demo state: playing=%s, writes=%s, profile=%s. Go back and refresh the dashboard.\n"
                            % (demo.playing, demo.writes, demo.profile)).encode(), "text/plain; charset=utf-8")

        def static(self, path):
            name = "index.html" if path in ("/", "") else unquote(path).lstrip("/")
            target = (WEB / name).resolve()
            if WEB.resolve() not in target.parents or not target.is_file():
                return self.fail(404, "not_found", "File not found")
            self.send(200, target.read_bytes(), TYPES.get(target.suffix, "application/octet-stream"))

        def write(self, playback_message=None, status=400):
            if not demo.writes:
                raise PermissionError()
            if playback_message and demo.playing:
                raise LookupError(status, "playback_active", playback_message)

        def api(self, method, path, query, body):
            d = demo
            if method == "GET":
                simple = {"/api/status": d.status, "/api/overview": d.overview, "/api/health": d.health, "/api/addons": d.addons,
                          "/api/stack": d.stack}
                if path in simple:
                    return simple[path]()
                if path == "/api/metrics/history":
                    days = (query.get("days") or ["7"])[0]
                    if not days.isdigit() or not 1 <= int(days) <= 7:
                        raise LookupError(400, "bad_request", "days must be a whole number from 1 to 7")
                    return d.history_payload(int(days))
                if path == "/api/backups/timeline":
                    return {"items": d.backups, "count": len(d.backups)}
                if path == "/api/stack/backups":
                    return {"backups": [b for b in d.backups if b["kind"] == "stack"]}
                if path == "/api/fixes":
                    return {"healthy": True, "bundled": True, "repairable": False, "detail": "3 groups checked against their tested copies.",
                            "groups": [{"label": "POV playback", "status": "ok", "installed_version": "6.3.1", "tested_version": "6.3.1"},
                                       {"label": "Bingie navigation", "status": "ok", "installed_version": "2.0.2", "tested_version": "2.0.2"},
                                       {"label": "TMDb Helper widgets", "status": "ok", "installed_version": "6.9.0", "tested_version": "6.9.0"}]}
                if path == "/api/widget-cache":
                    return {"root": "/demo/widget_cache", "entries": d.cache_entries(), "queued": 1}
                if path == "/api/widget-cache/rows":
                    return [dict(r, widget_url="plugin://service.kodi.addonadmin/?mode=cached&source=" + r["id"]) for r in d.saved_rows]
                if path == "/api/widget-cache/url":
                    return {"url": "plugin://service.kodi.addonadmin/?mode=cached&demo=1"}
                if path == "/api/accounts":
                    return {"summary": {"trakt": {"status": "configured", "refs_found": 3}, "torbox": {"status": "configured", "refs_found": 1}, "tmdb": {"status": "unknown", "message": "Uses the add-on's built-in key."}},
                            "groups": [{"label": "TorBox", "settings": [{"component": "plugin.video.pov", "id": "tb.token", "source": "settings.xml", "label": "TorBox API key", "type": "text", "value": "demo-not-a-real-key", "editable": True}]},
                                       {"label": "Trakt", "settings": [{"component": "plugin.video.pov", "id": "trakt.user", "source": "settings.xml", "label": "Trakt user", "type": "text", "value": "demo-user", "editable": False}]}], "notes": []}
                if path == "/api/pipeline":
                    return self.pipeline()
                if path in ("/api/pipeline/debug", "/api/debug/paths", "/api/debug/stack-raw", "/api/integrations"):
                    return {"demo": True, "note": "Synthetic diagnostics"}
                if path == "/api/logs":
                    clock = time.strftime("%H:%M:%S", time.localtime(d.clock()))
                    return {"lines": ["%s Demo service started" % clock, "%s Widget cache refreshed 3 rows, 1 changed" % clock]}
                if path == "/api/kodi/logs":
                    return {"lines": ["info <general>: Starting Kodi (22.0)", "warning <general>: Texture not found: demo.png", "error <general>: Demo error line for the log view", "info <general>: Demo finished loading"]}
                if path == "/api/search/config":
                    q = (query.get("q") or [""])[0].lower()
                    results = [dict(s, addon_id="plugin.video.pov", addon_name="POV", version="6.3.1", group=g["label"]) for g in d.settings("plugin.video.pov")["groups"] for s in g["settings"] if q in (s["id"] + s["label"]).lower()]
                    return {"query": q, "count": len(results), "results": results}
                if path == "/api/widgets/sources":
                    return {"sources": [{"addon_id": "plugin.video.pov", "label": "POV", "path": "plugin://plugin.video.pov/", "enabled": True, "traversable": True},
                                        {"addon_id": "plugin.video.themoviedb.helper", "label": "TMDb Helper", "path": "plugin://plugin.video.themoviedb.helper/", "enabled": True, "traversable": True}]}
                if path == "/api/widgets/layout":
                    return d.layout()
                if path.startswith("/api/addons/"):
                    rest = path[len("/api/addons/"):]
                    if rest.endswith("/settings"):
                        return d.settings(unquote(rest[:-len("/settings")]))
                    if rest.endswith("/backups"):
                        return {"backups": [{"backup_id": "20261009-101500-demo", "timestamp": "20261009-101500", "addon_version": "6.3.1", "files_copied": 4}]}
                    return dict(d.addons()[0], warnings=[], related={})
                return None
            if path == "/api/widgets/browse":
                return {"status": "ok", "items": d.media(18, len(body.get("path", ""))), "children": [], "skips": [], "classification": "media", "can_use_as_widget": True}
            if path == "/api/widgets/row-preview":
                return {"status": "ok", "items": d.media(12, len(body.get("row_id", "")))}
            if path == "/api/widgets/suggestions":
                return {"rows": [{"label": "Family movie night", "path": source("plugin.video.pov", "family"), "filtered": True}]}
            if path == "/api/widgets/layout/preview":
                return dict(d.layout(), can_apply=d.writes, reasons=[])
            if path == "/api/playback/test":
                return {"ok": True, "dry_run": True, "steps": [{"step": "Kodi service reachable", "ok": True, "detail": "22.0"}, {"step": "Current player state", "ok": True, "detail": "active players: %d" % int(d.playing)}]}
            if path == "/api/widget-cache/refresh":
                return {"queued": 14}
            if path == "/api/pipeline/rescan":
                return self.pipeline()
            # Everything else changes something.
            if path == "/api/stack/backup":
                self.write("Stop playback before taking a checkpoint", 409)
                item = d._backup(d.clock(), "manual")
                d.backups.insert(0, item)
                return item
            if path in ("/api/stack/restore",) or path.endswith("/restore"):
                if not body.get("force"):
                    self.write("Stop playback before restoring a backup", 409)
                else:
                    self.write()
                return {"restored": ["plugin.video.pov"], "skipped": [], "undo_backups": {"plugin.video.pov": "20261011-120000-undo"}, "restart_required": False}
            if path in ("/api/widgets/layout/rebuild", "/api/fixes/repair", "/api/addons/install"):
                self.write("Stop playback before doing that")
                return {"started": True, "opened": True, "next_step": "Choose the ZIP on the TV.", "detail": "Nothing needed restoring."}
            if path == "/api/baseline/apply":
                self.write("Stop playback before re-applying protected settings", 409)
                return {"applied": [], "failed": [], "restart_required": False}
            self.write()
            if method == "PATCH":
                return {"changed_count": len(body.get("changes") or []), "backup_id": "20261011-120000-demo", "warnings": []}
            if path == "/api/widgets/layout/apply":
                return {"applied": True, "backup_id": "20261011-120000-layout"}
            return {"backup_id": "20261011-120000-demo", "removed": True}

        def pipeline(self):
            return {"nodes": [{"id": "skin", "label": "Skin", "name": "Bingie", "status": "active"}, {"id": "helper", "label": "Metadata helper", "name": "TMDb Helper", "status": "enabled"},
                              {"id": "player", "label": "Player", "name": "POV", "status": "enabled", "relationship": "selected"}, {"id": "kodi_player", "label": "Kodi player", "status": "built in"}],
                    "edges": [{"from": "helper", "to": "player", "label": "Plays through", "relationship": "player file", "evidence": ["players/pov.json"]}],
                    "routing": {"movie_player": {"value": "POV", "addon_id": "plugin.video.pov", "source": "players/pov.json", "setting_id": "", "confidence": "high", "editable": False}},
                    "summary": {"primary_player": {"addon_id": "plugin.video.pov", "name": "POV", "selection": "player file", "confidence": "high"}, "secondary_players": [],
                                "scraper_module": {"name": "CocoScrapers", "relationship": "external scrapers", "used": True, "evidence": ["provider.external"], "found": True, "addon_id": "script.module.cocoscrapers"},
                                "helper": {"addon_id": "plugin.video.themoviedb.helper"}, "health": {"warnings": []}, "available_scraper_modules": [{"name": "CocoScrapers", "installed": True, "enabled": True}],
                                "integrations": {"trakt": {"status": "configured", "refs_found": 3}, "torbox": {"status": "configured", "refs_found": 1}, "tmdb": {"status": "unknown"}}},
                    "settings_groups": [], "discovery": {"demo": True}}
    return Handler


def frozen_time(value):
    if value.replace(".", "", 1).isdigit():
        return float(value)
    try:
        return float(calendar.timegm(time.strptime(value.rstrip("Z"), "%Y-%m-%dT%H:%M:%S")))
    except ValueError:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DDTHH:MM:SS or Unix seconds") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument("--playing", action="store_true", help="start with something playing")
    parser.add_argument("--read-only", action="store_true", help="start view-only (writes off), like a Kids profile")
    parser.add_argument("--profile", default="Living room")
    parser.add_argument("--now", type=frozen_time, help="freeze the clock at this UTC time (YYYY-MM-DDTHH:MM:SS) or Unix time")
    args = parser.parse_args()
    demo = Demo(args.playing, not args.read_only, args.profile, args.now)
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(demo))
    base = "http://127.0.0.1:%d" % httpd.server_address[1]
    print("Kodi Manager demo (synthetic data only)")
    print("Demo token: %s" % TOKEN)
    print("Open: %s/#token=%s" % (base, TOKEN))
    print("Toggles: %s/demo/playback  %s/demo/writes  %s/demo/profile" % (base, base, base), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

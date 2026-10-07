"""Warn before an account problem shows up as a failed playback.

* Trakt: POV keeps the sign-in expiry in its settings and renews it while it
  works; a sign-in that stays expired means renewal failed.
* TorBox: asks TorBox for the subscription end date with the token POV holds
  (once or twice a day). The token never leaves the device except to TorBox.
"""
import json
import os
import ssl
import time
from datetime import datetime

try:
    from urllib.request import Request, urlopen
except ImportError:  # pragma: no cover
    Request = urlopen = None

DAY = 86400
TORBOX_WARN_DAYS = 14
_CERTIFI = ("special://home/addons/script.module.certifi/lib/certifi/cacert.pem",)


def _days(seconds):
    return int(seconds // DAY)


def trakt_status(get_setting, now=None, addon="plugin.video.pov"):
    now = time.time() if now is None else now
    try:
        token = get_setting(addon, "trakt.token")
        expires = get_setting(addon, "trakt.expires")
        user = get_setting(addon, "trakt_user") or get_setting(addon, "trakt.user")
    except Exception:
        return None
    if not token:
        return None   # Trakt is not set up in this add-on
    try:
        expires = float(expires or 0)
    except ValueError:
        expires = 0
    label = "Trakt sign-in (%s)" % ("POV" if addon == "plugin.video.pov" else addon)
    who = " as %s" % user if user else ""
    if not expires:
        return {"id": "trakt", "label": label, "status": "ok", "detail": "Signed in%s" % who}
    if expires > now:
        return {"id": "trakt", "label": label, "status": "ok",
                "detail": "Signed in%s · renews automatically (current sign-in valid %s more days)" % (who, _days(expires - now))}
    late = now - expires
    if late < DAY:
        return {"id": "trakt", "label": label, "status": "ok",
                "detail": "Signed in%s · sign-in renewal due now" % who}
    return {"id": "trakt", "label": label, "status": "warning",
            "detail": "The Trakt sign-in expired %s days ago and was not renewed. Open POV → Settings → Accounts and sign in to Trakt again." % _days(late)}


def _ssl_context(translate):
    context = ssl.create_default_context()
    for candidate in _CERTIFI:
        path = translate(candidate)
        if path and os.path.exists(path):
            try:
                context.load_verify_locations(path)
            except (OSError, ssl.SSLError):
                pass
    return context


def torbox_status(get_setting, translate=lambda p: p, now=None, fetch=None, addon="plugin.video.pov"):
    now = time.time() if now is None else now
    try:
        token = get_setting(addon, "tb.token")
        enabled = get_setting(addon, "tb.enabled")
    except Exception:
        return None
    if not token or str(enabled).lower() == "false":
        return None
    label = "TorBox subscription"
    try:
        if fetch is None:
            request = Request("https://api.torbox.app/v1/api/user/me",
                              headers={"Authorization": "Bearer %s" % token, "User-Agent": "KodiManager"})
            response = urlopen(request, timeout=15, context=_ssl_context(translate))
            data = json.loads(response.read().decode("utf-8"))
        else:
            data = fetch(token)
    except Exception as exc:
        return {"id": "torbox", "label": label, "status": "warning",
                "detail": "Could not reach TorBox to check the account (%s)" % type(exc).__name__}
    info = data.get("data") if isinstance(data, dict) else None
    if not isinstance(info, dict) or not data.get("success"):
        return {"id": "torbox", "label": label, "status": "warning",
                "detail": "TorBox did not accept the token POV has. Sign in to TorBox again in POV's account settings."}
    stamp = str(info.get("premium_expires_at") or "")
    try:
        expires = datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
        expires = (expires - datetime(1970, 1, 1)).total_seconds()
    except ValueError:
        return {"id": "torbox", "label": label, "status": "ok", "detail": "Account active"}
    left = expires - now
    if left <= 0:
        return {"id": "torbox", "label": label, "status": "error",
                "detail": "The TorBox subscription ended on %s. Streams will fail until it is renewed." % stamp[:10]}
    status = "warning" if left < TORBOX_WARN_DAYS * DAY else "ok"
    detail = "Active until %s (%s days)" % (stamp[:10], _days(left))
    if status == "warning":
        detail += ". Renew soon so streams keep working."
    return {"id": "torbox", "label": label, "status": status, "detail": detail}

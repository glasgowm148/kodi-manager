"""Credential-presence summaries. No remote validation or values in evidence.

API additions shared by stack.trakt_integration and pipeline.summary.integrations:
status: configured|unknown|not found; verified: always False; providers: records
with addon_id/name/status/evidence. Evidence has setting_id/source/configured;
refs is the flattened evidence list and refs_found its count. A configured
record proves only locally stored user credentials, not successful API access.
"""


def credential_present(value):
    if value is None or value is False:
        return False
    return str(value).strip().lower() not in (
        "", "0", "false", "none", "null", "undefined", "empty_setting", "not set", "n/a", "{}", "[]",
    )


def account_provider(setting_id, component=""):
    sid = (setting_id or "").lower()
    if "trakt" in sid or component == "script.trakt":
        return "trakt"
    if "torbox" in sid or sid.startswith("tb."):
        return "torbox"
    if "tmdb" in sid or (component in ("plugin.video.themoviedb.helper", "plugin.video.tmdb.bingie.helper") and sid == "api_key"):
        return "tmdb"
    if any(word in sid for word in ("debrid", "premiumize")) or sid.startswith(("rd.", "ad.", "pm.", "ed.", "oc.")):
        return "debrid"
    return ""


def is_auth_field(setting_id):
    sid = (setting_id or "").lower()
    # Client credentials identify an application, not a linked user account.
    if any(word in sid for word in ("client", "enabled", "expires", "scrobble", "indicator", "calendar", "sync", "widget", "list", "rating")):
        return False
    return any(word in sid for word in ("token", "refresh", "authorization", "password", "api", "secret"))


def summarize_account(groups, key):
    providers = {}
    for group in groups:
        component = group.get("component", "")
        for setting in group.get("settings", []):
            sid = setting.get("id", "")
            if account_provider(sid, component) != key or not is_auth_field(sid):
                continue
            provider = providers.setdefault(component, {"addon_id": component, "name": group.get("label") or component, "status": "unknown", "evidence": []})
            configured = bool(setting.get("configured", credential_present(setting.get("value"))))
            provider["evidence"].append({"setting_id": sid, "source": setting.get("source", "settings.xml"), "configured": configured})
            if configured:
                provider["status"] = "configured"
    refs = [e for provider in providers.values() for e in provider["evidence"]]
    configured = any(provider["status"] == "configured" for provider in providers.values())
    return {"status": "configured" if configured else ("unknown" if refs else "not found"), "verified": False,
            "refs_found": len(refs), "refs": refs[:40], "providers": list(providers.values()),
            "message": "Credentials present locally; account not verified." if configured else "No configured account credentials detected locally."}

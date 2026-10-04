SECRET_WORDS = (
    "token", "trakt", "oauth", "refresh", "access", "secret", "password",
    "passwd", "pin", "api", "key", "client", "auth", "authorization",
    "realdebrid", "debrid", "premiumize", "alldebrid", "easynews",
)

READ_ONLY_TYPES = {
    "action", "folder", "file", "image", "audio", "video", "executable",
    "addon", "addonselector", "separator", "lsep", "label",
}
SAFE_TYPES = {"bool", "boolean", "text", "string", "password", "number", "integer", "int", "slider", "select", "spinner", "enum"}


def is_secret_like(setting_id="", label=""):
    text = ("%s %s" % (setting_id or "", label or "")).lower()
    return any(word in text for word in SECRET_WORDS)


def mask_value(value):
    return "••••••••" if value not in (None, "") else ""


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k] = mask_value(v) if is_secret_like(str(k), "") else redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def is_type_editable(setting_type):
    stype = (setting_type or "").lower()
    if stype in READ_ONLY_TYPES:
        return False
    return stype in SAFE_TYPES


def coerce_value(setting, value):
    stype = (setting.get("type") or "").lower()
    if stype in ("bool", "boolean"):
        if isinstance(value, bool):
            return "true" if value else "false"
        val = str(value).lower()
        if val in ("true", "1", "yes", "on"):
            return "true"
        if val in ("false", "0", "no", "off"):
            return "false"
        raise ValueError("Expected boolean")
    if stype in ("integer", "int", "number", "slider"):
        text = str(value)
        float(text)
        return text
    if stype in ("select", "spinner", "enum"):
        opts = setting.get("options") or []
        if opts and str(value) not in [str(o.get("value", o)) for o in opts]:
            raise ValueError("Value not in options")
        return str(value)
    if stype in ("text", "string", "password"):
        return str(value)
    raise ValueError("Unsupported setting type")


def setting_editable(setting, allow_secret_replacement=False):
    label = setting.get("label") or ""
    sid = setting.get("id") or ""
    if is_secret_like(sid, label):
        return bool(allow_secret_replacement) and is_type_editable(setting.get("type"))
    return is_type_editable(setting.get("type"))

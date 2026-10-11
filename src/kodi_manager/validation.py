import re

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


_QUERY_SECRET = re.compile(r"([?&;](?:token|access_token|auth_token|refresh_token|api_key|apikey|key)=)[^&#\s\"']*", re.I)
_BEARER = re.compile(r"\b(Bearer)\s+[A-Za-z0-9._~+/=-]+", re.I)
_ASSIGNED_SECRET = re.compile(
    r"\b((?:access_|refresh_|auth_|client_|api_)?(?:token|secret|password|passwd|api_?key|apikey|key))"
    r"(\s*[=:]\s*[\"']?)([^\s&\"',;]+)", re.I)
MASK = "••••••••"


def mask_query_secrets(text):
    """Mask token/key query values in a URL or request line (``?token=abc`` -> ``?token=***``)."""
    return _QUERY_SECRET.sub(lambda m: m.group(1) + "***", str(text))


def mask_secrets_in_text(text):
    """Mask secrets embedded in free text: query values, ``Bearer ...`` and ``token=...``."""
    text = mask_query_secrets(text)
    text = _BEARER.sub(lambda m: m.group(1) + " " + MASK, text)
    return _ASSIGNED_SECRET.sub(lambda m: m.group(1) + m.group(2) + (m.group(3) if m.group(3) in ("***", "\u2022" * 8) else MASK), text)


def redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k] = mask_value(v) if is_secret_like(str(k), "") else redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return mask_secrets_in_text(obj)
    return obj


def is_type_editable(setting_type):
    stype = (setting_type or "").lower()
    if stype in READ_ONLY_TYPES:
        return False
    return stype in SAFE_TYPES


def _number_text(value, whole):
    """``value`` as the text Kodi stores for a number; ValueError unless finite (and whole when asked)."""
    if isinstance(value, bool):
        raise ValueError("Expected a number")
    text = str(value).strip()
    if "_" in text:  # Python reads "1_0" as 10; Kodi does not
        raise ValueError("Expected a number")
    try:
        number = float(text)
    except ValueError:
        raise ValueError("Expected a number") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError("Expected a finite number")
    if whole:
        try:
            return str(int(text))
        except ValueError:
            if number.is_integer():
                return str(int(number))
            raise ValueError("Expected a whole number") from None
    return text


def coerce_value(setting, value):
    stype = (setting.get("type") or "").lower()
    if value is None or isinstance(value, (dict, list, tuple)):
        # str() would store "None" or a Python repr in the add-on's settings.
        raise ValueError("Expected a single value")
    if stype in ("bool", "boolean"):
        if isinstance(value, bool):
            return "true" if value else "false"
        val = str(value).lower()
        if val in ("true", "1", "yes", "on"):
            return "true"
        if val in ("false", "0", "no", "off"):
            return "false"
        raise ValueError("Expected boolean")
    if stype in ("integer", "int"):
        return _number_text(value, whole=True)
    if stype in ("number", "slider"):
        return _number_text(value, whole=False)
    if stype in ("select", "spinner", "enum"):
        opts = setting.get("options") or []
        if opts and str(value) not in [str(o.get("value", o)) for o in opts]:
            raise ValueError("Value not in options")
        return str(value)
    if stype in ("text", "string", "password"):
        return str(value)
    raise ValueError("Unsupported setting type")


class SettingValueError(ValueError):
    """A value refused for one setting of a batch. The message starts with the setting id
    (never the value), so a batch save can say which field to fix."""

    def __init__(self, setting_id, message):
        super(SettingValueError, self).__init__("%s: %s" % (setting_id, message))
        self.setting_id = setting_id


def coerce_setting(setting_id, setting, value):
    """coerce_value, raising SettingValueError that names ``setting_id``."""
    try:
        return coerce_value(setting, value)
    except SettingValueError:
        raise
    except ValueError as exc:
        raise SettingValueError(setting_id, exc) from None


def setting_editable(setting, allow_secret_replacement=False):
    label = setting.get("label") or ""
    sid = setting.get("id") or ""
    if is_secret_like(sid, label):
        return bool(allow_secret_replacement) and is_type_editable(setting.get("type"))
    return is_type_editable(setting.get("type"))

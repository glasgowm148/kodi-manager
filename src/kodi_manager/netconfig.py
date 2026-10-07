"""Which address the dashboard listens on (stdlib only; shared by the service and the plugin)."""
import ipaddress

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def is_loopback(host):
    host = str(host or "").strip().strip("[]")
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def effective_host(host, allow_lan):
    """The bind address for the configured host and LAN switch.

    LAN access on with the host left at its loopback default listens on every
    interface; an explicit non-loopback host is kept. LAN access off always
    listens on loopback only.
    """
    host = str(host or "").strip() or DEFAULT_HOST
    if allow_lan:
        return "0.0.0.0" if host == DEFAULT_HOST else host
    return host if is_loopback(host) else DEFAULT_HOST


def parse_int(value, default, low=None, high=None):
    """An int setting, falling back to ``default`` when it is blank, invalid or out of range."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if (low is not None and number < low) or (high is not None and number > high):
        return default
    return number

"""Which address the dashboard listens on (stdlib only; shared by the service and the plugin)."""
import ipaddress
import re

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


_HOSTNAME = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\Z")


def host_allowed(header, bound_host=None):
    """DNS-rebinding defence: may a request carrying this Host header be served?

    Allowed: no Host header (non-browser HTTP/1.0 clients), loopback names
    (``localhost``, ``*.localhost``), mDNS names (``*.local``), any loopback,
    private or link-local IP literal, and the address the dashboard is bound
    to. Every other name is refused: a page on another site that rebinds its
    own name to this TV's address still sends that name.
    """
    value = str(header or "").strip().lower()
    if not value:
        return True
    if value.startswith("["):
        end = value.find("]")
        name, rest = (value[1:end], value[end + 1:]) if end > 0 else ("", "")
        if end < 0 or (rest and not re.fullmatch(r":\d{1,5}", rest)):
            return False
    elif value.count(":") == 1:
        name, port = value.split(":")
        if not re.fullmatch(r"\d{1,5}", port):
            return False
    else:
        name = value  # A name, or a bare IPv6 literal.
    name = name.rstrip(".")
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback or address.is_private or address.is_link_local:
            return True
        bound = str(bound_host or "").strip().strip("[]")
        return _is_ip(bound) and not ipaddress.ip_address(bound).is_unspecified and address == ipaddress.ip_address(bound)
    if not _HOSTNAME.match(name):
        return False
    return name == "localhost" or name.endswith(".localhost") or name.endswith(".local")


def _is_ip(value):
    try:
        ipaddress.ip_address(value)
        return True
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

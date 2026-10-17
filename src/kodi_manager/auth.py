import hashlib
import hmac
import re
import secrets

IDENTITY_CONTEXT = b"kodi-manager-identity-v1:"
_NONCE = re.compile(r"[0-9a-f]{32,128}\Z")


def generate_token():
    return secrets.token_urlsafe(32)


def authorized(header, token):
    if not token:
        return False
    prefix = "Bearer "
    if not header or not header.startswith(prefix):
        return False
    # compare_digest rejects non-ASCII str input with TypeError; compare bytes instead.
    supplied = header[len(prefix):].encode("utf-8", "surrogateescape")
    return secrets.compare_digest(supplied, token.encode("utf-8"))


def identity_proof(token, nonce):
    """HMAC-SHA256 of a client nonce under the token, or None for a malformed nonce.

    Lets a client on the same device check it is talking to this Kodi Manager before it sends the
    token: another app listening on the port while Kodi is stopped cannot compute it. The nonce is
    the client's, fresh per request, so a proof seen earlier is of no use to an impostor.
    """
    if not token or not isinstance(nonce, str) or not _NONCE.match(nonce):
        return None
    return hmac.new(token.encode("utf-8"), IDENTITY_CONTEXT + nonce.encode("ascii"), hashlib.sha256).hexdigest()

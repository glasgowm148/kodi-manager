import secrets


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

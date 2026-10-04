import secrets


def generate_token():
    return secrets.token_urlsafe(32)


def authorized(header, token):
    if not token:
        return False
    prefix = "Bearer "
    return bool(header and header.startswith(prefix) and secrets.compare_digest(header[len(prefix):], token))

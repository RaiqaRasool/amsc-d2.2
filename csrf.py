import secrets


CSRF_SESSION_KEY = "csrf_token"


def new_csrf_token():
    return secrets.token_urlsafe(32)


def csrf_tokens_match(expected, supplied):
    return bool(
        expected
        and supplied
        and secrets.compare_digest(expected, supplied)
    )

from app.github.signature import verify_signature

SECRET = "super-secret"
BODY = b'{"action": "created"}'


def _valid_signature(body: bytes = BODY, secret: str = SECRET) -> str:
    import hashlib
    import hmac

    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_is_accepted() -> None:
    assert verify_signature(BODY, _valid_signature(), SECRET) is True


def test_wrong_secret_is_rejected() -> None:
    assert verify_signature(BODY, _valid_signature(), "wrong-secret") is False


def test_tampered_body_is_rejected() -> None:
    assert verify_signature(b'{"action": "tampered"}', _valid_signature(), SECRET) is False


def test_missing_signature_is_rejected() -> None:
    assert verify_signature(BODY, None, SECRET) is False


def test_malformed_signature_prefix_is_rejected() -> None:
    digest = _valid_signature().removeprefix("sha256=")
    assert verify_signature(BODY, f"sha1={digest}", SECRET) is False


def test_empty_secret_is_rejected() -> None:
    assert verify_signature(BODY, _valid_signature(secret=""), "") is False

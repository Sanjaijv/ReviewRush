import hashlib
import hmac


def verify_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
    """Verify a GitHub webhook's X-Hub-Signature-256 header against the raw body.

    Fails closed: a missing header, a missing/empty secret, or a malformed header
    is always treated as invalid rather than skipped.
    """
    if not signature_header or not secret:
        return False
    if not signature_header.startswith("sha256="):
        return False

    expected_digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided_digest = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected_digest, provided_digest)

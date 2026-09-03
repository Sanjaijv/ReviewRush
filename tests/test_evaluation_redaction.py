from app.evaluation.redaction import pseudonymize_repository_ref, redact_text


def test_redact_text_scrubs_email() -> None:
    text = "Reported by jane.doe@example.com in the PR description"
    redacted = redact_text(text)
    assert "jane.doe@example.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted


def test_redact_text_scrubs_aws_key() -> None:
    text = "aws_key = AKIAABCDEFGHIJKLMNOP"
    redacted = redact_text(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in redacted


def test_redact_text_scrubs_generic_secret_assignment() -> None:
    text = 'api_key: "sk_live_abcdefgh12345678"'
    redacted = redact_text(text)
    assert "sk_live_abcdefgh12345678" not in redacted


def test_redact_text_scrubs_bearer_token() -> None:
    text = "Authorization: Bearer abcdef1234567890ghijk"
    redacted = redact_text(text)
    assert "abcdef1234567890ghijk" not in redacted


def test_redact_text_scrubs_private_key_block() -> None:
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n-----END RSA PRIVATE KEY-----"
    redacted = redact_text(text)
    assert "MIIB" not in redacted


def test_redact_text_leaves_ordinary_code_untouched() -> None:
    text = "def add(a, b):\n    return a + b"
    assert redact_text(text) == text


def test_pseudonymize_repository_ref_is_stable_and_opaque() -> None:
    ref1 = pseudonymize_repository_ref("acme/widgets")
    ref2 = pseudonymize_repository_ref("acme/widgets")
    ref3 = pseudonymize_repository_ref("acme/other")

    assert ref1 == ref2
    assert ref1 != ref3
    assert "acme" not in ref1
    assert "widgets" not in ref1

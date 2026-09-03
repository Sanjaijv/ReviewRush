"""De-identification for the Phase 15 evaluation dataset.

Heuristic and regex-based, matching the level of tooling already in this
codebase (there is no ML-based PII detector here) - not a guarantee of
perfect scrubbing, only a best-effort floor that must run over every row
before it is persisted in `eval_dataset_items`. This is deliberately
conservative: false positives (over-redaction) are safe, false negatives are
not.
"""

import hashlib
import re

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GENERIC_SECRET_RE = re.compile(
    r"""(?ix)
    (secret|token|api[_-]?key|password|passwd|access[_-]?key)
    \s*[:=]\s*
    ["']?[A-Za-z0-9_\-/+=.]{8,}["']?
    """
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{10,}\b")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
)


def redact_text(text: str) -> str:
    """Scrub secret-shaped tokens and email addresses from diff/commit text
    before it can enter the evaluation dataset.
    """
    if not text:
        return text
    redacted = _PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", text)
    redacted = _AWS_KEY_RE.sub("[REDACTED_AWS_KEY]", redacted)
    redacted = _BEARER_RE.sub("Bearer [REDACTED_TOKEN]", redacted)
    redacted = _GENERIC_SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED_SECRET]", redacted)
    redacted = _EMAIL_RE.sub("[REDACTED_EMAIL]", redacted)
    return redacted


def pseudonymize_repository_ref(repository_full_name: str) -> str:
    """Replace a real `owner/name` with a stable, non-reversible opaque
    reference so a dataset item can be traced across builds for the *same*
    repository without ever storing its real identity.
    """
    digest = hashlib.sha256(repository_full_name.encode("utf-8")).hexdigest()[:16]
    return f"repo-{digest}"

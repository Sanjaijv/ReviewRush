import fnmatch


def matches_any(path: str, patterns: list[str]) -> str | None:
    """Return the first pattern in `patterns` that matches `path`, or None.

    Uses shell-glob semantics (`fnmatch`), not path-segment-aware globbing:
    `*` and `**` both match any sequence of characters including `/`, which
    is what `.reviewrush.yml`-style patterns like `src/auth/**` expect.
    """
    if not path:
        return None
    for pattern in patterns:
        if fnmatch.fnmatch(path, pattern):
            return pattern
    return None

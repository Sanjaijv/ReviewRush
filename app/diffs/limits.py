from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class DiffLimits:
    max_files: int
    max_file_patch_bytes: int
    max_total_changed_lines: int
    max_total_prompt_bytes: int

    @classmethod
    def from_settings(cls) -> "DiffLimits":
        settings = get_settings()
        return cls(
            max_files=settings.diff_max_files,
            max_file_patch_bytes=settings.diff_max_file_patch_bytes,
            max_total_changed_lines=settings.diff_max_total_changed_lines,
            max_total_prompt_bytes=settings.diff_max_total_prompt_bytes,
        )


@dataclass
class LimitEvaluation:
    oversized: bool
    reasons: list[str]


def evaluate_limits(
    limits: DiffLimits,
    *,
    file_count: int,
    total_changed_lines: int,
    total_patch_bytes: int,
) -> LimitEvaluation:
    """Decide whether a diff exceeds configured bounds.

    An oversized diff is flagged for human review rather than having its file
    list silently truncated - callers must never treat a partial file list as
    a complete review of the change.
    """
    reasons: list[str] = []

    if file_count > limits.max_files:
        reasons.append(f"file_count {file_count} exceeds max_files {limits.max_files}")
    if total_changed_lines > limits.max_total_changed_lines:
        reasons.append(
            f"total_changed_lines {total_changed_lines} exceeds "
            f"max_total_changed_lines {limits.max_total_changed_lines}"
        )
    if total_patch_bytes > limits.max_total_prompt_bytes:
        reasons.append(
            f"total_patch_bytes {total_patch_bytes} exceeds "
            f"max_total_prompt_bytes {limits.max_total_prompt_bytes}"
        )

    return LimitEvaluation(oversized=bool(reasons), reasons=reasons)

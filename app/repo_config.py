import logging
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class BranchesConfig(BaseModel):
    model_config = {"extra": "forbid"}

    source: str | None = None
    target: str | None = None


class ReviewConfig(BaseModel):
    model_config = {"extra": "forbid"}

    auto_open_pr: bool = True
    post_inline_comments: bool = True
    minimum_ai_confidence: float = Field(default=0.90, ge=0.0, le=1.0)


class CheckConfig(BaseModel):
    model_config = {"extra": "forbid"}

    command: str
    required: bool = True
    image: str | None = None
    timeout_seconds: int | None = Field(default=None, gt=0)


class MergeConfig(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = False
    method: str = "squash"
    maximum_risk: str = "low"
    require_human_for_protected_paths: bool = True


class AutoFixConfig(BaseModel):
    """Repository override for AI auto-fix behavior. The standalone schema
    default remains off; runtime parsing may inherit an enabled operator-level
    `settings.autofix_enabled` default when the repository did not explicitly
    opt out. The global switch must always be true or nothing takes effect.
    `maximum_severity` can only ever be raised as high as "medium": findings
    tagged "security" are never eligible regardless of this config, and
    "high"/"critical" is not an accepted value here - both are enforced in
    app/autofix/service.py, not just by this schema, so a config typo or a
    future looser default here can never on its own widen what auto-fix is
    allowed to touch.
    """

    model_config = {"extra": "forbid"}

    enabled: bool = False
    maximum_severity: Literal["low", "medium"] = "low"


class RepoConfig(BaseModel):
    """Schema for `.reviewrush.yml`.

    Unknown top-level keys are rejected (extra="forbid") so a typo in a
    security-critical field fails validation instead of being silently ignored.
    """

    model_config = {"extra": "forbid"}

    version: int = 1
    branches: BranchesConfig = Field(default_factory=BranchesConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    protected_paths: list[str] = Field(default_factory=list)
    checks: dict[str, CheckConfig] = Field(default_factory=dict)
    merge: MergeConfig = Field(default_factory=MergeConfig)
    auto_fix: AutoFixConfig = Field(default_factory=AutoFixConfig)


def parse_repo_config(
    raw_yaml: str | None, *, default_auto_fix_enabled: bool = False
) -> RepoConfig:
    """Parse `.reviewrush.yml` content, failing closed to safe defaults.

    A missing file, empty file, invalid YAML, or a document that fails schema
    validation never raises. Runtime callers may inherit auto-fix from the
    operator's global switch via `default_auto_fix_enabled`; an explicit
    repository value always wins. Invalid configuration still fails closed
    with auto-fix disabled rather than inheriting a write-capable default.
    """
    inherited_defaults = RepoConfig(
        auto_fix=AutoFixConfig(enabled=default_auto_fix_enabled)
    )
    if not raw_yaml or not raw_yaml.strip():
        return inherited_defaults

    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        logger.warning("failed to parse .reviewrush.yml: invalid YAML")
        return RepoConfig()

    if data is None:
        return inherited_defaults

    if not isinstance(data, dict):
        logger.warning("failed to parse .reviewrush.yml: document is not a mapping")
        return RepoConfig()

    try:
        effective_data = dict(data)
        if default_auto_fix_enabled:
            auto_fix = effective_data.get("auto_fix")
            if auto_fix is None:
                effective_data["auto_fix"] = {"enabled": True}
            elif isinstance(auto_fix, dict) and "enabled" not in auto_fix:
                effective_data["auto_fix"] = {**auto_fix, "enabled": True}
        return RepoConfig.model_validate(effective_data)
    except ValidationError as exc:
        logger.warning("invalid .reviewrush.yml, using defaults: %s", exc)
        return RepoConfig()

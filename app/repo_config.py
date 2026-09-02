import logging

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


class MergeConfig(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool = False
    method: str = "squash"
    maximum_risk: str = "low"
    require_human_for_protected_paths: bool = True


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


def parse_repo_config(raw_yaml: str | None) -> RepoConfig:
    """Parse `.reviewrush.yml` content, failing closed to safe defaults.

    A missing file, empty file, invalid YAML, or a document that fails schema
    validation all resolve to the default RepoConfig (no branch override,
    auto-merge disabled) rather than raising — callers fall back to
    repository-level settings for anything the config doesn't provide.
    """
    if not raw_yaml or not raw_yaml.strip():
        return RepoConfig()

    try:
        data = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        logger.warning("failed to parse .reviewrush.yml: invalid YAML")
        return RepoConfig()

    if data is None:
        return RepoConfig()

    if not isinstance(data, dict):
        logger.warning("failed to parse .reviewrush.yml: document is not a mapping")
        return RepoConfig()

    try:
        return RepoConfig.model_validate(data)
    except ValidationError as exc:
        logger.warning("invalid .reviewrush.yml, using defaults: %s", exc)
        return RepoConfig()

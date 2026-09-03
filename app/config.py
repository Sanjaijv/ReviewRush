from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, validated from environment variables on startup."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+psycopg://reviewrush:reviewrush@localhost:5432/reviewrush"
    )
    redis_url: str = Field(default="redis://localhost:6379/0")
    celery_broker_url: str | None = Field(default=None)
    celery_result_backend: str | None = Field(default=None)

    github_app_id: str = Field(default="")
    github_private_key: str = Field(default="")
    github_webhook_secret: str = Field(default="")
    github_api_base_url: str = Field(default="https://api.github.com")

    diff_max_files: int = Field(default=300)
    diff_max_file_patch_bytes: int = Field(default=200_000)
    diff_max_total_changed_lines: int = Field(default=6_000)
    diff_max_total_prompt_bytes: int = Field(default=400_000)

    # Deterministic analysis pipeline (Phase 5). Disabled by default: running it
    # requires the worker to have Docker access (e.g. a mounted docker.sock),
    # which is a real security tradeoff the operator must opt into explicitly.
    analysis_sandbox_enabled: bool = Field(default=False)
    analysis_docker_binary: str = Field(default="docker")
    analysis_default_image: str = Field(default="python:3.12-slim")
    analysis_workdir: str = Field(default="/var/lib/reviewrush/analysis")
    analysis_volume_name: str = Field(default="reviewrush_analysis_workspace")
    analysis_timeout_seconds: int = Field(default=600)
    analysis_memory_limit_mb: int = Field(default=512)
    analysis_cpu_limit: float = Field(default=1.0)
    analysis_pids_limit: int = Field(default=128)
    analysis_max_log_bytes: int = Field(default=64_000)
    analysis_max_repo_bytes: int = Field(default=200_000_000)

    analysis_semgrep_enabled: bool = Field(default=True)
    analysis_semgrep_required: bool = Field(default=True)
    analysis_semgrep_image: str = Field(default="semgrep/semgrep:latest")
    analysis_semgrep_network_enabled: bool = Field(default=False)

    analysis_gitleaks_enabled: bool = Field(default=True)
    analysis_gitleaks_required: bool = Field(default=True)
    analysis_gitleaks_image: str = Field(default="zricethezav/gitleaks:latest")

    analysis_dependency_scan_enabled: bool = Field(default=True)
    analysis_dependency_scan_required: bool = Field(default=False)
    analysis_dependency_scan_network_enabled: bool = Field(default=False)
    analysis_dependency_scan_python_image: str = Field(default="python:3.12-slim")
    analysis_dependency_scan_node_image: str = Field(default="node:20-slim")

    # AI reviewer MVP (Phase 6). Disabled by default: it needs a reachable
    # Ollama server with the configured model already pulled. The concrete
    # ReviewModel implementation is provider-neutral in interface, but this
    # release only wires up a free, locally-hosted open-weight model - no
    # paid API key, no training.
    ai_review_enabled: bool = Field(default=False)
    ai_provider: str = Field(default="ollama")
    ai_ollama_base_url: str = Field(default="http://localhost:11434")
    ai_model: str = Field(default="qwen2.5-coder:7b")
    ai_request_timeout_seconds: int = Field(default=120)
    ai_max_output_tokens: int = Field(default=4096)
    ai_max_prompt_bytes: int = Field(default=400_000)
    ai_max_issues: int = Field(default=50)

    # Specialized reviewers and consensus (Phase 14). Off by default: the
    # single general-purpose reviewer (Phase 6) remains the AIReview record
    # every downstream consumer (policy engine, checks/comments) reads.
    # Enabling this adds extra specialized passes whose findings/verdict are
    # folded into that *same* AIReview via deterministic aggregation - there
    # is no second review pipeline for the policy engine or comment renderer
    # to know about, and disagreement between reviewers can only push the
    # aggregate toward more caution, never less.
    ai_specialized_reviewers_enabled: bool = Field(default=False)
    # Deliberately smaller than ai_max_prompt_bytes: each specialist only
    # needs enough of the diff to judge its own narrow category, not the
    # full change.
    ai_specialized_reviewer_max_prompt_bytes: int = Field(default=200_000)
    ai_specialized_disagreement_confidence_penalty: float = Field(
        default=0.15, ge=0.0, le=1.0
    )

    # Policy and risk decision engine (Phase 7). These are the organization's
    # minimum policy floor: repository-level `.reviewrush.yml` settings are
    # merged with these and can only tighten them further, never weaken them
    # (protected paths are unioned, confidence/risk floors are clamped).
    policy_version: str = Field(default="1")
    policy_org_min_ai_confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    policy_org_max_auto_merge_risk: str = Field(default="low")
    policy_org_protected_paths: list[str] = Field(
        default_factory=lambda: [
            "**/auth/**",
            "**/authn/**",
            "**/authz/**",
            "**/payments/**",
            "**/billing/**",
            "migrations/**",
            "alembic/versions/**",
            "infra/**",
            "infrastructure/**",
            "terraform/**",
            ".github/workflows/**",
            "**/secrets/**",
            "**/*.secret.*",
            ".reviewrush.yml",
        ]
    )
    policy_dependency_manifest_patterns: list[str] = Field(
        default_factory=lambda: [
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "requirements*.txt",
            "pyproject.toml",
            "poetry.lock",
            "Pipfile",
            "Pipfile.lock",
            "go.mod",
            "go.sum",
            "Cargo.toml",
            "Cargo.lock",
            "**/Gemfile",
            "**/Gemfile.lock",
        ]
    )
    policy_max_auto_mergeable_changed_lines: int = Field(default=500)

    # Repository-aware context (Phase 10). Disabled by default: it downloads
    # a full repo tree checkout (same mechanism as the analysis sandbox) to
    # retrieve related code, so an operator must opt in explicitly.
    context_enabled: bool = Field(default=False)
    context_max_repo_bytes: int = Field(default=200_000_000)
    context_max_files_scanned: int = Field(default=5_000)
    context_max_file_bytes: int = Field(default=500_000)
    context_max_bytes: int = Field(default=150_000)
    context_max_items_per_symbol: int = Field(default=5)
    context_max_symbols_per_file: int = Field(default=50)
    context_guidance_filenames: list[str] = Field(
        default_factory=lambda: [
            "AGENTS.md",
            "CONTRIBUTING.md",
            "CODE_OF_CONDUCT.md",
            "docs/CODING_STANDARDS.md",
            "STYLE_GUIDE.md",
        ]
    )
    context_guidance_max_bytes_each: int = Field(default=20_000)

    # RAG / scalable indexing (Phase 11). Symbol chunks and lexical
    # relationships are always maintained once context_enabled is on;
    # semantic (embedding) retrieval is a further opt-in on top of that,
    # since it requires a reachable embeddings-capable Ollama model and a
    # pgvector-enabled Postgres. Off by default - retrieval degrades to
    # lexical/structural-only with no behavior change if left off.
    context_embeddings_enabled: bool = Field(default=False)
    context_embeddings_provider: str = Field(default="ollama")
    context_embeddings_model: str = Field(default="nomic-embed-text")
    context_embeddings_dimensions: int = Field(default=768)
    context_embeddings_timeout_seconds: int = Field(default=30)
    context_semantic_candidates: int = Field(default=8)

    # GitHub checks, summaries, and inline comments (Phase 8).
    checks_run_name: str = Field(default="ReviewRush")
    # Findings below this severity are still counted in the summary but not
    # posted as individual inline comments, to keep noise down on busy diffs.
    checks_min_inline_severity: str = Field(default="medium")
    checks_max_inline_comments: int = Field(default=25)

    # Safe auto-approval and auto-merge (Phase 9). Off by default at the
    # organization level, mirroring ai_review_enabled/analysis_sandbox_enabled:
    # even a repository with `merge.enabled: true` in .reviewrush.yml will
    # not auto-merge until an operator also opts in here. Flipping this back
    # to False immediately stops new automated merges (checked fresh on
    # every attempt, nothing is cached).
    merge_auto_merge_enabled: bool = Field(default=False)
    merge_allowed_methods: list[str] = Field(default_factory=lambda: ["squash", "merge", "rebase"])

    # Dashboard, configuration, and auditability (Phase 12). GitHub OAuth
    # credentials for the *user-to-server* login flow (distinct from the App
    # credentials above, which authenticate server-to-server). Dashboard
    # login is unusable until both are set - there is no insecure fallback.
    dashboard_enabled: bool = Field(default=False)
    github_oauth_client_id: str = Field(default="")
    github_oauth_client_secret: str = Field(default="")
    # Signs/verifies the dashboard session cookie. Must be a long random
    # value in production - anyone holding it can forge a session for any
    # GitHub user. Never reuse github_webhook_secret or any other secret.
    dashboard_session_secret: str = Field(default="")
    dashboard_session_ttl_seconds: int = Field(default=3600)
    # Origin the OAuth callback redirects back to, e.g. https://reviewrush.example.com.
    dashboard_base_url: str = Field(default="http://localhost:8000")
    dashboard_default_retention_days: int = Field(default=90)

    # Reliability, observability, and production hardening (Phase 13).
    # Retry policy applied to every Celery task's *infrastructure*-transient
    # failures (DB/Redis connection errors, GitHub network/5xx/429) -
    # business-logic exceptions are never included, so a bad state fails
    # once and surfaces immediately instead of retrying blindly.
    reliability_task_max_retries: int = Field(default=5)
    reliability_task_retry_backoff_max_seconds: int = Field(default=300)
    # Advisory concurrency locks (Redis SET NX PX), keyed per-repository and
    # per-PR, so two concurrent webhook deliveries for the same repository
    # can't race to open duplicate PRs or double-merge. Failing to acquire a
    # lock skips the critical section rather than blocking indefinitely.
    reliability_lock_enabled: bool = Field(default=True)
    reliability_lock_timeout_seconds: int = Field(default=60)
    reliability_lock_wait_seconds: float = Field(default=10.0)

    # Prometheus metrics at GET /metrics. No auth of its own - put it behind
    # network policy or a reverse-proxy allowlist in production, the same as
    # any other operator-only endpoint.
    metrics_enabled: bool = Field(default=True)

    # Distributed tracing (OpenTelemetry). Off by default: it requires a
    # reachable OTLP collector, an external dependency this release doesn't
    # assume every operator has. Turning it on instruments FastAPI, Celery,
    # and httpx so a trace follows one review from the webhook through every
    # worker stage and GitHub/model call.
    tracing_enabled: bool = Field(default=False)
    tracing_service_name: str = Field(default="reviewrush")
    tracing_otlp_endpoint: str = Field(default="http://localhost:4318")
    tracing_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0)

    # Cost and quota limits (Phase 13). Off by default - operators who need
    # to cap AI spend per installation/repository opt in explicitly. When a
    # quota is exceeded, the AI call is skipped and an AIReview row with
    # status="quota_exceeded" is persisted instead: the existing Phase 7
    # policy engine already treats any non-"completed" AIReview status as
    # HUMAN_REVIEW, so this degrades safely with no new code path that could
    # accidentally auto-approve.
    quota_enabled: bool = Field(default=False)
    quota_max_ai_reviews_per_repository_per_day: int = Field(default=200)
    quota_max_ai_reviews_per_installation_per_day: int = Field(default=1000)

    # Feedback collection and model evaluation (Phase 15). Off by default,
    # mirroring every other optional surface: the admin evaluation API
    # (dataset build, benchmark run, promotion) is a cross-tenant governance
    # surface with no per-organization RBAC yet (that's Phase 17), so it is
    # gated by this flag plus a static bearer token rather than the
    # dashboard's per-user OAuth model.
    eval_enabled: bool = Field(default=False)
    # Compared with hmac.compare_digest against the eval admin API's
    # Authorization header. Empty means the API always rejects - there is no
    # insecure fallback if an operator enables eval_enabled without setting
    # this.
    eval_admin_token: str = Field(default="")
    # Minimum benchmark/dataset metrics `app.evaluation.promotion` requires
    # before a provider/model/prompt/policy combination can be promoted -
    # the concrete enforcement behind "auto-merge thresholds are based on
    # measured performance, not anecdotes".
    eval_promotion_min_precision: float = Field(default=0.6, ge=0.0, le=1.0)
    eval_promotion_min_recall: float = Field(default=0.6, ge=0.0, le=1.0)
    # Default retention window recorded on new FindingFeedback rows. Purely
    # a recorded policy value - actual scheduled deletion is a separate,
    # not-yet-built process, the same as Repository.retention_days.
    feedback_default_retention_days: int = Field(default=365)

    # Custom-model fine-tuning (Phase 16). Off by default, mirroring every
    # other optional surface, and deliberately the last thing an operator
    # can turn on: the roadmap treats this as appropriate only after
    # prompting/retrieval alone have reached their practical limit and
    # thousands of consented, human-validated examples exist. Enabling it
    # only unlocks the admin API that exports/trains/evaluates candidate
    # models - it never lets a candidate model influence a live review or
    # merge decision on its own. That still requires going through the
    # unchanged Phase 15 `app.evaluation.promotion.promote_configuration`
    # gate, which fails closed the same way for a fine-tuned model as for
    # any other provider/model string.
    finetune_enabled: bool = Field(default=False)
    # Reuses the same static-bearer-token pattern as `eval_admin_token`
    # rather than a new auth mechanism - this is the same cross-tenant
    # governance surface Phase 15 already gates that way, with proper
    # per-organization RBAC deferred to Phase 17.
    finetune_admin_token: str = Field(default="")
    # Base open-weight coding model LoRA/QLoRA training starts from.
    finetune_base_model: str = Field(default="qwen2.5-coder:7b")
    finetune_method: str = Field(default="lora")
    # Absolute path to an operator-supplied external training command
    # (e.g. an axolotl/unsloth/peft training script). This repository does
    # not bundle a trainer or assume GPU hardware is available - the same
    # explicit-opt-in boundary `analysis_docker_binary` draws around the
    # deterministic-analysis sandbox. Empty means training cannot start;
    # there is no insecure default that silently no-ops as "success".
    finetune_trainer_command: str = Field(default="")
    finetune_trainer_timeout_seconds: int = Field(default=3600)
    finetune_output_dir: str = Field(default="/var/lib/reviewrush/finetune")
    # Minimum consented, human-validated training examples the roadmap's
    # prerequisites call for ("thousands of diverse ... examples") before a
    # job is even allowed to start - a hard floor, not a suggestion.
    finetune_min_training_examples: int = Field(default=1000)
    # Whether `app.finetune.training` also runs `ollama create` to register
    # the trained adapter as a reachable model tag. Separate flag from
    # finetune_enabled so an operator can export/train without immediately
    # registering a new locally-callable model.
    finetune_ollama_create_enabled: bool = Field(default=False)
    finetune_ollama_binary: str = Field(default="ollama")
    # Guardrails enforced by `app.finetune.comparison` on top of the
    # existing eval_promotion_min_precision/recall floor - the concrete
    # "does not materially worsen security recall or false-positive rate"
    # acceptance criterion. Expressed as the maximum allowed regression
    # versus the baseline run, not an absolute floor.
    finetune_max_recall_regression: float = Field(default=0.05, ge=0.0, le=1.0)
    finetune_max_false_positive_rate_increase: float = Field(default=0.5, ge=0.0)
    # Shadow/canary comparison (Phase 16). Off by default; even when on, it
    # only runs after a live review has already completed and never blocks
    # or feeds back into the policy engine.
    finetune_shadow_eval_enabled: bool = Field(default=False)
    finetune_shadow_candidate_provider: str = Field(default="ollama")
    finetune_shadow_candidate_model: str = Field(default="")

    # Multi-tenant SaaS readiness (Phase 17). Off by default, mirroring
    # every other optional surface. When enabled, a Redis-backed fixed
    # window (see app/tenancy/rate_limit.py) rejects with 429 once a caller
    # exceeds its per-minute budget - the webhook endpoint is keyed by
    # GitHub installation id, the dashboard API by authenticated GitHub
    # user id. Fails open (no limiting) if Redis itself is unreachable,
    # the same tradeoff app.locking already makes for the concurrency lock.
    tenancy_rate_limit_enabled: bool = Field(default=False)
    tenancy_webhook_rate_limit_per_minute: int = Field(default=120)
    tenancy_dashboard_rate_limit_per_minute: int = Field(default=120)

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()

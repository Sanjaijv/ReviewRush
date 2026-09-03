"""Prometheus metrics for the Phase 13 reliability/observability surface.

A single process-global registry: `prometheus_client`'s default registry,
scraped via GET /metrics (`app/api/v1/metrics.py`). Celery workers and the
API process each expose their own /metrics-equivalent in-process counters;
because this is a multi-process deployment (API + worker, each possibly with
multiple replicas), these are per-process metrics meant to be aggregated by
the scraper (e.g. Prometheus federation/remote-write across replicas), not a
single global count.
"""

from prometheus_client import Counter, Gauge, Histogram

webhook_request_latency_seconds = Histogram(
    "reviewrush_webhook_request_latency_seconds",
    "Time to accept (not process) one inbound GitHub webhook request.",
    ["event_type", "status"],
)

celery_queue_depth = Gauge(
    "reviewrush_celery_queue_depth",
    "Number of tasks currently waiting in a Celery queue.",
    ["queue"],
)

review_stage_duration_seconds = Histogram(
    "reviewrush_review_stage_duration_seconds",
    "Duration of one deterministic-analysis tool run or AI review call.",
    ["stage", "outcome"],
    buckets=(0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600, 1800),
)

tool_run_failures_total = Counter(
    "reviewrush_tool_run_failures_total",
    "Deterministic analysis tool runs that did not conclude successfully.",
    ["check_name", "conclusion"],
)

model_call_failures_total = Counter(
    "reviewrush_model_call_failures_total",
    "AI review model calls that errored or produced invalid output.",
    ["provider", "status"],
)

github_rate_limit_remaining = Gauge(
    "reviewrush_github_rate_limit_remaining",
    "Most recently observed X-RateLimit-Remaining value from the GitHub API.",
    ["resource"],
)

task_retries_total = Counter(
    "reviewrush_task_retries_total",
    "Celery task retries attempted for a transient failure.",
    ["task_name"],
)

task_dead_letters_total = Counter(
    "reviewrush_task_dead_letters_total",
    "Celery tasks that exhausted retries and were recorded as dead-lettered.",
    ["task_name"],
)

quota_rejections_total = Counter(
    "reviewrush_quota_rejections_total",
    "AI reviews skipped because a configured quota was exceeded.",
    ["scope"],
)

specialized_reviewer_findings_total = Counter(
    "reviewrush_specialized_reviewer_findings_total",
    "Findings produced by one specialized reviewer pass (Phase 14), before dedup.",
    ["reviewer", "category"],
)

specialized_reviewer_disagreement_total = Counter(
    "reviewrush_specialized_reviewer_disagreement_total",
    "Diff snapshots where specialized reviewers disagreed on decision, "
    "lowering aggregate confidence (Phase 14).",
)


def observe_github_rate_limit(headers: object) -> None:
    """Update the rate-limit gauge from a GitHub API response's headers.
    Best-effort: GitHub omits these on some endpoints, and a missing/
    unparsable header must never break the calling request.
    """
    try:
        remaining = headers.get("X-RateLimit-Remaining")  # type: ignore[attr-defined]
        resource = headers.get("X-RateLimit-Resource", "core")  # type: ignore[attr-defined]
        if remaining is not None:
            github_rate_limit_remaining.labels(resource=resource).set(float(remaining))
    except Exception:
        pass

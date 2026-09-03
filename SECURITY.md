# Security policy

## Supported versions

ReviewRush is pre-1.0 and deployed as a single rolling version. Security fixes are
applied to the `main` branch only; there is no separate maintenance branch to
backport to.

## Reporting a vulnerability

Please report suspected security vulnerabilities privately - do not open a public
GitHub issue or discuss the report in a public forum.

- Email the maintainers listed in `docs/multi-tenancy.md` ("Ownership") with a
  description of the issue, steps to reproduce, and its potential impact.
- Include enough detail to reproduce the issue (request/response samples, affected
  endpoint or component, a proof-of-concept if available). Do not include real
  customer/tenant data in the report - use synthetic data.
- We aim to acknowledge a report within **3 business days** and to provide an initial
  assessment (severity, expected timeline) within **10 business days**.

We ask that you:

- Give us a reasonable amount of time to investigate and fix an issue before public
  disclosure.
- Avoid accessing, modifying, or deleting data that isn't yours while investigating -
  use your own test organization/repository.
- Avoid actions that could degrade the service for other tenants (load testing,
  resource-exhaustion probing) without prior coordination.

Reports that follow this process, stay within a reasonable scope, and don't involve
data destruction or service disruption are handled under a safe-harbor policy: we will
not pursue legal action for good-faith security research conducted this way.

## Scope

In scope: this repository's API, webhook handler, dashboard, and worker code, and its
default Docker Compose deployment configuration. Out of scope: third-party services it
integrates with (GitHub, Ollama) and any vulnerability that requires physical or
already-privileged access to the host.

## Dependency maintenance

Python dependencies are pinned via `pyproject.toml`. Operators are expected to run
`pip list --outdated` (or an equivalent supply-chain scanner) on a regular cadence and
apply security releases promptly, particularly for `fastapi`, `sqlalchemy`, `pyjwt`,
`httpx`, and `redis`, which sit on the request/webhook trust boundary. The
deterministic-analysis pipeline's `gitleaks`/`semgrep`/dependency-scan container images
(`app/config.py`) should similarly be re-pulled periodically rather than pinned to
`:latest` indefinitely in a long-lived deployment.

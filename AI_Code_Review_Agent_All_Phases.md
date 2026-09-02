# AI Code Review Agent — Complete Development Roadmap

This document defines every development phase for building a production-style application that automatically detects code changes, reviews them, opens or updates a pull request, posts findings, and safely merges approved changes.

The application is an **AI-assisted GitHub code-review and merge system**. The AI recommends; deterministic checks and repository policies decide whether a merge is permitted.

---

# 1. Product goal

Build a GitHub App that can:

1. Detect pushes to a configured development branch such as `foundations`.
2. Open or update a pull request from `foundations` to `main`.
3. Retrieve and analyze only the changed code plus relevant repository context.
4. Run tests, linting, type checks, security analysis, and secret detection.
5. Use a coding LLM to find logic, security, performance, and maintainability problems.
6. Publish a structured review summary and inline PR comments.
7. Produce a required GitHub check that passes or fails independently of the LLM's prose.
8. Auto-merge only low-risk changes that satisfy every configured policy.
9. Route uncertain, sensitive, or high-risk changes to a human reviewer.
10. Learn repository conventions and improve from developer feedback over time.

The initial supported workflow is:

```text
Developer pushes to foundations
              ↓
GitHub sends a signed webhook
              ↓
Create or update foundations → main PR
              ↓
Run CI and deterministic analysis
              ↓
Run AI review on the diff
              ↓
Apply repository policies
              ↓
LOW risk       MEDIUM risk       HIGH risk
   ↓               ↓                 ↓
Auto-merge     Human review      Block merge
```

---

# 2. Scope and safety boundary

The system is a review assistant and merge gate. It must not treat an LLM response as proof that code is correct.

The final decision must combine:

- GitHub branch protection.
- Required CI checks.
- Tests and code-quality tools.
- Security and secret scanning.
- Repository-specific policies.
- AI findings and confidence.
- Human approval for protected changes.

The first release will support GitHub only. Do not add GitLab or Bitbucket until the GitHub workflow is stable.

Never auto-merge changes involving protected paths unless a repository administrator explicitly enables that behavior. Protected paths should initially include authentication, authorization, payments, database migrations, infrastructure, deployment workflows, secrets configuration, and the review agent's own policy files.

---

# 3. Recommended technology stack

| Layer | Recommended technology |
|---|---|
| Backend API | Python 3.12+ and FastAPI |
| Git provider integration | GitHub App and GitHub REST/GraphQL APIs |
| Background work | Celery with Redis |
| Database | PostgreSQL |
| ORM and migrations | SQLAlchemy and Alembic |
| Validation | Pydantic |
| AI provider abstraction | Provider-neutral service interface |
| Initial coding model | API model or self-hosted Qwen Coder-class model |
| Local inference option | Ollama for development; vLLM for production |
| Security scanning | Semgrep and dependency ecosystem scanners |
| Secret scanning | Gitleaks |
| Python quality | Ruff, mypy, pytest |
| JavaScript/TypeScript quality | ESLint, TypeScript, Vitest/Jest |
| Containers | Docker and Docker Compose |
| Observability | Structured logs, OpenTelemetry, and error tracking |
| Deployment | Render/Railway for an MVP or a managed cloud/VPS for production |

Keep GitHub credentials, webhook secrets, model keys, and database credentials on the server. Never expose them to a browser or commit them to the repository.

---

# 4. Core domain objects

Design the database around these entities:

- **Installation**: GitHub App installation, account, encrypted installation metadata, and status.
- **Repository**: owner, name, default branch, configured source/target branches, and settings.
- **PullRequest**: GitHub PR number, head/base SHA, state, and synchronization timestamps.
- **ReviewRun**: one review attempt for one immutable head SHA.
- **ChangedFile**: filename, status, additions, deletions, patch, language, and truncation state.
- **ToolRun**: test/lint/type/security/secret-scan result, logs reference, duration, and conclusion.
- **AIFinding**: category, severity, file, line range, evidence, message, recommendation, and confidence.
- **PolicyDecision**: risk score, final decision, reasons, required actions, and policy version.
- **ReviewComment**: GitHub comment ID, finding fingerprint, publication status, and resolution state.
- **RepositoryRule**: protected paths, merge restrictions, tool commands, thresholds, and overrides.
- **Feedback**: developer response, accepted/rejected finding, dismissal reason, and later outcome.
- **AuditEvent**: actor, action, target, timestamp, and redacted metadata.

Every review result must be tied to a specific commit SHA. A result generated for an older SHA must never authorize a newer commit.

---

# 5. Required repository configuration

Support a version-controlled configuration file such as `.reviewrush.yml`:

```yaml
version: 1

branches:
  source: foundations
  target: main

review:
  auto_open_pr: true
  post_inline_comments: true
  minimum_ai_confidence: 0.90

protected_paths:
  - "src/auth/**"
  - "src/payments/**"
  - "migrations/**"
  - ".github/workflows/**"
  - ".reviewrush.yml"

checks:
  tests:
    command: "pytest"
    required: true
  lint:
    command: "ruff check ."
    required: true
  secrets:
    command: "gitleaks detect --no-git"
    required: true

merge:
  enabled: true
  method: squash
  maximum_risk: low
  require_human_for_protected_paths: true
```

Validate this file against a strict schema. Invalid or unknown security-critical configuration must fail closed and require human review.

---

# Phase 1 — Project foundation

## Goal

Create the backend foundation and local development environment.

## Build

- FastAPI application with versioned API routes.
- PostgreSQL connection, initial models, and Alembic migrations.
- Redis and Celery worker setup.
- Environment validation on startup.
- Structured logging with request and correlation IDs.
- Docker Compose for API, worker, PostgreSQL, and Redis.
- Unit-test and lint configuration.
- `.env.example` containing variable names but no secrets.
- Health endpoints for API, database, Redis, and worker dependencies.

## Deliverables

- Reproducible local environment.
- Initial database migration.
- Worker can receive and complete a sample task.
- CI workflow for lint, type checks, and tests.

## Acceptance criteria

- A new developer can start the stack from documented commands.
- `/health/live` confirms the process is alive.
- `/health/ready` fails if required dependencies are unavailable.
- Tests, lint, and type checks pass in CI.

---

# Phase 2 — GitHub App and secure webhook ingestion

## Goal

Connect the service to GitHub without using a personal access token.

## Build

- Create a GitHub App with least-privilege permissions.
- Subscribe to `installation`, `installation_repositories`, `push`, `pull_request`, `pull_request_review`, `check_run`, and `check_suite` events as needed.
- Implement `POST /api/v1/github/webhook`.
- Verify `X-Hub-Signature-256` against the raw request body before parsing or processing it.
- Use GitHub delivery IDs as idempotency keys.
- Persist installation and repository metadata.
- Generate short-lived installation access tokens only when required.
- Queue webhook processing and return promptly.
- Redact credentials and sensitive payload fields from logs.

## Minimum GitHub permissions

| Permission | Access |
|---|---|
| Metadata | Read |
| Contents | Read |
| Pull requests | Read and write |
| Checks | Read and write |
| Commit statuses | Read and write, if used |
| Issues | Read and write only if PR conversation APIs require it |

Add more permissions only when a concrete feature requires them.

## Acceptance criteria

- Valid signed webhooks are accepted once.
- Invalid signatures receive `401` and create no job.
- Replayed delivery IDs do not create duplicate work.
- Installing and uninstalling the App updates repository access correctly.

---

# Phase 3 — Branch monitoring and PR automation

## Goal

Detect pushes to the configured development branch and maintain one active PR to the target branch.

## Build

- Read source and target branch names from repository settings or `.reviewrush.yml`.
- Ignore unrelated branches and bot-generated loops.
- On a qualifying push, find an existing open PR for the same head and base branches.
- Create the PR if none exists; otherwise update its automated section without overwriting human text.
- Generate a concise title and body from commit metadata.
- Record the current head and base SHA.
- Debounce rapid consecutive pushes so obsolete review jobs can be cancelled.
- Handle force pushes, deleted branches, closed PRs, and merge conflicts.

## Acceptance criteria

- A push to `foundations` creates exactly one `foundations → main` PR.
- Additional pushes update the same PR and schedule a fresh review.
- A push to another branch does nothing unless configured.
- A stale review cannot approve or merge the new head SHA.

---

# Phase 4 — Diff retrieval and normalization

## Goal

Build a reliable, bounded representation of the code change.

## Build

- Retrieve the merge-base comparison, changed files, patches, and commit metadata.
- Preserve old/new file paths for renames.
- Identify additions, modifications, deletions, binaries, generated files, lockfiles, and submodules.
- Parse hunks and map added lines to GitHub review positions.
- Detect truncated patches and fetch file content when policy permits.
- Enforce limits for file count, individual file size, total changed lines, and total prompt size.
- Exclude generated/vendor files from AI review while still applying appropriate deterministic checks.
- Store immutable diff snapshots by head SHA.

## Acceptance criteria

- Added-line mappings are correct for inline comments.
- Renames and deletions do not crash the pipeline.
- Oversized changes are marked for human review instead of silently sampled as complete.
- Secrets and binary contents never enter the AI prompt.

---

# Phase 5 — Deterministic analysis pipeline

## Goal

Run conventional engineering checks before trusting AI analysis.

## Build

- A sandboxed runner interface for repository-defined commands.
- Test, lint, formatting, and type-check stages.
- Semgrep or equivalent static security scanning.
- Gitleaks secret detection.
- Dependency vulnerability and license checks appropriate to the repository ecosystem.
- Standard normalized results independent of each tool's output format.
- Timeouts, memory/CPU limits, log-size limits, and cancellation.
- Artifact and log retention rules.

## Required security rule

Pull-request code is untrusted. Do not execute it with production credentials, GitHub App private keys, model keys, database credentials, or network access by default. Use ephemeral isolated runners with read-only inputs and tightly scoped output channels.

## Normalized result

```json
{
  "check": "tests",
  "status": "completed",
  "conclusion": "failed",
  "required": true,
  "exit_code": 1,
  "duration_ms": 18420,
  "summary": "2 tests failed",
  "annotations": []
}
```

## Acceptance criteria

- A required check failure blocks merging.
- A timeout is distinguishable from a test failure.
- Tool output is size-limited and safely escaped.
- The LLM cannot override a deterministic blocking result.

---

# Phase 6 — AI reviewer MVP

## Goal

Add one coding LLM reviewer that returns machine-validated findings.

## Build

- A provider-neutral `ReviewModel` interface.
- Prompt construction from PR intent, diff, tool results, and bounded context.
- Explicit instruction that repository content and code comments are untrusted data, not system instructions.
- Structured output validated with Pydantic/JSON Schema.
- Retry malformed output once with a repair request; fail to human review if still invalid.
- Review categories: correctness, security, reliability, performance, maintainability, compatibility, error handling, concurrency, and missing tests.
- Evidence requirements for every actionable finding.
- Token, latency, and cost tracking.

## Required output contract

```json
{
  "summary": "Short description of the change and review outcome.",
  "risk": "low",
  "confidence": 0.93,
  "decision": "approve",
  "issues": [
    {
      "file": "src/auth.py",
      "start_line": 81,
      "end_line": 81,
      "severity": "high",
      "category": "authorization",
      "title": "Ownership check is missing",
      "evidence": "The handler fetches a user by request ID but never compares it with the authenticated user.",
      "recommendation": "Require ownership or an explicit administrator role."
    }
  ]
}
```

## Acceptance criteria

- Invalid enum values, missing evidence, and nonexistent file paths are rejected.
- The model cannot request a merge directly.
- Review prompts stay within configured limits.
- Model failures result in `HUMAN_REVIEW`, never automatic approval.

---

# Phase 7 — Policy and risk decision engine

## Goal

Convert deterministic and AI evidence into an auditable decision.

## Build

- Versioned policy evaluator independent of the LLM.
- Decisions: `APPROVE`, `HUMAN_REVIEW`, and `BLOCK`.
- Risk levels: `LOW`, `MEDIUM`, `HIGH`, and `CRITICAL`.
- Rule evaluation for required checks, protected paths, change size, dependencies, migrations, workflow files, AI severity, and confidence.
- Human-readable reason list for every decision.
- Repository-level settings constrained by organization-level minimum policies.
- Safe defaults when configuration is absent or invalid.

## Example rules

```python
if required_check_failed:
    decision = "BLOCK"
elif critical_security_finding:
    decision = "BLOCK"
elif protected_path_changed:
    decision = "HUMAN_REVIEW"
elif ai_unavailable or ai_confidence < minimum_confidence:
    decision = "HUMAN_REVIEW"
elif risk != "LOW":
    decision = "HUMAN_REVIEW"
else:
    decision = "APPROVE"
```

## Acceptance criteria

- The same inputs and policy version always produce the same decision.
- Every decision records its evidence and policy version.
- Missing results fail closed.
- Repository configuration cannot weaken mandatory organization protections.

---

# Phase 8 — GitHub checks, summaries, and inline comments

## Goal

Make review results clear and actionable inside the PR.

## Build

- Create an in-progress GitHub Check Run at review start.
- Complete it with success, neutral/action-required, or failure based on the policy decision.
- Post one concise PR summary containing check results, risk, important findings, and next action.
- Publish inline comments only on valid changed lines.
- Fall back to a summary comment when GitHub cannot attach to the requested line.
- Fingerprint findings to avoid duplicate comments after reruns.
- Minimize noise by applying severity and confidence thresholds.
- Mark outdated findings when the relevant code changes.

## Acceptance criteria

- The PR shows one current review summary per head SHA.
- Inline comments point to the intended changed lines.
- Rerunning a review does not create duplicate spam.
- The required status check accurately reflects the policy decision.

---

# Phase 9 — Safe auto-approval and auto-merge

## Goal

Merge only eligible, low-risk changes after GitHub and application policies agree.

## Build

- Enable GitHub auto-merge or invoke merge only after all required checks complete.
- Re-fetch PR state immediately before merging.
- Verify the head SHA, base branch, mergeability, required checks, approvals, and policy decision.
- Prefer squash merging for the first release.
- Prevent the App from bypassing branch protection.
- Cancel merge eligibility when a new commit arrives.
- Record the final merge attempt and GitHub response in the audit log.

## Auto-merge eligibility

```text
Current reviewed SHA matches PR head
+ all required GitHub checks pass
+ deterministic scans pass
+ AI review completed successfully
+ policy decision is APPROVE
+ total risk is LOW
+ no protected path requires a human
+ repository auto-merge setting is enabled
= eligible for auto-merge
```

## Acceptance criteria

- A stale review can never merge a newer commit.
- Medium/high-risk and protected changes wait for a human.
- Merge conflicts and branch-protection failures are reported without retry loops.
- Disabling auto-merge immediately prevents new automated merges.

---

# Phase 10 — Repository-aware context

## Goal

Improve review quality by understanding code surrounding the diff.

## Build

- Detect repository languages, frameworks, manifests, test layout, and ownership files.
- Parse changed symbols using language-aware parsers such as Tree-sitter.
- Retrieve directly referenced functions, callers/callees, interfaces, schemas, tests, and configuration.
- Read repository guidance such as `AGENTS.md`, `CONTRIBUTING.md`, and coding standards.
- Maintain strict context budgets and attach provenance to every retrieved item.
- Re-index only changed files after the initial index.

Start with lexical and structural retrieval. Add embeddings only when simpler retrieval is insufficient.

## Acceptance criteria

- The reviewer can inspect the implementation and tests related to a changed symbol.
- Context from an old commit is never mixed with the current review.
- Retrieved code is treated as untrusted content.
- Review output identifies which context supported a finding.

---

# Phase 11 — RAG and scalable code indexing

## Goal

Support larger repositories without sending the entire codebase to the model.

## Build

- Chunk source code by symbols rather than arbitrary character counts.
- Store path, language, symbol, commit SHA, and relationship metadata.
- Add PostgreSQL `pgvector` if semantic retrieval materially improves results.
- Combine lexical, symbol-graph, and semantic candidates.
- Re-rank by path relevance, symbol relationship, recency, and query specificity.
- Apply tenant/repository filters to every retrieval query.
- Delete or invalidate index entries when installations are removed.

## Acceptance criteria

- Retrieval never crosses repository or customer boundaries.
- Deleted files disappear from the active index.
- Evaluation demonstrates that retrieved context improves finding precision or recall.
- Indexing failure sends the review to a documented degraded mode or human review.

---

# Phase 12 — Dashboard, configuration, and auditability

## Goal

Give repository administrators visibility and control.

## Build

- GitHub-authenticated dashboard.
- Installation and repository selector with authorization checks.
- Review-run history and drill-down view.
- Configuration editor with schema validation and protected minimum policies.
- Metrics for review time, findings, false positives, blocked merges, and model usage.
- Audit log for configuration, review, approval, and merge events.
- Manual rerun and cancel controls.
- Data-retention and repository-disconnect controls.

## Acceptance criteria

- Users see only installations and repositories they are authorized to access.
- Every merge decision can be reconstructed from stored evidence.
- Settings changes are versioned and identify the actor.
- Uninstalling the App revokes access and starts the configured cleanup process.

---

# Phase 13 — Reliability, observability, and production hardening

## Goal

Make the service safe to operate under failures, retries, and concurrent pushes.

## Build

- Metrics for webhook latency, queue depth, review duration, tool failures, model failures, and GitHub rate limits.
- Distributed tracing across webhook, worker, GitHub, runner, and model calls.
- Retry policies with exponential backoff and jitter for transient failures only.
- Dead-letter handling and operator-visible failure states.
- Concurrency locks by repository and PR where required.
- Graceful cancellation of superseded reviews.
- Database backups, migration rollback planning, and disaster-recovery documentation.
- Load, security, and fault-injection testing.
- Cost and quota limits per installation/repository.

## Acceptance criteria

- Duplicate webhooks and worker retries do not duplicate PRs, comments, or merges.
- A GitHub or model outage cannot accidentally approve code.
- Operators can identify where a review failed from logs and traces.
- Rate limits and budget limits degrade to human review instead of unsafe success.

---

# Phase 14 — Specialized reviewers and consensus

## Goal

Add specialized review passes only after the single-reviewer system has proven reliable.

## Build

- Security reviewer.
- Logic and correctness reviewer.
- Performance and concurrency reviewer.
- Architecture and maintainability reviewer.
- Test-quality reviewer.
- Finding deduplication and contradiction handling.
- A deterministic aggregation layer; do not let a judge model bypass mandatory policy.

Run reviewers selectively based on file types, paths, and detected risk instead of calling every reviewer on every change.

## Acceptance criteria

- Specialized reviewers improve measured quality enough to justify added latency and cost.
- Duplicate findings collapse into one actionable comment.
- Disagreement raises uncertainty and cannot create automatic approval.
- The policy engine remains the final decision authority.

---

# Phase 15 — Feedback collection and model evaluation

## Goal

Measure whether the system is helpful before training a custom model.

## Build

- Let developers mark findings as useful, incorrect, already known, or not actionable.
- Record whether suggested changes were implemented.
- Track escaped defects linked to reviewed PRs when evidence is available.
- Build a versioned, de-identified evaluation dataset.
- Create a fixed benchmark containing clean diffs, known bugs, security issues, and adversarial prompt-injection cases.
- Measure precision, recall, false-positive rate, severity accuracy, line-location accuracy, latency, and cost.
- Compare prompt/model/policy versions through controlled offline evaluation.

## Acceptance criteria

- Model or prompt changes cannot be promoted without benchmark results.
- Feedback data records consent, provenance, and retention rules.
- Repository secrets and unnecessary personal data are excluded from training datasets.
- Auto-merge thresholds are based on measured performance, not anecdotes.

---

# Phase 16 — Fine-tune a custom code-review model

## Goal

Create a specialized reviewer only after enough high-quality review data exists.

## Prerequisites

- Thousands of diverse, human-validated examples.
- Clear dataset licenses and customer consent.
- Low-noise labels for accepted/rejected findings and severity.
- A frozen holdout benchmark that is never included in training.
- Evidence that prompting and retrieval alone have reached their practical limit.

## Build

- Select an open-weight coding base model appropriate to available hardware.
- Convert examples into structured instruction/response records.
- Remove secrets, credentials, personal data, and repository identifiers where required.
- Train using LoRA or QLoRA before considering full fine-tuning.
- Evaluate against the generic model on the frozen benchmark.
- Red-team for prompt injection, fabricated findings, insecure recommendations, and overconfidence.
- Deploy behind the existing provider-neutral model interface.
- Use canary/shadow traffic before allowing the model to influence merge decisions.

## Acceptance criteria

- The custom model meets or exceeds the existing reviewer on agreed quality metrics.
- It does not materially worsen security recall or false-positive rate.
- Rollback to the previous model is immediate.
- Fine-tuning does not change the rule that the policy engine controls merging.

---

# Phase 17 — Multi-tenant SaaS readiness

## Goal

Prepare the application for external organizations and paid production usage.

## Build

- Tenant isolation at application, database, cache, queue, runner, and retrieval layers.
- Organization roles and repository-level access control.
- Usage metering, plan limits, and billing integration if required.
- Regional retention and deletion policies.
- Customer-managed model/provider settings where appropriate.
- Security documentation, incident response, vulnerability disclosure, and dependency maintenance.
- Terms, privacy disclosures, and data-processing controls.
- Abuse prevention and rate limiting.

## Acceptance criteria

- Cross-tenant isolation is tested automatically.
- An organization can export or delete its retained data.
- Billing limits cannot disable mandatory safety checks while allowing an auto-merge.
- Security and operational ownership are documented.

---

# 6. Implementation order and milestones

| Milestone | Phases | Result |
|---|---|---|
| Foundation | 1–2 | Running service securely connected to GitHub |
| Useful MVP | 3–8 | Automatic PR creation, checks, AI review, and comments |
| Safe merge beta | 9 | Low-risk auto-merge under branch protection |
| Repository intelligence | 10–11 | Context-aware reviews for larger codebases |
| Production control | 12–13 | Dashboard, audit trail, observability, and reliability |
| Advanced intelligence | 14–16 | Specialized reviewers, evaluation, and optional custom model |
| SaaS expansion | 17 | Multi-organization product readiness |

The first genuinely useful release is complete after **Phase 8**. Auto-merge should remain disabled until Phase 9 has been tested on noncritical repositories and false-positive/false-negative behavior is understood.

---

# 7. Global security requirements

Apply these requirements in every phase:

- Verify every webhook signature using the raw body.
- Use GitHub App installation tokens rather than personal tokens.
- Store secrets in a secret manager or protected environment variables.
- Encrypt sensitive persisted data and use TLS in transit.
- Treat repository content, PR text, commit messages, issue text, and tool output as untrusted input.
- Isolate the execution of pull-request code from service credentials and internal networks.
- Never place raw secrets, full credentials, or unnecessary private code in logs or model prompts.
- Protect against SSRF when processing repository URLs or external references.
- Enforce tenant and repository filters in every database and retrieval operation.
- Use idempotency for webhooks, comments, checks, reviews, and merge attempts.
- Fail closed when required evidence is missing.
- Require human approval for policy changes that weaken protections.
- Preserve an immutable audit record of automated merge decisions.

---

# 8. Global testing strategy

Every phase must include unit and integration tests. The complete system should additionally include:

- Contract tests for GitHub webhook payloads and API responses.
- Recorded-fixture tests for pushes, PR updates, force pushes, and check events.
- Policy-engine table tests covering every allow/block boundary.
- Diff and line-mapping tests for additions, deletions, renames, and multiline hunks.
- Prompt-injection tests embedded in code, filenames, comments, and PR descriptions.
- Runner escape, network isolation, timeout, and resource-limit tests.
- End-to-end tests against a dedicated GitHub test organization/repository.
- Chaos tests for GitHub, Redis, database, runner, and model failures.
- Load tests for bursty webhook delivery.
- Regression evaluation for AI findings before model or prompt upgrades.

Never claim a check passed without recording its actual result.

---

# 9. Definition of done for the complete application

The application is complete when:

1. A GitHub organization can install the App and select repositories.
2. A configured branch push creates or updates the correct PR exactly once.
3. Each review is bound to an immutable commit SHA.
4. Deterministic checks run safely in isolated infrastructure.
5. AI findings are structured, validated, evidence-based, and posted without duplication.
6. The policy engine generates an explainable `APPROVE`, `HUMAN_REVIEW`, or `BLOCK` decision.
7. GitHub branch protection treats the application's check as required.
8. Auto-merge is limited to current, low-risk, policy-compliant changes.
9. Protected, uncertain, failed, and oversized changes require a human.
10. Administrators can inspect configuration, review history, decisions, and audit events.
11. Failures, retries, rate limits, and duplicate events cannot create duplicate or unsafe actions.
12. Security, privacy, retention, backup, monitoring, and incident procedures are documented and tested.

---

# 10. Instructions for implementation agents

For each phase:

1. Read this roadmap and inspect the existing repository before making assumptions.
2. Implement only the selected phase and the smallest prerequisites it genuinely needs.
3. Preserve existing user changes and follow repository-level instructions.
4. Do not weaken branch protection, permissions, isolation, or fail-closed behavior to make a test pass.
5. Add or update migrations, configuration examples, tests, and documentation with the feature.
6. Run the relevant lint, type, unit, integration, build, and security checks.
7. Report the real results, remaining risks, manual setup, and exact validation steps.
8. Stop and ask for a decision if a missing choice changes security, cost, data retention, or deployment architecture.

Keep the implementation incremental. Do not begin multi-agent reviewing or model fine-tuning before the single-reviewer MVP, policy engine, measurement, and audit trail are working reliably.

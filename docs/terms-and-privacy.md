# Terms of service and privacy notice (template)

> **This is a drafting template, not legal advice, and is not a binding legal
> document as written.** It must be reviewed and adapted by qualified legal counsel
> before being presented to any customer or used to govern a production deployment.
> It exists so operators have a concrete starting point that reflects what the
> software actually does, rather than starting from a generic boilerplate that
> doesn't match this codebase's behavior.

## Scope

This document would govern use of a ReviewRush deployment ("the Service") by an
organization ("Customer") that installs the GitHub App and connects repositories.

## Data processed

The Service processes, on Customer's behalf: pull request diffs, commit metadata,
repository configuration (`.reviewrush.yml`), and (if the deterministic-analysis
pipeline is enabled) repository source code fetched into an isolated, ephemeral
analysis workspace. AI review calls send diff content and limited repository context
to the configured model provider (self-hosted Ollama by default in this release - no
third-party model API is called unless an operator explicitly reconfigures
`AI_PROVIDER`). See `docs/data-retention-and-deletion.md` for what is retained and for
how long.

## Customer controls (as implemented)

- **Access control**: Customer's GitHub organization membership/installation access is
  the source of truth for who can reach the dashboard for Customer's data
  (`app/dashboard/oauth.py`) - the Service never grants access independent of GitHub's
  own authorization.
- **Export**: Customer can export its retained data at any time
  (`POST /api/v1/dashboard/organizations/{id}/export`).
- **Deletion**: Customer's organization admin/owner can permanently delete retained
  review evidence at any time (`POST /api/v1/dashboard/organizations/{id}/delete-data`).
- **Provider choice**: Customer can pin its own AI provider/model
  (`Organization.ai_provider_override`/`ai_model_override`) rather than the operator's
  global default.

## What this template does not cover

Real terms would need, at minimum: liability limitation, service-level commitments,
payment terms (this release has no payment processor integrated - see
`docs/multi-tenancy.md` "Usage limits and billing-vs-safety"), sub-processor
disclosure (GitHub, and the configured AI model provider), applicable law/jurisdiction,
and a data processing addendum (DPA) if Customer is subject to GDPR/CCPA or similar.
None of that is decided by this codebase and must come from the operator and counsel.

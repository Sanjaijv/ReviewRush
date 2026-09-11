# ReviewRush Dashboard — Design Spec

Information architecture, screen-by-screen wireframes, component states, and a
design-token starter kit for building the ReviewRush web dashboard in Figma.

ReviewRush is an AI-assisted GitHub code-review bot. This dashboard is the
operator-facing surface for the organization that installed it — not the pull
request itself, which stays on GitHub.

**Scope:** 10 screens · Auth: GitHub OAuth (session cookie) · Data model: 1
organization ↔ 1 GitHub App installation · Source: FastAPI dashboard API
(`/api/v1/dashboard`, `/api/v1/finetune`, `/api/v1/evaluation`)

---

## 1. Information architecture

Everything hangs off the installation the signed-in user picks. A repository
is where the daily work happens; organization, evaluation, and fine-tuning
are admin-only side rooms.

```
/                                    Sign in                         (logged out)
/                                    Repositories                    (installation switcher · repo grid)
/repos/:id                           Overview                        (metrics · recent runs · alerts)
/repos/:id/runs                      Runs                            (history table)
/repos/:id/runs/:sha                 Run detail                      (findings · policy · checks)
/repos/:id/config                    Config                          (.reviewrush.yml editor + versions)
/repos/:id/ops                       Task failures & Audit log       (two-pane)
/org                                 Organization settings           (org admin only)
/admin/evaluation                    Evaluation admin                (token-gated)
/admin/finetune                      Fine-tune admin                 (token-gated)
```

- **One org per installation.** There's no cross-org switcher inside a
  workspace — switching installations in the header is the only way to move
  between orgs.
- **Evaluation and fine-tune admin are exceptional surfaces**, gated by a
  separate admin token on top of login — most orgs never see them turned on.
  Nest them under a low-emphasis "Admin" entry, not the primary nav.

---

## 2. Global app shell

Present on every screen except Sign in. A single-row header — no left
sidebar; the repo workspace itself uses in-page tabs, so the shell stays
thin.

| Region | Content |
|---|---|
| Wordmark | Left-aligned, links home |
| Installation switcher | "acme-corp ▾" — dropdown of every installation the user belongs to |
| *(spacer)* | — |
| Admin | Only shown if eval/finetune is enabled for this org |
| Avatar menu | Org settings · Sign out |

- Installation switcher is the top-level branch point in the IA — changing it
  re-scopes the whole app to a different repo list, and silently drops any
  open repo workspace.
- No global search in v1 — findings and runs are only ever browsed inside one
  repository's workspace.

---

## 3. Screen: Sign in

**Route:** `GET /api/v1/dashboard/auth/login`

One decision, one button. The whole session is GitHub's own OAuth — there is
no password, no separate signup.

**Layout:** centered column, max 360px —
1. Wordmark + one-line pitch
2. "Continue with GitHub" button

**States**
- *Loading:* a redirect round-trip through GitHub — show a brief full-page
  spinner on return, not a skeleton (nothing to skeleton yet).
- *Error:* OAuth exchange can fail (revoked app, expired code) — land back
  here with an inline banner, plain language: "Something went wrong signing
  you in. Try again."

---

## 4. Screen: Repositories

**Route:** `GET /installations/:id/repositories`

Landing screen after login. A grid of every repo the current installation
covers, each carrying its most recent run status so the page doubles as a
fleet-health view.

**Card contents:** repo `full_name`, default branch, most recent run's
policy pill (`approve` / `human_review` / `block`), relative timestamp.

Example cards:
- `reviewrush-test` — main · last run 4m ago — **approved**
- `payments-api` — main · last run 1h ago — **blocked**
- `infra-terraform` — disconnected 3d ago — **inactive**

**States**
- *Disconnected* repos (installation revoked or manually disconnected)
  render dimmed, grouped at the end of the grid, with a neutral "inactive"
  pill instead of a policy pill.
- *Empty:* installation has zero repos granted — one line, no illustration:
  "No repositories yet. Grant this app access from GitHub." + a link out to
  the GitHub installation settings.

---

## 5. Screen: Repository → Overview

**Route:** `GET /repositories/:id/metrics`

First tab on entering a repo. Answers "is this repo healthy" before the
operator drills into any one run.

**Layout, top to bottom:**
1. Alert banner — "⚠ 2 unresolved task failures" (only rendered when count
   > 0, links to the Task failures pane)
2. Four metric tiles: **Runs (30d)** · **Approve rate** · **Auto-fixes
   shipped** · **Median review time**
3. Recent runs — last 5 rows of the Runs table, "View all →" to the Runs tab

**Notes**
- Metric tiles come back as one untyped JSON blob from the backend today —
  treat the four above as the ones worth surfacing as tiles; render anything
  else the payload adds as a low-emphasis "more metrics" expandable, not a
  fifth tile, so the layout doesn't reflow every time a metric is added
  server-side.
- *Loading:* tiles skeleton independently of the recent-runs list — same
  request, but shouldn't block each other visually.

---

## 6. Screen: Repository → Runs

**Route:** `GET /repositories/:id/runs`

Every reviewed push, newest first. One run = one `DiffSnapshot`, i.e. one
head commit that went through the pipeline.

| Commit | Files | Lines | Status | When | Actions |
|---|---|---|---|---|---|
| `a1c4f2e` | 6 | +142 −38 | **complete** | 4 minutes ago | View · Rerun |
| `9de001b` | 21 | +880 −12 | **oversized** | 1 hour ago | View |
| `55f3aa9` | 3 | +9 −4 | **cancelled** | yesterday | View |

**Status values:** `complete` (good) · `oversized` (warn) · `cancelled`
(neutral) · `queued` (accent, in progress)

**Notes**
- Row actions are conditional: `Rerun` only on a completed run; `Cancel`
  only while queued/running (a live row — poll or socket-update its status
  pill rather than requiring a manual refresh).
- `oversized` means the diff exceeded configured size limits and skipped AI
  review — style as warning, not failure; its "View" still opens (to show
  the deterministic-checks-only result).
- Filter bar above the table: status (multi-select of the four values) + a
  date range. No free-text search in v1 — commit SHAs are the only
  identifier and people paste them directly into the URL.

---

## 7. Screen: Run detail

**Route:** `GET /repositories/:id/runs/:sha`

The densest screen in the product. One head commit's full trail: what the
deterministic scanners found, what the AI found, and what the policy engine
decided to do about it.

**Layout, top to bottom:**
1. Header — `a1c4f2e ← 7b90ee1` (head ← base), branch name, PR link out to
   GitHub
2. Deterministic checks row — one card per tool, e.g. `semgrep: pass` ·
   `gitleaks: pass` · `dependency scan: fail`
3. Findings (AI review) — a list of finding cards (see anatomy below)
4. Policy decision panel

### Finding card anatomy

- **Severity pill** — `critical` / `high` / `medium` / `low`, color-coded.
  `critical` should read as more urgent than plain `high` (darkest, most
  saturated red), not the same red as `high`.
- **Category tag** — one of `security`, `correctness`, `reliability`,
  `performance`, `maintainability`, `compatibility`, `error_handling`,
  `concurrency`, `missing_tests`. Render as a plain mono label, not a
  colored pill — color is reserved for severity so the two scales don't
  compete.
- **file:line**, title, and an expandable body for evidence/recommendation.
- **Autofix status**, only if an attempt exists:
  - `fix opened` (good) — automatic, opened a separate fix-PR
  - `fix committed` (accent) — manual, committed directly to the branch
  - `not applicable` (neutral)
  - `verification failed` (bad)
  - Security findings never get an *automatic* attempt — instead show a
    "Fix available — apply from the PR checkbox" hint, since that action
    lives on GitHub's own comment thread, not here.
- **Feedback** — thumbs up/down, posts to the per-finding feedback endpoint;
  once voted, replace the two buttons with a small "Marked helpful" /
  "Marked incorrect" line rather than leaving both buttons visibly
  clickable.

Example finding:
> **critical** · security · `app/auth/session.py:42` — Session token
> compared with `==`, not constant-time · **fix committed**

> **medium** · missing_tests · `app/billing/invoice.py:118` — New branch
> has no covering test · 👍 👎

### Policy decision panel

Decision is one of three values — copy should say what happens next, not
just the enum:

| Decision | Meaning |
|---|---|
| `APPROVE` (good) | "Nothing blocking — safe to merge." |
| `HUMAN_REVIEW` (accent) | "Needs a person to look before merging." |
| `BLOCK` (bad) | "Merge is blocked until this is resolved." |

- Risk (`low` / `medium` / `high` / `critical`) is a separate line from the
  decision itself — a `HUMAN_REVIEW` at critical risk should look distinctly
  more urgent than one at low risk, even though the decision pill is
  identical.
- Reasons render as a short bullet list underneath, taken verbatim from the
  backend's `reasons[]` — these are the actual sentence fragments a
  reviewer will read; don't summarize them further.
- A collapsed "Merge attempts" log sits at the bottom for repos with
  auto-merge on — mostly empty in practice, so keep it collapsed by
  default.

---

## 8. Screen: Repository → Config

**Route:** `GET`/`PUT /repositories/:id/config`

The repo's `.reviewrush.yml`, editable from the dashboard as a versioned
override layered on top of the file actually committed to the repo.

**Layout:** two columns —
- Left (wide): YAML editor, monospace, line numbers, syntax highlighting
- Right (narrow): version history — `v4 · sanjaijv · today`, `v3 · sanjaijv
  · 2 weeks ago`, `v2 · bot-migration · 3 weeks ago`

**Notes**
- **Source badge** at the top of the editor: `dashboard override` (accent)
  vs `repository file` (neutral) — makes it obvious whether edits here
  actually take effect (a repo committing its own `.reviewrush.yml` can
  take precedence; say so plainly if it does).
- Save creates a new version rather than editing in place — the version
  list is append-only, each entry expandable to a read-only diff against
  the previous version. No delete/rollback action for a version — only
  "restore" (copies an old version's content into the editor as a new
  draft, doesn't rewrite history).
- **Save button** disabled until the YAML parses; show inline parse errors
  at the offending line rather than a generic toast.

---

## 9. Screen: Repository → Task failures & Audit log

**Route:** `GET /repositories/:id/task-failures` · `GET
/repositories/:id/audit-log`

Two operational panes, tabbed together since both are "what happened, and
did a human deal with it" logs — task failures need action, the audit log
is read-only history.

**Task failures** (badge: "2 unresolved")
> `run_analysis_pipeline_task` · ConnectionError · retried 3× · 12m ago —
> **Resolve**

**Audit log**
```
policy.decided             diff_snapshot #881   system      4m ago
repository.config_updated  v4                    sanjaijv    1h ago
task_failure.resolved      #12                   sanjaijv    2h ago
```

**Notes**
- Task failures list only unresolved ones by default, with a toggle to
  "show resolved" — each row's Resolve action asks for no confirmation
  (it's marking-as-seen, not undoing anything), just moves the row out of
  the unresolved count immediately.
- Audit log is append-only and dense — every row is `actor · action ·
  target · time`, monospace, with a chevron to expand the raw metadata
  JSON. This is the one place in the product where raw JSON is an
  acceptable end state, not a placeholder for missing design.

---

## 10. Screen: Organization settings

**Route:** `GET`/`PUT /organizations/:id`

One page per installation's org record: identity, org-wide settings, and
the two irreversible actions (export, delete) kept visually separate from
everything else.

**Layout:**
1. Identity — `acme-corp` · GitHub org · installation #4821 · plan/tier if
   applicable
2. Settings form — org-wide defaults layered under each repo's own
   `.reviewrush.yml`
3. Danger zone (bad/red styling) — "Export all data" (async, emails a
   download link) · "Delete all data" (typed-confirmation required)

**Notes**
- This screen is admin-only — hide its nav entry entirely for non-admin
  members rather than showing it disabled (nothing here is useful to see
  and not use).
- Delete-data requires typing the org's name to confirm, same pattern as
  GitHub's own repo-delete flow — this audience will recognize it
  immediately.

---

## 11. Screen: Evaluation admin

**Route:** `/admin/evaluation` · token-gated

Benchmarks the AI reviewer itself against a labeled dataset. Used rarely,
by whoever owns model quality — treat as a utility screen, not a polished
daily surface.

**Layout:**
1. Two panels: Dataset versions (build new · list past) · Active promotion
   (which model/prompt version is live)
2. Eval runs table:

| Run | Dataset | Precision | Recall | Action |
|---|---|---|---|---|
| `eval-run-014` | v6 | 0.83 | 0.71 | Promote |

**Notes**
- Every action here (build dataset, run benchmark, promote) is a
  long-running job — represent each as a row with a status pill (`running`
  accent / `done` good / `failed` bad), never a blocking spinner over the
  whole page.
- "Promote" is the one consequential action on this screen — it changes
  what real users see — so it's the only button styled with the accent
  color; everything else here is neutral/utility styling.

---

## 12. Screen: Fine-tune admin

**Route:** `/admin/finetune` · token-gated

Manages custom model training jobs end to end: kick off a job, benchmark
the result against the baseline, and roll back if a shadow-deployed
candidate underperforms.

**Layout:**
1. Jobs list — `job-2026-09-01 · qwen2.5-coder:7b · lora · complete (good)`,
   `job-2026-08-14 · qwen2.5-coder:7b · lora · failed (bad)`
2. Two panels: Compare (baseline vs candidate, metric deltas side by side)
   · Shadow-eval results (candidate scored against live traffic, not yet
   promoted)

**Notes**
- A job detail view shows its training log tail + resulting metrics once
  complete — same "row with status pill, no page-blocking spinner" pattern
  as Evaluation admin.
- **Rollback** is a single, clearly-labeled destructive-toned button (uses
  the `bad` token, not accent) — it reverts the live model to the previous
  promotion, so it earns the same visual weight as Delete-data on the
  Organization screen.

---

## 13. Component inventory

Build these once as shared Figma components — every screen above is
assembled from this set plus layout.

| Component | Variants / states | Used on |
|---|---|---|
| Status pill | good · warn · bad · neutral · accent; each with a label slot | Everywhere — run status, policy decision, severity, autofix status, job status |
| Metric tile | default · loading (skeleton) · unavailable | Overview |
| Finding card | collapsed · expanded · with/without autofix pill · voted/unvoted feedback | Run detail |
| Data table row | default · hover · disabled action · live-updating (queued run) | Runs, Task failures, Eval runs, Fine-tune jobs |
| Danger action block | default · confirm-typed · in-progress | Organization, Fine-tune rollback |
| Alert banner | info (accent) · warning · error; dismissible or persistent | Overview, Config parse errors |
| Code/YAML editor | editable · read-only diff (version restore) | Config |
| Installation switcher | 1 installation (no dropdown chevron) · multiple | Global shell |
| Empty state | no repos · no runs yet · no findings on a clean run | Repositories, Runs, Run detail |

---

## 14. Design tokens

Starter palette and type scale — bring these in as Figma styles/variables
before building screens, so every wireframe above maps directly onto real
components.

### Color

| Token | Light | Dark |
|---|---|---|
| `ink/900` (primary text) | `#171b22` | `#eef0f2` |
| `ink/700` | `#333b46` | `#cbd1d8` |
| `ink/500` (secondary text) | `#57626f` | `#8d97a1` |
| `paper/0` (page background) | `#f3f5f4` | `#14171c` |
| `surface/1` (card background) | `#ffffff` | `#1b1f26` |
| `line` (hairline border) | `#dbe0e0` | `#2b313a` |
| `accent` (interactive/brand) | `#a3721f` | `#d6a75c` |
| `good` | `#276a45` | `#6fbf8f` |
| `warn` | `#b5590f` | `#e0975a` |
| `bad` | `#a5332a` | `#e08a83` |
| `risk/critical` | `#7a2530` | `#e4a2a9` |

- The accent (ochre) is reserved for interactive/brand moments —
  installation switcher, primary buttons, active states. It never doubles
  as a severity or status color, which stay in the good/warn/bad/
  risk-critical set above.
- Define both light and dark values as Figma variable modes, not one static
  palette.

### Type

| Role | Typeface | Weight | Size |
|---|---|---|---|
| Display / h1 | Archivo | 800 | 36px |
| Heading / h2 | Archivo | 700 | 24px |
| Subhead / h3 | Archivo | 600 | 17px |
| Body | Source Sans 3 | 400 | 15.5px |
| Mono / label | JetBrains Mono | 500 | 13–14px |

Mono is used for SHAs, status pill labels, eyebrows, route paths, and raw
metadata — anywhere the content is closer to data than prose.

### Spacing & radius

Spacing scale (px): `4 · 8 · 14 · 22 · 32 · 44`

- Radius: 4px for pills/badges/small controls, 8px for cards and panels.
  Nothing larger — this is an operator tool, not a marketing surface, and
  sharper corners read as more instrumented.

---

*Prepared for Figma handoff — see also the rendered HTML version at
`docs/dashboard-spec.html` for a visual pass with the tokens applied.*

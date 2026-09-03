# Fine-tuning a custom code-review model (Phase 16)

This is the last, and most conditional, capability in the roadmap. It exists
so an operator who has already accumulated thousands of consented,
human-validated review examples — and who has evidence that prompting and
retrieval alone have hit their limit — has a *safe path* to a custom model.
It is not a recommendation to fine-tune, and every gate described below is
designed to fail closed rather than let an under-validated candidate model
anywhere near a real merge decision.

Everything in this phase is off by default (`FINETUNE_ENABLED=false`). None
of it changes what the live reviewer does unless an operator explicitly
promotes a candidate through the same gate described below.

## Prerequisites this tooling does not (and cannot) satisfy for you

The roadmap is explicit that fine-tuning is only appropriate once:

- Thousands of diverse, human-validated examples exist.
- Dataset licenses and customer consent are clear.
- Labels (accepted/rejected findings, severity) are low-noise.
- A frozen holdout benchmark exists that is never trained on.
- Prompting/retrieval have demonstrably reached their practical limit.

`app.finetune` enforces the first of these mechanically
(`finetune_min_training_examples`, default 1000 — raise it for your actual
"thousands" bar) and reuses the existing frozen benchmark
(`app.evaluation.benchmark`) for the fourth. The rest — licensing, consent,
label quality, and whether prompting has actually plateaued — are
organizational judgment calls this code cannot make for you.

## Pipeline

1. **Build a dataset version** (Phase 15, unchanged):
   `POST /api/v1/eval/dataset/build`. This already filters to consented,
   `"useful"`-confirmed feedback and redacts secrets/emails/repository
   identity (`app.evaluation.redaction`).
2. **Create a fine-tune job**:
   `POST /api/v1/finetune/jobs {"dataset_version_id": N}`. Rejected with
   `422` if the dataset has fewer than `finetune_min_training_examples`
   items.
3. **Run the job**: `POST /api/v1/finetune/jobs/{id}/run`, or let
   `app.tasks.finetune.run_finetune_job_task` run it asynchronously. This
   exports the dataset to instruction/response JSONL
   (`app.finetune.export`) and invokes the external trainer configured at
   `finetune_trainer_command` — **this application does not bundle a
   trainer**; point this at a LoRA/QLoRA script (axolotl, unsloth, peft,
   etc.) you have vetted and provisioned with appropriate hardware, the
   same boundary `ANALYSIS_DOCKER_BINARY` draws around the deterministic
   analysis sandbox.
4. **Register the model** (optional, `finetune_ollama_create_enabled`):
   builds an Ollama `Modelfile` (`FROM <base> / ADAPTER <path>`) and runs
   `ollama create`, so the fine-tuned model becomes reachable as an
   ordinary model tag through the *existing* `ReviewModel` interface
   (`app.ai.model.OllamaReviewModel`) — no new provider code is needed.
5. **Evaluate against the frozen benchmark**:
   `POST /api/v1/finetune/jobs/{id}/benchmark` runs the same fixed
   benchmark (`app.evaluation.benchmark`, including the Phase 16 red-team
   cases below) against the candidate's `output_model` and persists an
   `EvalRun`, exactly like `POST /eval/benchmark/run` does for the live
   model.
6. **Compare against the current baseline**:
   `POST /api/v1/finetune/compare {"candidate_run_id", "baseline_run_id"}`
   enforces `finetune_max_recall_regression` and
   `finetune_max_false_positive_rate_increase` — the concrete form of "does
   not materially worsen security recall or false-positive rate."
7. **Promote** (unchanged Phase 15 gate, not duplicated here):
   `POST /api/v1/eval/promotions {"eval_run_id": <candidate run>}`. This
   still requires the candidate's own `EvalRun` to independently clear
   `eval_promotion_min_precision`/`eval_promotion_min_recall` — the
   Phase 16 comparison in step 6 is an additional guardrail on top of this,
   not a replacement for it.
8. **Shadow/canary traffic** (`finetune_shadow_eval_enabled`): once a
   candidate model is set as `finetune_shadow_candidate_model`, every
   completed live review is, in the background, also scored by the
   candidate and logged to `shadow_eval_results`
   (`GET /api/v1/finetune/shadow-results`). This never blocks, delays, or
   feeds back into the live `AIReview`, `PolicyDecision`, or any comment —
   it exists purely so a candidate's real-world behavior is visible before
   promotion.
9. **Rollback**: `POST /api/v1/finetune/rollback` immediately re-promotes
   the configuration from before the current promotion. `ModelPromotion`
   rows are additive and immutable, so this creates a new latest row rather
   than deleting anything — the full promotion history stays intact for
   audit, and `GET /api/v1/eval/promotions/active` reflects the rollback
   right away.

## Red-teaming

`app.evaluation.benchmark` includes, alongside the Phase 15 clean/
known-bug/security/prompt-injection cases, two Phase 16 categories:

- `fabrication_bait` — a trivial, behavior-preserving diff a model prone to
  hallucinating findings (a known LoRA overfitting failure mode) might
  flag anyway. Any reported finding is a false positive by construction.
- `overconfidence_bait` — a real but low-severity, context-dependent bug.
  Escalating it to a high/critical finding is scored as a severity
  mismatch, the closest signal this benchmark's scoring gives to
  "overconfidence" without a dedicated confidence-calibration harness.

Extend `FIXED_BENCHMARK_CASES` with more cases in either category (or a new
one) as red-teaming surfaces further failure modes; bump a case's `slug`
(e.g. `-v2`) rather than editing an existing case's `diff_text`/
`expected_findings` in place, so past `EvalRun` rows stay reproducible.

## Admin auth

`app/api/v1/finetune.py` is gated by `finetune_enabled` +
`finetune_admin_token`, mirroring the Phase 15 evaluation admin API exactly.
This is a cross-tenant governance surface with no per-organization RBAC yet
— that is Phase 17's job.

## What this phase deliberately does not do

- It does not implement or bundle a trainer.
- It does not let a fine-tuned model influence a live review or merge
  decision without going through the unchanged Phase 15 promotion gate.
- It does not change the rule that the policy engine, not any model,
  controls merging (Phase 7) — fine-tuning only ever changes which
  `ReviewModel` the *advisory* AI reviewer calls.

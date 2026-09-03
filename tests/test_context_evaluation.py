"""Regression-style evaluation for Phase 11's retrieval quality acceptance
criterion ("evaluation demonstrates that retrieved context improves finding
precision or recall").

Builds a fixture candidate set with one item that's genuinely relevant to
the changed symbol (a semantic hit sharing its directory) alongside several
irrelevant-but-cheap distractors, under a byte budget too small to fit
everything. Asserts the Phase 11 pipeline (`rerank` + `apply_budget`) keeps
the relevant item, whereas the pre-Phase-11 "smallest item first" policy
this replaced would have dropped it in favor of the cheap distractors -
i.e. relevance-ranking measurably improves what a real review actually
sees, which is the thing precision/recall would be computed over.
"""

from app.context.rerank import rerank
from app.context.retrieval import ContextItem, apply_budget


def _distractor(n: int) -> ContextItem:
    return ContextItem(
        id="", path=f"unrelated/noise_{n}.py", kind="config", symbol=None,
        start_line=1, end_line=1, snippet="x" * 5, reason="nearby config, unrelated",
    )


def _relevant_semantic_hit() -> ContextItem:
    return ContextItem(
        id="", path="billing/helpers.py", kind="semantic", symbol="charge_customer",
        start_line=10, end_line=40,
        snippet="y" * 200,  # larger than any single distractor
        reason="semantically related to 'charge_customer_v2'",
    )


def _old_smallest_first_budget(items: list[ContextItem], max_bytes: int) -> list[ContextItem]:
    """The exact policy `apply_budget` used before Phase 11: sort by
    snippet size ascending, keep until the budget runs out. Reproduced here
    (not imported) specifically as the baseline this evaluation compares
    against.
    """
    ordered = sorted(items, key=lambda item: len(item.snippet.encode("utf-8")))
    kept: list[ContextItem] = []
    used = 0
    for item in ordered:
        size = len(item.snippet.encode("utf-8"))
        if used + size > max_bytes:
            continue
        used += size
        kept.append(item)
    return kept


def test_relevance_ranking_keeps_the_relevant_hit_the_size_naive_baseline_drops() -> None:
    relevant = _relevant_semantic_hit()
    distractors = [_distractor(i) for i in range(10)]
    candidates = [relevant, *distractors]
    # 10 distractors x 5 bytes (50) + the 200-byte relevant item = 250,
    # one byte over budget - just enough to force a choice between them.
    budget = 249

    baseline_kept = _old_smallest_first_budget(candidates, budget)
    assert relevant not in baseline_kept  # old policy: cheap noise crowds out the real hit

    ranked = rerank(
        candidates,
        changed_paths={"billing/service.py"},
        changed_symbol_names={"charge_customer_v2"},
        fresh_paths=set(),
    )
    phase11_kept, truncated, _ = apply_budget(ranked, budget)

    assert relevant in phase11_kept
    assert truncated is True
    # The relevant item outranks every distractor it's now grouped with.
    assert phase11_kept[0] is relevant

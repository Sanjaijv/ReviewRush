from unittest.mock import MagicMock

from app.evaluation.benchmark import (
    ALL_CATEGORIES,
    FIXED_BENCHMARK_CASES,
    load_fixed_benchmark_cases,
)
from app.models import BenchmarkCase


def test_fixed_benchmark_covers_every_required_category() -> None:
    categories = {case.category for case in FIXED_BENCHMARK_CASES}
    assert categories == set(ALL_CATEGORIES)


def test_fixed_benchmark_slugs_are_unique() -> None:
    slugs = [case.slug for case in FIXED_BENCHMARK_CASES]
    assert len(slugs) == len(set(slugs))


def test_clean_case_expects_no_findings() -> None:
    clean_cases = [c for c in FIXED_BENCHMARK_CASES if c.category == "clean"]
    assert clean_cases
    for case in clean_cases:
        assert case.expected_findings == []


def test_load_fixed_benchmark_cases_creates_new_rows() -> None:
    db = MagicMock()
    db.query.return_value.filter_by.return_value.one_or_none.return_value = None

    load_fixed_benchmark_cases(db)

    added = [c.args[0] for c in db.add.call_args_list if isinstance(c.args[0], BenchmarkCase)]
    assert len(added) == len(FIXED_BENCHMARK_CASES)
    db.commit.assert_called_once()


def test_load_fixed_benchmark_cases_updates_existing_row_in_place() -> None:
    # db.query(...).one_or_none() returns the same mocked row regardless of
    # slug, so every case in the fixed list updates *this* row in place -
    # what matters is that it ends up matching the last case processed and
    # that no new BenchmarkCase row was ever added.
    db = MagicMock()
    existing = BenchmarkCase(id=1, slug=FIXED_BENCHMARK_CASES[0].slug, category="stale")
    db.query.return_value.filter_by.return_value.one_or_none.return_value = existing

    load_fixed_benchmark_cases(db)

    assert existing.category == FIXED_BENCHMARK_CASES[-1].category
    assert existing.diff_text == FIXED_BENCHMARK_CASES[-1].diff_text
    assert not any(isinstance(c.args[0], BenchmarkCase) for c in db.add.call_args_list)

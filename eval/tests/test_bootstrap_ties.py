"""Bootstrap CIs (seeded, resample over items) and CI-overlap tie
rendering (SPEC §6)."""

from __future__ import annotations

import pytest

from rancor.score import RankedEntry, bootstrap_ci, rank_with_ties


def test_bootstrap_ci_seeded_and_reproducible():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    a = bootstrap_ci(values, b=500, seed=7)
    b = bootstrap_ci(values, b=500, seed=7)
    assert a == b
    lo, hi = a
    assert lo <= 3.0 <= hi  # CI of the mean brackets the sample mean
    assert lo >= 1.0 and hi <= 5.0


def test_bootstrap_ci_seed_drives_resampling():
    # enough distinct values that these two fixed seeds' resample
    # distributions produce different quantiles (verified empirically;
    # deterministic given the fixed seeds)
    values = [float(i) * 1.37 for i in range(30)]
    assert bootstrap_ci(values, b=200, seed=1) != bootstrap_ci(values, b=200, seed=2)


def test_bootstrap_ci_degenerate_single_item():
    assert bootstrap_ci([42.0], b=100, seed=0) == (42.0, 42.0)


def test_bootstrap_ci_empty_raises():
    with pytest.raises(ValueError):
        bootstrap_ci([], b=100, seed=0)


def test_bootstrap_ci_default_b_smoke():
    lo, hi = bootstrap_ci([10.0, 20.0, 30.0], seed=0)  # B=10,000 (SPEC §6)
    assert lo < 20.0 < hi


def _entry(name: str, point: float, lo: float, hi: float) -> RankedEntry:
    return RankedEntry(name=name, point=point, lo=lo, hi=hi)


def test_overlapping_intervals_share_rank():
    ranked = rank_with_ties(
        [
            _entry("a", 90.0, 85.0, 95.0),
            _entry("b", 88.0, 84.0, 92.0),  # overlaps a -> tie
            _entry("c", 50.0, 45.0, 55.0),  # clear of both
        ]
    )
    by_name = {e.name: e for e in ranked}
    assert by_name["a"].rank == by_name["b"].rank == 1
    assert by_name["a"].tied and by_name["b"].tied
    assert by_name["c"].rank == 3  # rank skips the tied block
    assert not by_name["c"].tied


def test_non_overlapping_strict_ordering():
    ranked = rank_with_ties(
        [_entry("a", 90.0, 88.0, 92.0), _entry("b", 80.0, 78.0, 82.0)]
    )
    assert [(e.name, e.rank, e.tied) for e in ranked] == [("a", 1, False), ("b", 2, False)]


def test_tie_groups_chain_transitively():
    """b overlaps both a and c; a and c don't overlap directly — they still
    share one tie group (no ordering is defensible inside the chain)."""
    ranked = rank_with_ties(
        [
            _entry("a", 90.0, 86.0, 94.0),
            _entry("b", 85.0, 81.0, 89.0),
            _entry("c", 80.0, 76.0, 84.0),
        ]
    )
    assert {e.rank for e in ranked} == {1}
    assert all(e.tied for e in ranked)


def test_chained_ties_are_marked_as_chained():
    """Live-site audit finding: the leaderboard states
    "shared rank = tie by CI overlap", but ties chain transitively, so two
    models whose intervals do NOT overlap can share a rank by hopping
    through a third. On the published run grok [96.25, 100.00] and llama
    [62.50, 92.50] are disjoint and both render "= 1" — a 20-point gap
    shown as a tie under a rule that says otherwise.

    The grouping is defensible; stating a pairwise rule for it is not. So
    a group must report whether every pair inside it actually overlaps.
    """
    from rancor.score import RankedEntry, rank_with_ties

    # a-b overlap, b-c overlap, a-c do NOT: one chained group
    chained = rank_with_ties([
        RankedEntry(name="a", point=95.0, lo=90.0, hi=100.0),
        RankedEntry(name="b", point=87.0, lo=80.0, hi=95.0),
        RankedEntry(name="c", point=72.0, lo=60.0, hi=85.0),
    ])
    assert {e.rank for e in chained} == {1}
    assert all(e.tied for e in chained)
    assert all(e.tie_chained for e in chained), (
        "a and c do not overlap; the group is only tied via b"
    )

    # every pair genuinely overlaps -> not chained
    direct = rank_with_ties([
        RankedEntry(name="a", point=95.0, lo=90.0, hi=100.0),
        RankedEntry(name="b", point=93.0, lo=91.0, hi=99.0),
    ])
    assert all(e.tied for e in direct)
    assert not any(e.tie_chained for e in direct)

    # a lone entry is neither tied nor chained
    solo = rank_with_ties([RankedEntry(name="a", point=95.0, lo=90.0, hi=100.0)])
    assert not solo[0].tied and not solo[0].tie_chained

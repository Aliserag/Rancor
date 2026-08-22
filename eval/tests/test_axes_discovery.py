"""Axis discovery + the SPEC M1 zero-code-change dummy-axis proof."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rancor.axes import discover_axes
from rancor.schema import load_prompt_set
from rancor.validate import validate_prompt_set

from .conftest import make_axis_pack, synthetic_item

RANCOR_PKG = Path(__file__).resolve().parents[1] / "rancor"


def test_discovers_repo_axes(repo_prompts):
    axes = discover_axes(repo_prompts)
    # count is whatever the repo ships; the invariants below are what matter
    assert len(axes) >= 1
    for config in axes.values():
        # focal first, then comparisons (SPEC §2 default groups)
        assert config.default_groups[0] == config.focal_group
        assert len(config.default_groups) == 1 + len(config.comparison_groups)
        # every comparison group carries a documented rationale (SPEC §0)
        assert all(c.rationale.strip() for c in config.comparison_groups)


def test_axis_id_must_match_directory(tmp_path):
    prompts = tmp_path / "v1.0"
    make_axis_pack(prompts, "axis_one")
    config = prompts / "axes" / "axis_one" / "axis.yaml"
    config.write_text(config.read_text().replace("axis_one", "wrong_name"), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match directory"):
        discover_axes(prompts)


def test_dummy_third_axis_requires_zero_code_changes(prompts_copy):
    """SPEC M1 acceptance: adding an axis directory works with no code
    changes — proven by driving only public library entry points.

    Asserted relative to whatever the repo ships, so changing the shipped
    axis set cannot silently turn this proof into a tautology.
    """
    before = len(discover_axes(prompts_copy))
    make_axis_pack(
        prompts_copy,
        "dummy_axis",
        items_by_category={"stereotype_association": [synthetic_item("dummy_sa_1")]},
        lexicon_tokens={"GroupA": ["groupa"], "GroupB": ["groupb"]},
    )
    axes = discover_axes(prompts_copy)
    assert len(axes) == before + 1
    assert "dummy_axis" in axes

    prompt_set = load_prompt_set(prompts_copy)
    (dummy_item,) = prompt_set.items_for_axis("dummy_axis")
    # groups default from the dummy axis config: focal + comparisons
    assert dummy_item.groups == ["GroupA", "GroupB", "GroupC"]

    assert validate_prompt_set(prompts_copy) == []


def test_no_axis_names_hardcoded_in_package(repo_prompts):
    """standing rule 7: axes are data. No shipped axis id may appear
    in package code."""
    axis_ids = sorted(discover_axes(repo_prompts))
    pattern = re.compile("|".join(axis_ids))
    offenders = [
        str(path)
        for path in RANCOR_PKG.rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []

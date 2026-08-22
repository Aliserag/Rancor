"""Freeze hash: deterministic, order-invariant, edit-sensitive."""

from __future__ import annotations

import yaml

from rancor.freeze import FREEZE_FILENAME, freeze, prompt_set_hash, read_frozen_hash
from rancor.schema import load_prompt_set


def test_hash_is_deterministic(repo_prompts):
    h1 = prompt_set_hash(load_prompt_set(repo_prompts))
    h2 = prompt_set_hash(load_prompt_set(repo_prompts))
    assert h1 == h2
    assert len(h1) == 64


def test_hash_invariant_to_file_item_order(prompts_copy):
    baseline = prompt_set_hash(load_prompt_set(prompts_copy))
    # reverse the on-disk order of items in one category file
    path = next((prompts_copy / "axes").glob("*/stereotype_association.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if len(raw.get("items") or []) < 2:
        return  # nothing to reorder in this tree
    raw["items"] = list(reversed(raw["items"]))
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert prompt_set_hash(load_prompt_set(prompts_copy)) == baseline


def test_hash_changes_on_any_edit(prompts_copy):
    baseline = prompt_set_hash(load_prompt_set(prompts_copy))
    path = next((prompts_copy / "axes").glob("*/stereotype_association.yaml"))
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["items"][0]["template"] = raw["items"][0]["template"] + " EDITED"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert prompt_set_hash(load_prompt_set(prompts_copy)) != baseline


def test_freeze_writes_hash_file(prompts_copy):
    digest = freeze(prompts_copy, strict=False)
    assert read_frozen_hash(prompts_copy) == digest
    assert (prompts_copy / FREEZE_FILENAME).is_file()


def test_freeze_strict_refuses_below_floors(tmp_path):
    """Release freeze must refuse while a set is under its floors."""
    import pytest

    from .conftest import make_axis_pack, synthetic_item

    prompts = tmp_path / "v1.0"
    make_axis_pack(
        prompts,
        "axis_x",
        items_by_category={"dog_whistles": [synthetic_item("only_item")]},
    )
    with pytest.raises(ValueError, match="refusing to freeze"):
        freeze(prompts, strict=True)


def test_freeze_strict_succeeds_on_repo_set(prompts_copy):
    """The promoted repo set meets all release gates; strict freeze works
    (run on a copy — the real freeze is a deliberate release action)."""
    digest = freeze(prompts_copy, strict=True)
    assert read_frozen_hash(prompts_copy) == digest

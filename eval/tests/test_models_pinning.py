"""SPEC §3: the runner must fail loudly on unpinned snapshots."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from rancor.models import load_models


def _write(tmp_path: Path, models: list[dict]) -> Path:
    path = tmp_path / "models.yaml"
    path.write_text(yaml.safe_dump({"models": models}), encoding="utf-8")
    return path


def test_unpinned_snapshot_fails_loudly_for_real_runs(tmp_path):
    path = _write(
        tmp_path,
        [
            {"name": "a", "litellm_id": "provider/model-2026-01-01",
             "snapshot_id": "model-2026-01-01"},
            {"name": "b", "litellm_id": None, "snapshot_id": None},
        ],
    )
    with pytest.raises(ValueError, match=r"unpinned.*\['b'\]"):
        load_models(path, require_pinned=True)


def test_unpinned_allowed_for_dry_run(tmp_path):
    path = _write(tmp_path, [{"name": "b"}])
    (slot,) = load_models(path, require_pinned=False)
    assert not slot.is_pinned


def test_duplicate_names_rejected(tmp_path):
    path = _write(tmp_path, [{"name": "a"}, {"name": "a"}])
    with pytest.raises(ValueError, match="duplicate"):
        load_models(path, require_pinned=False)


def test_cost_guard_refuses_real_run_without_confirm(tmp_path):
    """SPEC §8: estimated call count printed; no spend without --confirm.
    Uses pinned fake models so the guard (not pinning) is what refuses."""
    from rancor import run as run_module

    from .conftest import make_axis_pack, synthetic_item

    prompts = tmp_path / "v1.0"
    make_axis_pack(
        prompts,
        "axis_x",
        items_by_category={
            "double_standards": [synthetic_item("item_a", condition_variants=["base"])]
        },
    )
    models = _write(
        tmp_path,
        [{"name": "a", "litellm_id": "provider/model-x-2026", "snapshot_id": "model-x-2026"}],
    )
    exit_code = run_module.main(
        ["--prompts-root", str(prompts), "--models", str(models), "--out", str(tmp_path / "r")]
    )
    assert exit_code == 2
    assert not (tmp_path / "r").exists(), "cost guard must refuse before any run dir is created"


def test_repo_models_yaml_is_pinned():
    """The shipped config is fully pinned (SPEC §3): 5 slots, every slot
    carries a litellm route, a snapshot id, and a lab for self-lab
    exclusion."""
    repo_models = Path(__file__).resolve().parents[2] / "models.yaml"
    slots = load_models(repo_models, require_pinned=True)
    assert len(slots) == 5  # SPEC §3 default slots
    assert all(slot.is_pinned for slot in slots)
    assert all(slot.lab for slot in slots)
    assert len({slot.lab for slot in slots}) == 5  # one slot per lab

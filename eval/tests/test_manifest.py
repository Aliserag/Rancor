"""Run manifest: written at run start, required by downstream stages
(standing rule 4)."""

from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from rancor.manifest import MANIFEST_FILENAME, load_manifest
from rancor.run import execute_run

from .conftest import make_axis_pack, synthetic_item


@pytest.fixture()
def dry_run_dir(tmp_path):
    prompts = tmp_path / "v1.0"
    make_axis_pack(
        prompts,
        "axis_x",
        items_by_category={
            "double_standards": [synthetic_item("item_a", condition_variants=["base"])]
        },
    )
    models = tmp_path / "models.yaml"
    models.write_text(yaml.safe_dump({"models": [{"name": "m1"}]}), encoding="utf-8")
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, tmp_path / "judges.yaml", dry_run=True)
    return run_dir


def test_manifest_written_with_required_fields(dry_run_dir):
    assert (dry_run_dir / MANIFEST_FILENAME).is_file()
    manifest = load_manifest(dry_run_dir)
    assert manifest.fixture is True
    assert len(manifest.prompt_set_sha256) == 64
    assert manifest.prompt_set_frozen is False  # tmp tree has no freeze file
    assert [m.name for m in manifest.models] == ["m1"]
    assert manifest.judges == []  # judges.yaml absent in this fixture
    assert manifest.decoding["base"].temperature == 0.0
    assert manifest.decoding["base"].n == 1
    assert manifest.decoding["robustness"].temperature == 0.7
    assert manifest.decoding["robustness"].n == 3


def test_missing_manifest_refuses_processing(tmp_path):
    with pytest.raises(ValueError, match="refusing to process"):
        load_manifest(tmp_path)


def test_corrupt_manifest_rejected(dry_run_dir):
    (dry_run_dir / MANIFEST_FILENAME).write_text('{"run_id": "x"}', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_manifest(dry_run_dir)

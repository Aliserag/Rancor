"""Shared test helpers: the real repo prompt tree + synthetic axis packs."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REPO_PROMPTS = REPO_ROOT / "prompts" / "v1.0"
DATA_DIR = Path(__file__).resolve().parent / "data"

CATEGORY_NAMES = [
    "stereotype_association",
    "dog_whistles",
    "biased_refusals",
    "double_standards",
    "loaded_presuppositions",
    "agentic_scenarios",
]


@pytest.fixture()
def repo_prompts() -> Path:
    assert REPO_PROMPTS.is_dir(), "repo prompt tree missing"
    return REPO_PROMPTS


@pytest.fixture()
def prompts_copy(tmp_path: Path) -> Path:
    """A mutable copy of the real prompt tree for planting bad data."""
    dest = tmp_path / "v1.0"
    shutil.copytree(REPO_PROMPTS, dest)
    return dest


def make_axis_pack(
    prompts_root: Path,
    axis_id: str,
    focal_group: str = "GroupA",
    comparison_groups: tuple[str, ...] = ("GroupB", "GroupC"),
    items_by_category: dict[str, list[dict]] | None = None,
    extra_config: dict | None = None,
    lexicon_tokens: dict[str, list[str]] | None = None,
) -> Path:
    """Write a minimal, structurally complete synthetic axis pack."""
    axis_dir = prompts_root / "axes" / axis_id
    axis_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "axis_id": axis_id,
        "display_name": axis_id.title(),
        "focal_group": focal_group,
        "comparison_groups": [
            {"group": g, "rationale": f"synthetic comparison {g}"} for g in comparison_groups
        ],
        "name_pools": {},
        "keyword_list": None,
        "seed_sources": [],
    }
    config.update(extra_config or {})
    (axis_dir / "axis.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    if lexicon_tokens is not None:
        (axis_dir / "identity_lexicon.yaml").write_text(
            yaml.safe_dump({"tokens": lexicon_tokens}), encoding="utf-8"
        )
    rubrics_dir = axis_dir / "rubrics"
    rubrics_dir.mkdir(exist_ok=True)
    for category in CATEGORY_NAMES:
        items = (items_by_category or {}).get(category, [])
        (axis_dir / f"{category}.yaml").write_text(
            yaml.safe_dump({"axis": axis_id, "category": category, "items": items}),
            encoding="utf-8",
        )
        # axis symmetry requires every pack to carry the same rubric file set
        (rubrics_dir / f"{category}.md").write_text(
            f"# Rubric: {category} (synthetic test rubric)\n", encoding="utf-8"
        )
    return axis_dir


def synthetic_item(item_id: str, **overrides) -> dict:
    """A valid synthetic prompt item dict (clearly test-only data)."""
    item = {
        "id": item_id,
        "template": "A synthetic {group} test template",
        "is_counterfactual": True,
        "condition_variants": ["base"],
        "source": "https://example.invalid/synthetic-test-source",
        "rationale": "synthetic test item",
    }
    item.update(overrides)
    return item


def load_jsonl(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (DATA_DIR / name).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

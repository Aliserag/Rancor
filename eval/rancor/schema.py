"""Prompt-set data model and loader (SPEC §2).

One YAML file per category per axis under ``prompts/v1.0/axes/<axis>/``,
plus matched cross-axis trope templates under
``prompts/v1.0/shared_tropes/`` (SPEC §6).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from rancor.axes import AxisConfig, axes_root, discover_axes

GROUP_SLOT = "{group}"
SHARED_TROPES_DIRNAME = "shared_tropes"


class Category(StrEnum):
    STEREOTYPE_ASSOCIATION = "stereotype_association"
    DOG_WHISTLES = "dog_whistles"
    BIASED_REFUSALS = "biased_refusals"
    DOUBLE_STANDARDS = "double_standards"
    LOADED_PRESUPPOSITIONS = "loaded_presuppositions"
    AGENTIC_SCENARIOS = "agentic_scenarios"


# The five categories scored absolutely (Handling Score, SPEC §6) — every
# category except the counterfactual-gap one.
ABSOLUTE_CATEGORIES = [c for c in Category if c is not Category.DOUBLE_STANDARDS]


class Condition(StrEnum):
    BASE = "base"
    COT = "cot"
    PERSONA = "persona"


class PromptItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    axis: str
    category: Category
    template: str
    is_counterfactual: bool
    # Filled from the axis config's focal + comparison groups when omitted
    # in the YAML (SPEC §2); empty for non-counterfactual items.
    groups: list[str] = []
    shared_trope_id: str | None = None
    condition_variants: list[Condition]
    source: str
    upstream_id: str | None = None
    attribution: str | None = None
    rationale: str
    rubric_notes: str | None = None
    in_robustness_slice: bool = False


class SharedTrope(BaseModel):
    """A matched cross-axis trope template (SPEC §6): the same structure
    instantiated once per axis, plus a non-group control statement."""

    model_config = ConfigDict(extra="forbid")

    id: str
    template: str
    control: str
    source: str
    rationale: str


class PromptSet(BaseModel):
    axes: dict[str, AxisConfig]
    items: list[PromptItem]
    shared_tropes: list[SharedTrope]

    def items_for_axis(self, axis_id: str) -> list[PromptItem]:
        return [i for i in self.items if i.axis == axis_id]


def category_filename(category: Category) -> str:
    return f"{category.value}.yaml"


def load_category_file(path: Path, axis: AxisConfig, category: Category) -> list[PromptItem]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    file_axis = raw.get("axis", axis.axis_id)
    file_category = raw.get("category", category.value)
    if file_axis != axis.axis_id or file_category != category.value:
        raise ValueError(
            f"{path}: file header ({file_axis}/{file_category}) does not match "
            f"location ({axis.axis_id}/{category.value})"
        )
    items: list[PromptItem] = []
    for entry in raw.get("items") or []:
        entry.setdefault("axis", axis.axis_id)
        entry.setdefault("category", category.value)
        item = PromptItem.model_validate(entry)
        if not item.groups and GROUP_SLOT in item.template:
            item = item.model_copy(update={"groups": axis.default_groups})
        items.append(item)
    return items


def load_shared_tropes(prompts_root: Path) -> list[SharedTrope]:
    tropes_dir = prompts_root / SHARED_TROPES_DIRNAME
    tropes: list[SharedTrope] = []
    if not tropes_dir.is_dir():
        return tropes
    for path in sorted(tropes_dir.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in raw.get("tropes") or []:
            tropes.append(SharedTrope.model_validate(entry))
    return tropes


def load_prompt_set(prompts_root: Path) -> PromptSet:
    axes = discover_axes(prompts_root)
    items: list[PromptItem] = []
    for axis_id, config in axes.items():
        axis_dir = axes_root(prompts_root) / axis_id
        for category in Category:
            path = axis_dir / category_filename(category)
            if path.is_file():
                items.extend(load_category_file(path, config, category))
    return PromptSet(axes=axes, items=items, shared_tropes=load_shared_tropes(prompts_root))

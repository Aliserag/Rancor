"""Prompt-set validator (SPEC §2 counterfactual hygiene + M1 acceptance).

Runs in CI. Two severities:
- errors: structural violations, always fatal
- strict-only errors (``--strict``, used at freeze time): per-category item
  floors, persona prerequisites — release gates, not development gates.

The same rules apply identically to every axis (standing rule 7).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from rancor.axes import AxisConfig, axes_root, discover_axes
from rancor.schema import (
    GROUP_SLOT,
    Category,
    Condition,
    PromptItem,
    PromptSet,
    category_filename,
    load_prompt_set,
)

IDENTITY_LEXICON_FILENAME = "identity_lexicon.yaml"
ITEM_FLOOR_PER_CATEGORY = 30  # SPEC §2 hard floor


def load_identity_lexicon(axis_dir: Path) -> dict[str, list[str]]:
    path = axis_dir / IDENTITY_LEXICON_FILENAME
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): [str(t) for t in v] for k, v in (raw.get("tokens") or {}).items()}


def find_identity_tokens_outside_slot(template: str, lexicon: dict[str, list[str]]) -> list[str]:
    """Identity tokens must appear ONLY in the {group} slot (SPEC §2)."""
    stripped = template.replace(GROUP_SLOT, " ")
    hits: list[str] = []
    for tokens in lexicon.values():
        for token in tokens:
            if re.search(rf"(?<![a-zA-Z]){re.escape(token)}(?![a-zA-Z])", stripped, re.IGNORECASE):
                hits.append(token)
    return hits


def _all_pool_names(config: AxisConfig) -> list[str]:
    return [name for pool in config.name_pools.values() for names in pool.values() for name in names]


def validate_items(
    prompt_set: PromptSet, prompts_root: Path, strict: bool = False
) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    trope_ids = {t.id for t in prompt_set.shared_tropes}
    lexicons = {
        axis_id: load_identity_lexicon(axes_root(prompts_root) / axis_id)
        for axis_id in prompt_set.axes
    }

    for item in prompt_set.items:
        where = f"{item.axis}/{item.category.value}/{item.id}"
        if item.id in seen_ids:
            errors.append(f"{where}: duplicate item id")
        seen_ids.add(item.id)

        if item.axis not in prompt_set.axes:
            errors.append(f"{where}: unknown axis {item.axis!r}")
            continue

        has_slot = GROUP_SLOT in item.template
        if has_slot and len(item.groups) < 2:
            errors.append(f"{where}: template has {GROUP_SLOT} but fewer than 2 groups")
        if item.groups and not has_slot:
            errors.append(f"{where}: groups given but template has no {GROUP_SLOT} slot")
        if item.is_counterfactual and not has_slot:
            errors.append(f"{where}: is_counterfactual but template has no {GROUP_SLOT} slot")

        # scoring reads groups[0] as the focal group (score.py is_focal), so
        # a list that leads with a comparison group scores the wrong group
        # as focal for this axis (E2E finding N1)
        axis_config = prompt_set.axes[item.axis]
        if item.groups and item.groups[0] not in axis_config.focal_forms:
            errors.append(
                f"{where}: group list leads with {item.groups[0]!r}, not this "
                f"axis's focal group {sorted(axis_config.focal_forms)}"
            )

        hits = find_identity_tokens_outside_slot(item.template, lexicons.get(item.axis, {}))
        if hits:
            errors.append(
                f"{where}: identity token(s) outside the {GROUP_SLOT} slot: {sorted(set(hits))}"
            )

        if Condition.BASE not in item.condition_variants:
            errors.append(f"{where}: condition_variants must include 'base'")

        if not item.source.strip():
            errors.append(f"{where}: empty source (attested URL or 'team-written')")
        if item.upstream_id and not (item.attribution or "").strip():
            errors.append(f"{where}: upstream_id set but no attribution (standing rule 3)")

        if item.shared_trope_id is not None and item.shared_trope_id not in trope_ids:
            errors.append(f"{where}: shared_trope_id {item.shared_trope_id!r} not defined")

        pool_names = _all_pool_names(prompt_set.axes[item.axis])
        name_hits = [n for n in pool_names if re.search(rf"\b{re.escape(n)}\b", item.template)]
        if name_hits:
            errors.append(f"{where}: persona pool name(s) in template: {name_hits}")

    if strict:
        errors.extend(_validate_release_gates(prompt_set))
    return errors


def _validate_release_gates(prompt_set: PromptSet) -> list[str]:
    """Freeze-time gates: per-axis floors and persona prerequisites."""
    errors: list[str] = []
    for axis_id, config in prompt_set.axes.items():
        axis_items = prompt_set.items_for_axis(axis_id)
        for category in Category:
            n = sum(1 for i in axis_items if i.category is category)
            if n < ITEM_FLOOR_PER_CATEGORY:
                errors.append(
                    f"{axis_id}/{category.value}: {n} items < hard floor "
                    f"{ITEM_FLOOR_PER_CATEGORY} (SPEC §2)"
                )
        uses_persona = any(Condition.PERSONA in i.condition_variants for i in axis_items)
        if uses_persona and not _all_pool_names(config):
            errors.append(f"{axis_id}: persona items exist but name_pools is empty")
        # Shared tropes must be instantiated in >=2 axes to be comparable.
    for trope in prompt_set.shared_tropes:
        axes_using = {i.axis for i in prompt_set.items if i.shared_trope_id == trope.id}
        if len(axes_using) < 2:
            errors.append(
                f"shared_tropes/{trope.id}: instantiated in {len(axes_using)} axes; "
                "parity view needs >=2 (SPEC §6)"
            )
    return errors


def validate_symmetry(prompts_root: Path) -> list[str]:
    """Axis packs must be structurally identical (standing rule 7):
    same six category files, same rubric file set. Bespoke axis.yaml fields
    are rejected by AxisConfig's extra="forbid" during discovery."""
    errors: list[str] = []
    try:
        axes = discover_axes(prompts_root)
    except (ValueError, ValidationError, yaml.YAMLError, OSError) as exc:
        # surfaces planted special-case configs as validation errors
        return [f"axis discovery failed: {exc}"]

    expected_files = {category_filename(c) for c in Category}
    rubric_sets: dict[str, set[str]] = {}
    for axis_id in axes:
        axis_dir = axes_root(prompts_root) / axis_id
        present = {p.name for p in axis_dir.glob("*.yaml")} - {
            "axis.yaml",
            IDENTITY_LEXICON_FILENAME,
        }
        missing = expected_files - present
        extra = present - expected_files
        if missing:
            errors.append(f"{axis_id}: missing category file(s): {sorted(missing)}")
        if extra:
            errors.append(f"{axis_id}: unexpected file(s) in axis pack: {sorted(extra)}")
        rubrics_dir = axis_dir / "rubrics"
        rubric_sets[axis_id] = (
            {p.name for p in rubrics_dir.glob("*.md")} if rubrics_dir.is_dir() else set()
        )
    reference = None
    for axis_id, rubrics in sorted(rubric_sets.items()):
        if reference is None:
            reference = (axis_id, rubrics)
        elif rubrics != reference[1]:
            errors.append(
                f"rubric sets differ: {reference[0]}={sorted(reference[1])} "
                f"vs {axis_id}={sorted(rubrics)}"
            )
    return errors


def validate_prompt_set(prompts_root: Path, strict: bool = False) -> list[str]:
    errors = validate_symmetry(prompts_root)
    try:
        prompt_set = load_prompt_set(prompts_root)
    except (ValueError, ValidationError, yaml.YAMLError, OSError) as exc:
        return errors + [f"prompt set failed to load: {exc}"]
    return errors + validate_items(prompt_set, prompts_root, strict=strict)


def validate_single_item(raw: dict, config: AxisConfig, lexicon: dict[str, list[str]]) -> PromptItem:
    """Parse-and-check helper used by extraction scripts on candidates."""
    item = PromptItem.model_validate(raw)
    hits = find_identity_tokens_outside_slot(item.template, lexicon)
    if hits:
        raise ValueError(f"{item.id}: identity token(s) outside slot: {hits}")
    return item


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    strict = "--strict" in args
    paths = [a for a in args if a != "--strict"]
    prompts_root = Path(paths[0]) if paths else Path("prompts/v1.0")
    errors = validate_prompt_set(prompts_root, strict=strict)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} error(s) in {prompts_root}", file=sys.stderr)
        return 1
    print(f"OK: {prompts_root} valid" + (" (strict)" if strict else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

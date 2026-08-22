"""Axis discovery and configuration.

Axes are self-contained data packs under ``prompts/v1.0/axes/<axis>/``.
This module discovers them dynamically; no axis name may ever be
hardcoded in this package (standing rule 7).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

AXIS_CONFIG_FILENAME = "axis.yaml"


class ComparisonGroup(BaseModel):
    """A comparison group with the documented rationale SPEC §0 requires."""

    model_config = ConfigDict(extra="forbid")

    group: str
    rationale: str


class SeedSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    url: str
    license: str


class AxisConfig(BaseModel):
    """Parsed ``axis.yaml``. ``extra="forbid"`` rejects bespoke per-axis
    fields — a planted special-case must fail validation (SPEC M1)."""

    model_config = ConfigDict(extra="forbid")

    axis_id: str
    display_name: str
    focal_group: str
    # Surface forms that also denote the focal group (e.g. a plural), so
    # templates written with a plural slot can still lead with the focal
    # group. Data, not code — scoring reads groups[0] as focal.
    focal_aliases: list[str] = []
    comparison_groups: list[ComparisonGroup]
    # name pool shape: {"focal"|"<group>": {"male": [...], "female": [...]}}
    name_pools: dict[str, dict[str, list[str]]] = {}
    keyword_list: list[str] | None = None
    seed_sources: list[SeedSource] = []

    @property
    def default_groups(self) -> list[str]:
        """Focal group first, then comparison groups (SPEC §2)."""
        return [self.focal_group] + [c.group for c in self.comparison_groups]

    @property
    def focal_forms(self) -> set[str]:
        """Every surface form that denotes this axis's focal group."""
        return {self.focal_group, *self.focal_aliases}


def axes_root(prompts_root: Path) -> Path:
    return prompts_root / "axes"


def discover_axes(prompts_root: Path) -> dict[str, AxisConfig]:
    """Scan ``<prompts_root>/axes/*/axis.yaml`` and parse each config.

    Raises ``ValueError`` if a directory name and its ``axis_id`` disagree,
    or if a pack is missing its config.
    """
    root = axes_root(prompts_root)
    if not root.is_dir():
        raise ValueError(f"no axes directory at {root}")
    configs: dict[str, AxisConfig] = {}
    for axis_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        config_path = axis_dir / AXIS_CONFIG_FILENAME
        if not config_path.is_file():
            raise ValueError(f"axis pack {axis_dir.name!r} has no {AXIS_CONFIG_FILENAME}")
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config = AxisConfig.model_validate(raw)
        if config.axis_id != axis_dir.name:
            raise ValueError(
                f"axis_id {config.axis_id!r} does not match directory {axis_dir.name!r}"
            )
        configs[config.axis_id] = config
    if not configs:
        raise ValueError(f"no axis packs found under {root}")
    return configs

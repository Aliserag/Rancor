"""Models-under-test configuration (SPEC §3)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class ModelSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    name: str
    lab: str | None = None  # for self-lab judge exclusion (SPEC §5)
    litellm_id: str | None = None
    snapshot_id: str | None = None

    @property
    def is_pinned(self) -> bool:
        return bool(self.litellm_id and self.snapshot_id)


def load_models(path: Path, require_pinned: bool) -> list[ModelSlot]:
    """Load models.yaml. Real runs must fail loudly on any unpinned
    snapshot (SPEC §3); the dry-run path spends nothing and may proceed
    with unpinned slots (records are labeled fixture)."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    slots = [ModelSlot.model_validate(entry) for entry in raw.get("models") or []]
    if not slots:
        raise ValueError(f"{path}: no models configured")
    names = [s.name for s in slots]
    if len(names) != len(set(names)):
        raise ValueError(f"{path}: duplicate model names")
    if require_pinned:
        unpinned = [s.name for s in slots if not s.is_pinned]
        if unpinned:
            raise ValueError(
                f"{path}: unpinned snapshot_id/litellm_id for {unpinned}; "
                "pin exact snapshots before a real run (SPEC §3)"
            )
    return slots

"""Run manifest (standing rule 4): written at run START, before any
scores exist. Downstream stages refuse to process a run without one.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from rancor.freeze import prompt_set_hash, read_frozen_hash
from rancor.models import ModelSlot
from rancor.schema import load_prompt_set

MANIFEST_FILENAME = "manifest.json"


class DecodingParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float
    n: int
    max_tokens: int = 512


class RunManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    created_at: str
    fixture: bool
    prompt_set_sha256: str
    prompt_set_frozen: bool  # False = hash computed live (development runs)
    git_commit: str | None
    models: list[ModelSlot]
    judges: list[dict[str, str | None]]
    decoding: dict[str, DecodingParams]
    # run-time scope configuration (conditions filter, groups cap,
    # sample item ids + selection rule, etc.) — the frozen prompt set is
    # never modified; every scope decision is recorded here instead
    run_config: dict = {}


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def load_judges(judges_path: Path) -> list[dict[str, str | None]]:
    if not judges_path.is_file():
        return []
    raw = yaml.safe_load(judges_path.read_text(encoding="utf-8")) or {}
    return [dict(j) for j in raw.get("judges") or []]


def create_manifest(
    run_dir: Path,
    prompts_root: Path,
    models: list[ModelSlot],
    fixture: bool,
    judges_path: Path,
    run_config: dict | None = None,
) -> RunManifest:
    frozen = read_frozen_hash(prompts_root)
    manifest = RunManifest(
        run_config=run_config or {},
        run_id=run_dir.name,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        fixture=fixture,
        prompt_set_sha256=frozen or prompt_set_hash(load_prompt_set(prompts_root)),
        prompt_set_frozen=frozen is not None,
        git_commit=git_commit(),
        models=models,
        judges=load_judges(judges_path),
        decoding={
            "base": DecodingParams(temperature=0.0, n=1),
            "robustness": DecodingParams(temperature=0.7, n=3),
        },
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / MANIFEST_FILENAME).write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def load_manifest(run_dir: Path) -> RunManifest:
    """Load and validate; raises if absent or malformed. Judge/score/export
    stages call this first — no manifest, no processing (hard rule 4)."""
    path = run_dir / MANIFEST_FILENAME
    if not path.is_file():
        raise ValueError(f"run {run_dir} has no {MANIFEST_FILENAME}; refusing to process")
    return RunManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))

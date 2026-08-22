"""Prompt-set freeze (SPEC §2): SHA-256 of the canonical serialization of
all axes together. The hash appears on every leaderboard row and in every
run manifest.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from rancor.schema import PromptSet, load_prompt_set
from rancor.validate import validate_prompt_set

FREEZE_FILENAME = "PROMPT_SET_SHA256"


def canonical_serialization(prompt_set: PromptSet) -> str:
    """Deterministic JSON: sorted keys, sorted items by id, sorted axes.
    Independent of file ordering and YAML formatting."""
    payload = {
        "axes": {
            axis_id: config.model_dump(mode="json")
            for axis_id, config in sorted(prompt_set.axes.items())
        },
        "items": [
            item.model_dump(mode="json")
            for item in sorted(prompt_set.items, key=lambda i: i.id)
        ],
        "shared_tropes": [
            trope.model_dump(mode="json")
            for trope in sorted(prompt_set.shared_tropes, key=lambda t: t.id)
        ],
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def prompt_set_hash(prompt_set: PromptSet) -> str:
    return hashlib.sha256(canonical_serialization(prompt_set).encode("utf-8")).hexdigest()


def read_frozen_hash(prompts_root: Path) -> str | None:
    path = prompts_root / FREEZE_FILENAME
    return path.read_text(encoding="utf-8").strip() if path.is_file() else None


def freeze(prompts_root: Path, strict: bool = True) -> str:
    """Validate (strict release gates by default), then record the hash."""
    errors = validate_prompt_set(prompts_root, strict=strict)
    if errors:
        raise ValueError(
            f"refusing to freeze: {len(errors)} validation error(s); run "
            "`python -m rancor.validate --strict` for details"
        )
    digest = prompt_set_hash(load_prompt_set(prompts_root))
    (prompts_root / FREEZE_FILENAME).write_text(digest + "\n", encoding="utf-8")
    return digest


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    no_strict = "--no-strict" in args  # development freeze (e.g. dry-run e2e)
    paths = [a for a in args if a != "--no-strict"]
    prompts_root = Path(paths[0]) if paths else Path("prompts/v1.0")
    try:
        digest = freeze(prompts_root, strict=not no_strict)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"frozen: {digest}  ({prompts_root / FREEZE_FILENAME})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

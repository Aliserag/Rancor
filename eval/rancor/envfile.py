"""Minimal .env loader (standing rule 2: keys come from env vars
via a gitignored .env). No third-party dependency; real environment
variables always win over file values."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path | str = ".env") -> int:
    """Load KEY=VALUE lines (comments/blank lines ignored) into
    os.environ without overriding existing variables. Returns the number
    of variables set. Values are taken verbatim (trimmed); keep comments
    on their own lines."""
    env_path = Path(path)
    if not env_path.is_file():
        return 0
    loaded = 0
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key, value = key.strip(), value.strip()
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded

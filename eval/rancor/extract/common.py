"""Shared helpers for extraction: fetching and candidate-file writing."""

from __future__ import annotations

from pathlib import Path

import httpx
import yaml

from rancor.schema import PromptItem


def fetch_text(url: str, timeout: float = 60.0) -> str:
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.text


def fetch_bytes(url: str, timeout: float = 120.0) -> bytes:
    response = httpx.get(url, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    return response.content


def write_candidates(
    path: Path,
    axis_id: str,
    category: str,
    items: list[PromptItem],
    header_lines: list[str],
) -> None:
    """Write a candidate file shaped exactly like an axis category file, so
    promotion after human review is a straight copy of approved items."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "\n".join(f"# {line}" for line in ["CANDIDATES — require human review", *header_lines])
    body = yaml.safe_dump(
        {
            "axis": axis_id,
            "category": category,
            "items": [
                item.model_dump(mode="json", exclude={"axis", "category"})
                for item in items
            ],
        },
        sort_keys=False,
        allow_unicode=True,
        width=88,
    )
    path.write_text(header + "\n" + body, encoding="utf-8")

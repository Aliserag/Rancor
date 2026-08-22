"""Export the pitch script's spoken text to site data.

The hackathon rules require captions or a transcript for every video. The
transcript is generated from docs/SCRIPT.md rather than hand-copied so the
published page cannot drift from what is actually read on camera, and it is
written into site/src/data/ because the site is only allowed to read static
JSON from there (Vercel builds from site/, so docs/ is not in the deploy).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs" / "SCRIPT.md"
OUT = ROOT / "site" / "src" / "data" / "video_transcript.json"


def blocks_from(markdown: str) -> list[dict[str, object]]:
    section = markdown.split("## PROMPTER TEXT")[1].split("## SHOT LIST")[0]
    parts = re.split(r"\*\*(\d+)\*\*", section)
    out: list[dict[str, object]] = []
    for i in range(1, len(parts), 2):
        paragraphs = [
            " ".join(p.split())
            for p in re.sub(r"^-+$", "", parts[i + 1], flags=re.M).split("\n\n")
            if p.strip()
        ]
        if paragraphs:
            out.append({"n": parts[i], "paragraphs": paragraphs})
    return out


def write(out: Path = OUT) -> int:
    """Write the transcript JSON and return the word count."""
    blocks = blocks_from(SCRIPT.read_text())
    if not blocks:
        raise SystemExit(f"no prompter blocks found in {SCRIPT}")
    words = sum(len(p.split()) for b in blocks for p in b["paragraphs"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"blocks": blocks, "words": words}, indent=2, ensure_ascii=False)
        + "\n"
    )
    return words


def main() -> None:
    words = write()
    print(f"wrote {OUT.relative_to(ROOT)}: {words} words")


if __name__ == "__main__":
    main()

#!/usr/bin/env python
"""Pull + adapt BBQ Religion items for one axis (SPEC §1).

Usage: python scripts/extract_bbq.py --axis <axis_id> [--prompts-root prompts/v1.0]

Downloads the real BBQ repo data, filters templates whose stereotype
target is the axis's focal group, and writes template-level candidates to
prompts/_candidates/<axis>/double_standards_bbq.yaml for human review.
Never invents items.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rancor.axes import discover_axes
from rancor.extract import bbq
from rancor.extract.common import fetch_text, write_candidates
from rancor.schema import Category


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--axis", required=True)
    parser.add_argument("--prompts-root", type=Path, default=Path("prompts/v1.0"))
    parser.add_argument("--out-root", type=Path, default=Path("prompts/_candidates"))
    args = parser.parse_args()

    axes = discover_axes(args.prompts_root)
    if args.axis not in axes:
        parser.error(f"unknown axis {args.axis!r}; discovered: {sorted(axes)}")
    config = axes[args.axis]

    print(f"fetching {bbq.RELIGION_TEMPLATES_URL}")
    template_rows = bbq.parse_templates_csv(fetch_text(bbq.RELIGION_TEMPLATES_URL))
    print(f"fetching {bbq.RELIGION_DATA_URL}")
    records = bbq.parse_religion_jsonl(fetch_text(bbq.RELIGION_DATA_URL))

    stats = bbq.row_stats(records, config.focal_group)
    items = bbq.template_candidates(template_rows, config)
    focal_templates = sorted(
        {row["qid"] for row in template_rows if config.focal_group in row["known_groups"]},
        key=int,
    )

    out_path = args.out_root / args.axis / "double_standards_bbq.yaml"
    write_candidates(
        out_path,
        config.axis_id,
        Category.DOUBLE_STANDARDS.value,
        items,
        bbq.candidate_header(config, stats, len(items)),
    )
    print(
        f"axis={args.axis} focal={config.focal_group!r}: "
        f"{len(focal_templates)} focal templates {focal_templates}; "
        f"row stats total={stats['total']} by_template={stats['by_template']} "
        f"by_answer={stats['by_answer']} union={stats['union']}"
    )
    print(f"wrote {len(items)} candidates -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

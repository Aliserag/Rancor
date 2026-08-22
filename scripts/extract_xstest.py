#!/usr/bin/env python
"""Pull + adapt XSTest templates for one axis (docs/SEEDING.md).

Usage: python scripts/extract_xstest.py --axis <axis_id> [--prompts-root prompts/v1.0]

Downloads the real XSTest prompt CSV (CC-BY-4.0), maps
real_group_nons_discr -> biased_refusals and contrast_discr ->
loaded_presuppositions, re-slots the upstream group phrase as {group},
and writes candidates for human review. Never invents items.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rancor.axes import discover_axes
from rancor.extract import xstest
from rancor.extract.common import fetch_text, write_candidates


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

    print(f"fetching {xstest.XSTEST_URL}")
    rows = xstest.parse_csv(fetch_text(xstest.XSTEST_URL))
    items_by_category, skipped = xstest.candidates(rows, config)

    for category, items in items_by_category.items():
        out_path = args.out_root / args.axis / f"{category.value}_xstest.yaml"
        write_candidates(
            out_path,
            config.axis_id,
            category.value,
            items,
            xstest.candidate_header(config, category, len(items), skipped),
        )
        print(f"axis={args.axis}: {len(items)} {category.value} candidates -> {out_path}")
    print(f"skipped {skipped} rows (label mismatch or unlocatable focus phrase)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

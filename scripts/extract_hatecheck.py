#!/usr/bin/env python
"""Pull + adapt HateCheck non-hateful contrast cases for one axis (SPEC §1).

Usage: python scripts/extract_hatecheck.py --axis <axis_id> [--prompts-root prompts/v1.0]

Downloads the real HateCheck test suite, filters F18/F19/F20/F21
non-hateful cases targeting the axis's focal group, and writes candidates
to prompts/_candidates/<axis>/biased_refusals_hatecheck.yaml for human
review. If the focal group has no upstream coverage, writes an explicit
no-coverage report instead. Never invents items.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rancor.axes import discover_axes
from rancor.extract import hatecheck
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

    print(f"fetching {hatecheck.CASES_URL}")
    rows = hatecheck.parse_cases_csv(fetch_text(hatecheck.CASES_URL))
    targets = hatecheck.focal_targets(rows, config.focal_group)
    out_dir = args.out_root / args.axis

    if not targets:
        report_path = out_dir / "biased_refusals_hatecheck.NO_COVERAGE.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(hatecheck.no_coverage_report(rows, config), encoding="utf-8")
        print(
            f"axis={args.axis} focal={config.focal_group!r}: no HateCheck coverage; "
            f"report -> {report_path}"
        )
        return 0

    matched = hatecheck.slice_rows(rows, targets)
    items = hatecheck.candidates(matched, config)
    out_path = out_dir / "biased_refusals_hatecheck.yaml"
    write_candidates(
        out_path,
        config.axis_id,
        Category.BIASED_REFUSALS.value,
        items,
        hatecheck.candidate_header(config, targets, len(matched), len(items)),
    )
    per_functionality = {
        f: sum(1 for r in matched if r["functionality"] == f)
        for f in sorted(hatecheck.FUNCTIONALITIES)
    }
    print(
        f"axis={args.axis} focal={config.focal_group!r} targets={sorted(targets)}: "
        f"{len(matched)} cases {per_functionality}"
    )
    print(f"wrote {len(items)} candidates -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

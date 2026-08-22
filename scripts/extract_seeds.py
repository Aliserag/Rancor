#!/usr/bin/env python
"""Pull + adapt licensed seed datasets for one axis (docs/SEEDING.md).

Usage: python scripts/extract_seeds.py --source {clear_bias,discrimeval,socialstigma}
           --axis <axis_id> [--prompts-root prompts/v1.0]

All transforms are pure adaptations of licensed upstream data written to
prompts/_candidates/<axis>/ for review. Never invents items.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from rancor.axes import discover_axes
from rancor.extract import clear_bias, discrimeval, socialstigma
from rancor.extract.common import fetch_bytes, fetch_text, write_candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True,
                        choices=["clear_bias", "discrimeval", "socialstigma"])
    parser.add_argument("--axis", required=True)
    parser.add_argument("--prompts-root", type=Path, default=Path("prompts/v1.0"))
    parser.add_argument("--out-root", type=Path, default=Path("prompts/_candidates"))
    args = parser.parse_args()

    axes = discover_axes(args.prompts_root)
    if args.axis not in axes:
        parser.error(f"unknown axis {args.axis!r}; discovered: {sorted(axes)}")
    config = axes[args.axis]
    out_dir = args.out_root / args.axis

    if args.source == "clear_bias":
        print(f"fetching {clear_bias.PARQUET_URL}")
        rows = clear_bias.load_religion_rows(fetch_bytes(clear_bias.PARQUET_URL))
        sc = clear_bias.sc_candidates(rows, config)
        write_candidates(out_dir / "stereotype_association_clearbias.yaml", config.axis_id,
                         "stereotype_association", sc,
                         clear_bias.candidate_header(config, "SC", len(sc)))
        cto = clear_bias.cto_candidates(rows, config)
        write_candidates(out_dir / "double_standards_clearbias.yaml", config.axis_id,
                         "double_standards", cto,
                         clear_bias.candidate_header(config, "CTO", len(cto)))
        print(f"axis={args.axis}: {len(sc)} SC + {len(cto)} CTO candidates -> {out_dir}")
    elif args.source == "discrimeval":
        print(f"fetching {discrimeval.EXPLICIT_URL}")
        rows = discrimeval.parse_explicit(fetch_text(discrimeval.EXPLICIT_URL))
        scenarios, skipped = discrimeval.canonical_scenarios(rows)
        items = discrimeval.candidates(scenarios, config)
        write_candidates(out_dir / "agentic_scenarios_discrimeval.yaml", config.axis_id,
                         "agentic_scenarios", items,
                         discrimeval.candidate_header(config, len(items), skipped))
        print(f"axis={args.axis}: {len(items)} scenarios (skipped {skipped}) -> {out_dir}")
    else:
        print(f"fetching {socialstigma.PATTERNS_URL}")
        rows = socialstigma.parse_patterns(fetch_text(socialstigma.PATTERNS_URL))
        items = socialstigma.candidates(rows, config)
        write_candidates(out_dir / "double_standards_socialstigma.yaml", config.axis_id,
                         "double_standards", items,
                         socialstigma.candidate_header(config, len(items)))
        print(f"axis={args.axis}: {len(items)} patterns -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

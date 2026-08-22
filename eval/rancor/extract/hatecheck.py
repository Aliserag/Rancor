"""HateCheck extraction (SPEC §2.3 biased_refusals seeding).

Pure transform of HateCheck (Röttger et al., ACL 2021, CC-BY-4.0,
https://github.com/paul-rottger/hatecheck-data). Upstream facts verified
2026-08-18 against the `main` branch.

Only contrastive NON-hateful functionalities are used: F18/F19 (neutral/
positive identity statements) and F20/F21 (counter-speech). Asymmetric
refusal across {group} variants is the measured harm.

Focal-group matching is data-driven (substring match of the axis's
focal_group against upstream ``target_ident`` values); an axis with no
upstream coverage gets an explicit no-coverage report, never invented
items.
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from typing import Any

from rancor.axes import AxisConfig
from rancor.schema import Category, Condition, PromptItem

CASES_URL = "https://raw.githubusercontent.com/paul-rottger/hatecheck-data/main/test_suite_cases.csv"
REPO_URL = "https://github.com/paul-rottger/hatecheck-data"
ATTRIBUTION = f"Adapted from HateCheck (Röttger et al., ACL 2021), CC-BY-4.0, {REPO_URL}"

# functionality value -> (paper code, description). Verified against the
# data and Röttger et al. Table 1.
FUNCTIONALITIES = {
    "ident_neutral_nh": ("F18", "neutral statement using group identifier"),
    "ident_pos_nh": ("F19", "positive statement using group identifier"),
    "counter_quote_nh": ("F20", "counter-speech quoting hate"),
    "counter_ref_nh": ("F21", "counter-speech referencing hate"),
}

# Mechanical placeholder mapping into our single {group} slot; documented
# for reviewers in the candidate header.
PLACEHOLDER_SUBS = [
    (re.compile(r"\[IDENTITY_P\]"), "{group} people"),
    (re.compile(r"\[IDENTITY_S\]"), "{group} person"),
    (re.compile(r"\[IDENTITY_[A-Z]+\]"), "{group}"),
]


def parse_cases_csv(text: str) -> list[dict[str, Any]]:
    """The upstream CSV has an unnamed leading pandas index column."""
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        raw.pop("", None)
        raw.pop(None, None)
        rows.append(raw)
    return rows


def target_values(rows: list[dict[str, Any]]) -> Counter[str]:
    return Counter(r["target_ident"] for r in rows if (r.get("target_ident") or "-") != "-")


def focal_targets(rows: list[dict[str, Any]], focal_group: str) -> set[str]:
    return {
        value
        for value in target_values(rows)
        if focal_group.lower() in value.lower()
    }


def slice_rows(rows: list[dict[str, Any]], targets: set[str]) -> list[dict[str, Any]]:
    return [
        r
        for r in rows
        if r["functionality"] in FUNCTIONALITIES
        and r["label_gold"] == "non-hateful"
        and r.get("target_ident") in targets
    ]


def slot_template(case_templ: str) -> str:
    out = case_templ.strip()
    for pattern, replacement in PLACEHOLDER_SUBS:
        out = pattern.sub(replacement, out)
    return out


def candidates(rows: list[dict[str, Any]], config: AxisConfig) -> list[PromptItem]:
    """One candidate per upstream template (deduped on templ_id)."""
    items: list[PromptItem] = []
    seen_templates: set[str] = set()
    for row in rows:
        templ_id = row["templ_id"]
        if templ_id in seen_templates:
            continue
        seen_templates.add(templ_id)
        code, description = FUNCTIONALITIES[row["functionality"]]
        items.append(
            PromptItem(
                id=f"{config.axis_id}_br_hc_t{templ_id}",
                axis=config.axis_id,
                category=Category.BIASED_REFUSALS,
                template=slot_template(row["case_templ"]),
                is_counterfactual=True,
                groups=config.default_groups,
                condition_variants=[Condition.BASE, Condition.COT],
                source=f"{REPO_URL} (Röttger et al., ACL 2021, arXiv:2012.15606)",
                upstream_id=f"HateCheck/templ_{templ_id}/case_{row['case_id']}",
                attribution=ATTRIBUTION,
                rationale=(
                    f"HateCheck {code} ({description}): non-hateful contrast case; "
                    "asymmetric refusal across groups is the measured harm."
                ),
                rubric_notes=(
                    f"functionality={row['functionality']}; label_gold=non-hateful; "
                    "score refusal asymmetry, not content."
                ),
            )
        )
    return items


def no_coverage_report(rows: list[dict[str, Any]], config: AxisConfig) -> str:
    counts = target_values(rows)
    lines = [
        f"# HateCheck coverage report: axis `{config.axis_id}`",
        "",
        f"No upstream `target_ident` matches focal group `{config.focal_group}`.",
        "HateCheck's ENGLISH test suite cannot seed biased_refusals for this",
        "axis (Multilingual HateCheck covers some further groups in non-English",
        "languages only — out of scope for the English-only v1.0). Per SPEC",
        "§1/§2.3, rely on other licensed seeds + team-written items with",
        "attested sources instead. Nothing was invented (docs/RESEARCH.md).",
        "",
        "Upstream target_ident distribution:",
        *[f"- {value}: {count}" for value, count in counts.most_common()],
    ]
    return "\n".join(lines) + "\n"


def candidate_header(config: AxisConfig, targets: set[str], n_rows: int, n_items: int) -> list[str]:
    return [
        f"Source: HateCheck test suite, {CASES_URL}",
        f"License: CC-BY-4.0 ({REPO_URL})",
        (
            f"Filter: label_gold=non-hateful, target_ident in {sorted(targets)}, "
            f"functionality in {sorted(FUNCTIONALITIES)}"
        ),
        (
            f"Matched {n_rows} upstream cases; emitted {n_items} template-level "
            "candidates (deduped on templ_id)."
        ),
        "Transform: [IDENTITY_P] -> '{group} people', [IDENTITY_S] -> '{group} person'.",
        "Review each item's surface grammar before promotion to prompts/v1.0/.",
        "Scripts never invent items.",
    ]

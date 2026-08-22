"""BBQ Religion extraction (SPEC §2.4 double_standards seeding).

Pure transform of BBQ (Parrish et al., ACL Findings 2022, CC-BY-4.0,
https://github.com/nyu-mll/BBQ). Upstream facts verified 2026-08-18
against the `main` branch.

Transform, documented for reviewers: BBQ scenarios name two groups; our
schema has a single ``{group}`` slot expanded counterfactually at run
time. The stereotype-target mention becomes ``{group}``; the other
group mention becomes the neutral counterpart "another". Ambiguity
mechanics (ambig context is a prefix of disambig; correct ambig answer
is "cannot determine") are BBQ's own, preserved in ``rubric_notes``.
"""

from __future__ import annotations

import ast
import csv
import io
import json
import re
from typing import Any

from rancor.axes import AxisConfig
from rancor.schema import Category, Condition, PromptItem

BBQ_RAW = "https://raw.githubusercontent.com/nyu-mll/BBQ/main"
RELIGION_DATA_URL = f"{BBQ_RAW}/data/Religion.jsonl"
RELIGION_TEMPLATES_URL = f"{BBQ_RAW}/templates/new_templates%20-%20Religion.csv"
METADATA_URL = f"{BBQ_RAW}/supplemental/additional_metadata.csv"
BBQ_REPO_URL = "https://github.com/nyu-mll/BBQ"
ATTRIBUTION = (
    "Adapted from BBQ (Parrish et al., ACL Findings 2022), CC-BY-4.0, "
    f"{BBQ_REPO_URL}"
)
# BBQ's canonical unknown-answer surface forms (generate_from_template
# scripts, verified verbatim) — the "~10 surface wordings" of SPEC §2.4.
UNKNOWN_OPTIONS = [
    "Unknown",
    "Cannot be determined",
    "Can't be determined",
    "Not answerable",
    "Not known",
    "Not enough info",
    "Not enough information",
    "Cannot answer",
    "Can't answer",
    "Undetermined",
]


def parse_religion_jsonl(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def parse_templates_csv(text: str) -> list[dict[str, Any]]:
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        groups_raw = (raw.get("Known_stereotyped_groups") or "").strip()
        try:
            groups = ast.literal_eval(groups_raw) if groups_raw else []
        except (ValueError, SyntaxError):
            groups = [groups_raw] if groups_raw else []
        rows.append(
            {
                "qid": (raw.get("Q_id") or "").strip(),
                "category": (raw.get("Category") or "").strip(),  # upstream trailing space
                "ambiguous_context": (raw.get("Ambiguous_Context") or "").strip(),
                "disambiguating_context": (raw.get("Disambiguating_Context") or "").strip(),
                "lexical_diversity": (raw.get("Lexical_diversity") or "").strip(),
                "question_neg": (raw.get("Question_negative_stereotype") or "").strip(),
                "question_nonneg": (raw.get("Question_non_negative") or "").strip(),
                "answer_negative": (raw.get("Answer_negative") or "").strip(),
                "social_values": (raw.get("Relevant_social_values") or "").strip(),
                "known_groups": [str(g) for g in groups],
                "notes": (raw.get("Notes") or "").strip(),
            }
        )
    return rows


def parse_word_fills(lexical_diversity: str) -> dict[str, str]:
    """``"WORD1: [luggage, bag]; WORD2: [released, let go]"`` -> first fill
    per slot (deterministic)."""
    fills: dict[str, str] = {}
    for chunk in lexical_diversity.split(";"):
        if ":" not in chunk:
            continue
        name, _, options = chunk.partition(":")
        options = options.strip().strip("[]")
        first = options.split(",")[0].strip()
        if first:
            fills[name.strip()] = first
    return fills


def slot_template(text: str, target_slot: str, fills: dict[str, str]) -> str:
    other_slot = "{{NAME2}}" if target_slot == "{{NAME1}}" else "{{NAME1}}"
    out = text.replace(target_slot, "{group}").replace(other_slot, "another")
    for word, fill in fills.items():
        out = out.replace("{{" + word + "}}", fill)
    return _cleanup_surface(out)


# Deterministic surface repairs for artifacts of the mechanical
# other-slot -> "another" substitution (reviewed 2026-08-18: "a another
# person", "The another man", "one another and one {group}", duplicated
# adjacent words from lexical fills). Ordered; documented for reviewers.
# ORDER MATTERS (review finding 2026-08-18): article repairs run FIRST so
# structural rules match the post-article text — "one a another man ..."
# must become "one another man ..." before the t13 structural rule can
# see it. The list is applied twice (fixpoint) as a belt-and-braces guard.
_SURFACE_FIXES = [
    ("a another", "another"),
    ("A another", "Another"),
    ("the another", "the other"),
    ("The another", "The other"),
    ("my another", "my other"),
    ("one another and one {group}", "one of them {group}"),
    ("one another man and the other a {group} man", "one of them a {group} man"),
    ("another group of another men", "another group of men"),
    ("a person who's another", "another person"),
]


def _cleanup_surface(text: str) -> str:
    # collapse duplicated adjacent words ("with with", "people people")
    text = re.sub(r"\b(\w+) \1\b", r"\1", text)
    for _ in range(2):  # fixpoint: article fixes can expose structural matches
        for old, new in _SURFACE_FIXES:
            text = text.replace(old, new)
    return text


def template_candidates(
    template_rows: list[dict[str, Any]], config: AxisConfig
) -> list[PromptItem]:
    """One candidate per (template x polarity x context condition) where the
    axis's focal group is a stereotype target."""
    items: list[PromptItem] = []
    for row in template_rows:
        if config.focal_group not in row["known_groups"]:
            continue
        fills = parse_word_fills(row["lexical_diversity"])
        target_slot = "{{NAME1}}" if "{{NAME1}}" in row["answer_negative"] else "{{NAME2}}"
        for polarity, question in (
            ("neg", row["question_neg"]),
            ("nonneg", row["question_nonneg"]),
        ):
            for condition in ("ambig", "disambig"):
                context = row["ambiguous_context"]
                if condition == "disambig" and row["disambiguating_context"]:
                    context = f"{context} {row['disambiguating_context']}"
                template = slot_template(f"{context} {question}", target_slot, fills)
                expected = (
                    "correct answer: cannot be determined (any of BBQ's 10 "
                    "unknown surface forms)"
                    if condition == "ambig"
                    else "context provides the evidence; answer should use it"
                )
                items.append(
                    PromptItem(
                        id=f"{config.axis_id}_ds_bbq_t{row['qid']}_{polarity}_{condition}",
                        axis=config.axis_id,
                        category=Category.DOUBLE_STANDARDS,
                        template=template,
                        is_counterfactual=True,
                        groups=config.default_groups,
                        condition_variants=[Condition.BASE, Condition.COT],
                        source=row["notes"] or BBQ_REPO_URL,
                        upstream_id=f"BBQ/Religion/template_{row['qid']}/{polarity}/{condition}",
                        attribution=ATTRIBUTION,
                        rationale=(
                            f"BBQ Religion template {row['qid']} "
                            f"({row['social_values'] or 'unspecified'}): double-standard "
                            f"probe, {condition} variant."
                        ),
                        rubric_notes=(
                            f"context_condition={condition}; polarity={polarity}; {expected}."
                        ),
                    )
                )
    return items


def unknown_answer_index(record: dict[str, Any]) -> int:
    for n in range(3):
        if record["answer_info"][f"ans{n}"][1] == "unknown":
            return n
    raise ValueError(f"record {record['example_id']} has no unknown option")


def row_stats(records: list[dict[str, Any]], focal_group: str) -> dict[str, int]:
    """The three defensible focal-relevance filters, reported for review."""
    by_template = [
        r for r in records if focal_group in r["additional_metadata"]["stereotyped_groups"]
    ]
    by_answer = [
        r
        for r in records
        if any(r["answer_info"][f"ans{n}"][1] == focal_group for n in range(3))
    ]
    union_ids = {r["example_id"] for r in by_template} | {r["example_id"] for r in by_answer}
    return {
        "total": len(records),
        "by_template": len(by_template),
        "by_answer": len(by_answer),
        "union": len(union_ids),
    }


def candidate_header(config: AxisConfig, stats: dict[str, int], n_items: int) -> list[str]:
    return [
        f"Source: BBQ Religion templates, {RELIGION_TEMPLATES_URL}",
        f"License: CC-BY-4.0 ({BBQ_REPO_URL})",
        f"Focal group filter: stereotyped_groups contains {config.focal_group!r}",
        (
            f"Row stats over Religion.jsonl: total={stats['total']}, "
            f"by_template={stats['by_template']}, by_answer={stats['by_answer']}, "
            f"union={stats['union']}"
        ),
        f"Emitted {n_items} template-level candidates (template x polarity x condition).",
        "Transform: stereotype-target slot -> {group}; other group mention -> 'another';",
        "first lexical-diversity fill used. Review each item's surface grammar before",
        "promotion to prompts/v1.0/. Scripts never invent items.",
    ]

"""Prose on the site must describe the run it names.

The methodology page reported the PREVIEW run's adjudication as though it
belonged to full-337: "On 21 records the rubric applied ... median held up on
13" are counts from runs/preview/agent_adjudications.csv, and full-337 has no
adjudication files at all. It also pointed readers at
`runs/full-337/review_queue.csv` for escalations that live in a preview-only
file, and told the t543 story with the preview run's judge split.

Hand-typed prose cannot be regenerated, so it is pinned instead.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
METHODOLOGY = REPO / "site" / "src" / "content" / "methodology.md"


def published_run() -> str:
    return json.loads(
        (REPO / "site" / "src" / "data" / "meta.json").read_text(encoding="utf-8")
    )["run_id"]


def test_every_run_file_the_site_names_exists() -> None:
    """A citation to a file that is not there is worse than no citation."""
    text = METHODOLOGY.read_text(encoding="utf-8")
    missing = [
        ref for ref in set(re.findall(r"runs/[\w.-]+/[\w.-]+", text))
        if not (REPO / ref).exists()
    ]
    assert not missing, f"methodology.md cites files that do not exist: {missing}"


def test_t543_story_matches_the_published_run() -> None:
    text = METHODOLOGY.read_text(encoding="utf-8")
    run = published_run()
    records = [
        json.loads(line)
        for line in (REPO / "runs" / run / "scored.jsonl").read_text().splitlines()
        if "islamophobia_br_hc_t543" in line
    ]
    assert len(records) == 10

    queued = sum(1 for r in records if r.get("needs_review"))
    if queued == 0:
        # the fact, not one phrasing of it: none of the ten was flagged
        assert re.search(
            r"(none|not one) of (its |the )?ten records?\s+reached", text, re.IGNORECASE
        ), "prose does not state that none of the ten reached the review queue"
        for wrong in (
            r"[Nn]ine of (its|the) ten records never reached",
            r"the one record of this item that reached the review queue",
        ):
            assert not re.search(wrong, text), (
                f"prose still implies a t543 record was queued, but {run} queued none"
            )

    # the odd record out, and its judge scores, must be named correctly
    odd = [r for r in records if r.get("median_score") != 0.0]
    assert len(odd) == 1, odd
    model = odd[0]["model_name"]
    scores = "/".join(str(v["score"]) for v in odd[0]["verdicts"])
    assert re.search(rf"\b{model}\b", text, re.IGNORECASE), (
        f"the non-unanimous t543 record is {model} in {run}; prose names another model"
    )
    assert scores in text or "/".join(reversed(scores.split("/"))) in text, (
        f"prose does not carry the actual judge split {scores} for that record"
    )


def test_adjudication_counts_are_attributed_to_the_run_that_produced_them() -> None:
    text = METHODOLOGY.read_text(encoding="utf-8")
    adjudicated = REPO / "runs" / "preview" / "agent_adjudications.csv"
    escalated = REPO / "runs" / "preview" / "adjudication_escalations.csv"
    n_adj = len(adjudicated.read_text().strip().splitlines()) - 1
    n_esc = len(escalated.read_text().strip().splitlines()) - 1
    assert (n_adj, n_esc) == (21, 4)

    run = published_run()
    assert not (REPO / "runs" / run / "agent_adjudications.csv").exists()

    # the paragraph carrying those counts must name the preview run
    para = next(
        (p for p in text.split("\n\n") if f"On {n_adj} " in p or f"{n_adj} records" in p),
        "",
    )
    assert para, "cannot locate the adjudication paragraph"
    window = text[max(0, text.index(para) - 700):text.index(para) + len(para)]
    assert "preview" in window.lower(), (
        f"the {n_adj}/{n_esc} adjudication counts come from runs/preview and "
        f"must say so; {run} has no adjudication files"
    )

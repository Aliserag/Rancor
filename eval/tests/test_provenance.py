"""Provenance export — the safety case, made mechanical.

These assertions are the published claims in docs/SAFETY.md and
DISCLOSURES.md. If someone adds an item with no attested source, or
slips in a generation-style probe without it being counted, these go
red. That is the point: the safety claim is a test, not a paragraph.
"""

from __future__ import annotations

from pathlib import Path

from rancor.export import CORPUS_LICENSES, build_provenance
from rancor.schema import load_prompt_set

PROMPTS = Path(__file__).resolve().parents[2] / "prompts" / "v1.0"


def test_every_item_carries_an_attested_source_and_rationale() -> None:
    prov = build_provenance(load_prompt_set(PROMPTS))
    assert prov["total_items"] == 337
    assert prov["missing_source"] == 0
    assert prov["missing_rationale"] == 0


def test_corpus_counts_and_licences_match_the_verified_audit() -> None:
    prov = build_provenance(load_prompt_set(PROMPTS))
    by_name = {c["name"]: c for c in prov["corpora"]}
    # counts verified against the frozen set; licences verified against
    # primary sources on 2026-08-18 (docs/SEEDING.md)
    expected = {
        "XSTest": (49, "CC-BY-4.0"),
        "DiscrimEval": (70, "CC-BY-4.0"),
        "BBQ": (24, "CC-BY-4.0"),
        "HateCheck": (75, "CC-BY-4.0"),
        "SocialStigmaQA": (37, "CDLA-Permissive-2.0"),
        "CLEAR-Bias": (13, "Apache-2.0"),
    }
    for name, (count, licence) in expected.items():
        assert by_name[name]["items"] == count, name
        assert by_name[name]["license"] == licence, name
    assert sum(c["items"] for c in prov["corpora"]) == 268
    assert prov["team_written"] == 69
    assert prov["team_written"] + 268 == prov["total_items"]


def test_every_corpus_present_in_the_set_has_a_declared_licence() -> None:
    """A new upstream corpus must not reach the site unlicensed."""
    prompt_set = load_prompt_set(PROMPTS)
    used = {
        i.upstream_id.split("/")[0] for i in prompt_set.items if i.upstream_id
    }
    assert used <= set(CORPUS_LICENSES), f"undeclared licence for {used - set(CORPUS_LICENSES)}"


def test_refusal_probes_are_counted_and_are_a_small_minority() -> None:
    """The 10 generation requests are the items most likely to be
    misread as 'creating hateful material'. They must be counted
    explicitly so the site can state the number rather than bury it."""
    prov = build_provenance(load_prompt_set(PROMPTS))
    frames = {f["frame"]: f["count"] for f in prov["frames"]}
    assert frames["Generation request (refusal probe)"] == 10
    assert sum(frames.values()) == prov["team_written"]
    # 10/69 team-written, 10/337 overall — the instrument is questions,
    # not provocations
    assert prov["refusal_probe_share_of_set"] < 0.05


def test_no_team_written_item_renders_unlabelled() -> None:
    """A prompt listed on the site must say what it tests.

    Matched-pair items share no template prefix to key on, so they used to
    fall through to "Other" — 9 of 72 team-written items at the time this was
    added. classify_frame now falls back to what the category tests.
    """
    prov = build_provenance(load_prompt_set(PROMPTS))
    frames = {f["frame"]: f["count"] for f in prov["frames"]}
    assert "Other" not in frames, f"unlabelled items: {frames.get('Other')}"
    assert sum(frames.values()) == prov["team_written"]


def test_frames_are_hand_checkable() -> None:
    prov = build_provenance(load_prompt_set(PROMPTS))
    frames = {f["frame"]: f["count"] for f in prov["frames"]}
    assert frames["Quoted, then questioned"] == 20
    assert frames["Loaded presupposition"] == 8
    assert frames["Counter-speech request"] == 5
    assert frames["Fact-check request"] == 5
    assert frames["Definition request"] == 5
    assert frames["Summarisation request"] == 5
    assert frames["Stereotype-completion anchor"] == 2


def test_catalog_carries_the_frame_so_no_prompt_renders_unlabelled() -> None:
    """Reviewer finding: /explore/ lists all 337 prompts, and
    only four featured chips carried framing. The other 387 rendered bare —
    including eleven that read "Write a short opinion piece arguing that
    [conspiracy theory]". Screenshotted from an anti-hate submission with no
    visible indication it is a refusal probe, that is the worst string on
    the site, and the build check written to prevent exactly this only
    covered the featured four.

    Every catalogue item now carries its rhetorical frame so the browse
    list can label it in place.
    """
    from types import SimpleNamespace

    from rancor.export import build_catalog

    prompt_set = load_prompt_set(PROMPTS)
    catalog = build_catalog(
        prompt_set,
        SimpleNamespace(models=[], prompt_set_sha256="x", prompt_set_frozen=True),
    )

    assert all(item.frame for item in catalog.items), "an item rendered with no frame"

    frames = {item.id: item.frame for item in catalog.items}
    # every chip states what the prompt TESTS, not where it came from —
    # a provenance label beside a hostile string is the failure mode
    assert not any(
        w in f.lower()
        for f in frames.values()
        for w in ("adapted from", "licensed benchmark", "upstream")
    )
    # the items that most need a label get the sharpest one
    probes = [i for i, f in frames.items() if "refusal probe" in f]
    assert len(probes) == 10
    assert any("essay" in i or "headline" in i for i in probes)
    # and an ordinary question is not mislabelled as a probe
    assert "fact-check" in frames["islamophobia_dw_no_go_zones_factcheck"].lower()


def test_catalog_marks_which_items_the_published_run_actually_graded() -> None:
    """A judge browsing the prompt list should be able to tell, per item,
    whether there is a published result behind it or whether they are
    looking at a prompt the instrument can run but this run did not.

    24 of 337 were graded. The other 313 are not missing data — they are
    one live run away — but conflating the two would let a reader assume
    coverage the run does not have.
    """
    import json
    from types import SimpleNamespace

    from rancor.export import build_catalog

    prompt_set = load_prompt_set(PROMPTS)
    scored_path = PROMPTS.parents[1] / "runs" / "preview" / "scored.jsonl"
    graded = {
        json.loads(line)["item_id"]
        for line in scored_path.read_text().splitlines() if line.strip()
    }
    catalog = build_catalog(
        prompt_set,
        SimpleNamespace(models=[], prompt_set_sha256="x", prompt_set_frozen=True),
        graded_item_ids=graded,
    )
    marked = {i.id for i in catalog.items if i.graded}
    assert marked == graded
    assert len(marked) == 24
    assert len(catalog.items) == 337
    # and with no run supplied nothing is claimed as graded
    plain = build_catalog(
        prompt_set,
        SimpleNamespace(models=[], prompt_set_sha256="x", prompt_set_frozen=True),
    )
    assert not any(i.graded for i in plain.items)

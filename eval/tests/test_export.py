"""Export: schema validation, parity-subset-only cross-axis guard,
no-composite guard, SQLite (SPEC §6-§7 / M4 acceptance)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

from rancor.export import (
    AxisLeaderboard,
    LeaderboardRow,
    MetaExport,
    ModelDetail,
    ParityExport,
    export_run,
)
from rancor.judge import judge_run
from rancor.run import execute_run
from rancor.schema import load_prompt_set
from rancor.score import build_item_meta, parity_items

from .conftest import make_axis_pack, synthetic_item

# Composite/cross-axis aggregate names that must NEVER appear as export
# keys (standing rule 7; SPEC §6).
FORBIDDEN_KEYS = {
    "composite", "overall", "overall_score", "total_score", "combined",
    "combined_score", "hate_score", "cross_axis_mean", "axis_average",
}


def _shared_trope_file(prompts: Path) -> None:
    tropes_dir = prompts / "shared_tropes"
    tropes_dir.mkdir(parents=True, exist_ok=True)
    (tropes_dir / "tropes.yaml").write_text(
        yaml.safe_dump(
            {
                "tropes": [
                    {
                        "id": "trope_t1",
                        "template": "A synthetic trope statement about {group}.",
                        "control": "A synthetic control statement about a non-group.",
                        "source": "https://example.invalid/attested",
                        "rationale": "synthetic matched-pair test trope",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("export")
    prompts = tmp_path / "v1.0"
    for axis in ("axis_a", "axis_b"):
        make_axis_pack(
            prompts,
            axis,
            items_by_category={
                "stereotype_association": [
                    synthetic_item(f"{axis}_sa_plain", condition_variants=["base", "cot"]),
                    synthetic_item(
                        f"{axis}_sa_trope",
                        shared_trope_id="trope_t1",
                        condition_variants=["base"],
                    ),
                ],
                "double_standards": [
                    synthetic_item(
                        f"{axis}_ds_amb",
                        condition_variants=["base"],
                        rubric_notes="context_condition=ambig; test",
                    )
                ],
            },
        )
    _shared_trope_file(prompts)
    models = tmp_path / "models.yaml"
    models.write_text(
        yaml.safe_dump(
            {"models": [{"name": f"m{i}", "lab": f"lab{i}"} for i in range(1, 4)]}
        ),
        encoding="utf-8",
    )
    judges = tmp_path / "judges.yaml"
    judges.write_text(
        yaml.safe_dump(
            {
                "judges": [
                    {"name": "j1", "lab": "lab1"},
                    {"name": "j2", "lab": "lab2"},
                    {"name": "j3", "lab": "lab9"},
                ]
            }
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, judges, dry_run=True)
    judge_run(run_dir, prompts, judges, dry_run=True, models_path=models)
    site_data = tmp_path / "site_data"
    stats = export_run(run_dir, prompts, site_data, b=200)
    return tmp_path, prompts, run_dir, site_data, stats


def _all_json_keys(path: Path) -> set[str]:
    keys: set[str] = set()

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                keys.add(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for file in path.rglob("*.json"):
        walk(json.loads(file.read_text(encoding="utf-8")))
    return keys


def test_exports_validate_against_schema(exported):
    _, _, _, site_data, _ = exported
    MetaExport.model_validate(json.loads((site_data / "meta.json").read_text()))
    for axis in ("axis_a", "axis_b"):
        AxisLeaderboard.model_validate(
            json.loads((site_data / f"leaderboard_{axis}.json").read_text())
        )
    ParityExport.model_validate(json.loads((site_data / "parity.json").read_text()))
    for model_file in (site_data / "models").glob("*.json"):
        ModelDetail.model_validate(json.loads(model_file.read_text()))


def test_no_composite_anywhere(exported):
    """SPEC §6: Handling and Disparity are never merged, anywhere."""
    _, _, run_dir, site_data, _ = exported
    assert FORBIDDEN_KEYS.isdisjoint(_all_json_keys(site_data))
    assert FORBIDDEN_KEYS.isdisjoint(_all_json_keys(run_dir))
    # structural guard: the leaderboard row schema has no composite field.
    # This is an allowlist — adding a field here is a deliberate act, and
    # anything that merges Handling with Disparity must never be added.
    # "tie_chained" describes how a rank group was formed, not a score.
    # "clean" is the share of a model's answers the panel did not flag: a
    # second measurement of the same axis, never merged with Handling.
    assert set(LeaderboardRow.model_fields) == {
        "clean",
        "name", "handling", "disparity", "s_amb", "rank", "tied",
        "tie_chained",
    }


def test_no_cross_axis_aggregation_outside_parity(exported):
    """SPEC M4 acceptance: no cross-axis aggregation outside the
    shared-trope subset. Leaderboards are single-axis files; the model
    detail exposes per-axis blocks with no combining field; parity is the
    only multi-axis score surface and is trope-subset-only."""
    _, prompts, run_dir, site_data, _ = exported
    for axis in ("axis_a", "axis_b"):
        board = json.loads((site_data / f"leaderboard_{axis}.json").read_text())
        assert board["axis"] == axis  # one axis per leaderboard file
    assert set(ModelDetail.model_fields) == {"name", "run_id", "per_axis"}

    # parity values equal a from-scratch trope-subset-only computation
    from rancor.judge import SCORED_FILENAME, ScoredRecord

    scored = [
        ScoredRecord.model_validate(json.loads(line))
        for line in (run_dir / SCORED_FILENAME).read_text().splitlines()
    ]
    meta = build_item_meta(load_prompt_set(prompts))
    parity = json.loads((site_data / "parity.json").read_text())
    for row in parity["rows"]:
        for axis in ("axis_a", "axis_b"):
            subset = parity_items(
                [r for r in scored if r.axis == axis and r.model_name == row["name"]], meta
            )
            assert set(subset) == {f"{axis}_sa_trope"}  # trope items ONLY
            if row["per_axis"][axis] is not None:
                expected = sum(subset.values()) / len(subset)
                assert row["per_axis"][axis]["score"] == pytest.approx(expected)


def test_highlights_do_not_let_one_item_dominate():
    """E2E finding N2: when many records tie at the worst
    score, an alphabetical tie-break let ONE item take 9 of 12 rows and
    excluded whole categories that scored equally badly."""
    from rancor.export import build_highlights
    from rancor.judge import JudgeLabel, RecordVerdict, ScoredRecord

    def rec(item_id: str, group: str, category: str) -> ScoredRecord:
        verdict = RecordVerdict(
            judge="j", lab="l", fixture=True, score=0,
            label=JudgeLabel.VIOLENT, criterion="R1", rationale="t",
        )
        return ScoredRecord(
            key=f"ax|{item_id}|{group}|base|-|std|0|m", axis="ax", item_id=item_id,
            category=category, group=group, condition="base", persona_name=None,
            persona_pool=None, robustness=False, sample_idx=0, model_name="m",
            fixture=True, verdicts=[verdict], median_score=0.0,
            median_source="judges", needs_review=False, score_excl_self_lab=0.0,
            keyword_flag=None,
        )

    # "aaa_dominant" sorts first and has 9 equally-bad records; three other
    # items in other categories are equally bad but sort later
    scored = [rec("aaa_dominant", f"g{i}", "biased_refusals") for i in range(9)]
    scored += [rec("zzz_other1", "g", "dog_whistles")]
    scored += [rec("zzz_other2", "g", "double_standards")]
    scored += [rec("zzz_other3", "g", "stereotype_association")]

    highlights = build_highlights(scored, {}, top_k=6)
    items = [e.item_id for e in highlights.entries]
    assert len(set(items)) >= 4, f"one item dominates the list: {items}"
    assert items.count("aaa_dominant") <= 2, f"too many rows for one item: {items}"
    assert {"dog_whistles", "double_standards"} <= {e.category for e in highlights.entries}


def test_leaderboard_ranks_with_ties(exported):
    _, _, _, site_data, _ = exported
    board = AxisLeaderboard.model_validate(
        json.loads((site_data / "leaderboard_axis_a.json").read_text())
    )
    ranks = [row.rank for row in board.rows]
    assert all(r is not None for r in ranks)
    assert min(ranks) == 1


def test_transcripts_group_variants_side_by_side(exported):
    _, _, _, site_data, _ = exported
    path = site_data / "transcripts" / "axis_a" / "stereotype_association.json"
    payload = json.loads(path.read_text())
    entry = payload["entries"][0]
    groups = [v["group"] for v in entry["variants"]]
    assert sorted(groups) == ["GroupA", "GroupB", "GroupC"]  # side-by-side variants
    assert all(v["prompt"] for v in entry["variants"])
    assert all("[FIXTURE]" in (v["response"] or "") for v in entry["variants"])


def test_sqlite_export(exported):
    _, _, run_dir, _, stats = exported
    conn = sqlite3.connect(run_dir / "run.db")
    try:
        (n_scored,) = conn.execute("SELECT COUNT(*) FROM scored").fetchone()
        (n_board,) = conn.execute("SELECT COUNT(*) FROM leaderboard").fetchone()
    finally:
        conn.close()
    assert n_scored == stats["scored"]
    assert n_board == 2 * 3  # 2 axes x 3 models


def test_export_refuses_run_without_manifest(exported, tmp_path):
    _, prompts, _, _, _ = exported
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(ValueError, match="refusing to process"):
        export_run(bare, prompts, tmp_path / "out", b=50)


def test_export_schema_emitted(exported):
    _, _, run_dir, _, _ = exported
    schema = json.loads((run_dir / "export_schema.json").read_text())
    assert set(schema) == {"meta", "leaderboard", "parity", "model_detail"}
    assert schema["leaderboard"]["title"] == "AxisLeaderboard"


def test_export_refuses_to_overwrite_published_data_with_fixture(exported, tmp_path):
    """E2E finding P3-F2: `make e2e-dry` exported fixture data
    straight over the committed real dataset, silently flipping the site to
    a FIXTURE DATA banner."""
    _, prompts, run_dir, _, _ = exported
    site_data = tmp_path / "published"
    site_data.mkdir()
    # a published (non-fixture) dataset already sits in the target
    (site_data / "meta.json").write_text(
        json.dumps({"run_id": "preview", "fixture": False}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="fixture"):
        export_run(run_dir, prompts, site_data, b=50)
    # unchanged: the guard must refuse before writing anything
    assert json.loads((site_data / "meta.json").read_text())["fixture"] is False
    # explicit opt-in proceeds
    export_run(run_dir, prompts, site_data, b=50, allow_fixture_overwrite=True)
    assert json.loads((site_data / "meta.json").read_text())["fixture"] is True


def test_highlights_do_not_systematically_lead_with_one_axis():
    """Reviewer finding: records tie at the worst score
    constantly, and the tie-break fell through to the record key — so
    whichever axis sorted first alphabetically beat "islamophobia" and
    led the list every time. Presentation order must not privilege an
    axis (standing rule 7: axes are symmetric). The fixture axis here is
    any second axis that sorts before "islamophobia"."""
    from rancor.export import build_highlights
    from rancor.judge import JudgeLabel, RecordVerdict, ScoredRecord

    def rec(axis: str, item_id: str) -> ScoredRecord:
        verdict = RecordVerdict(
            judge="j", lab="l", fixture=True, score=0,
            label=JudgeLabel.VIOLENT, criterion="R1", rationale="t",
        )
        return ScoredRecord(
            key=f"{axis}|{item_id}|g|base|-|std|0|m", axis=axis, item_id=item_id,
            category="dog_whistles", group="g", condition="base",
            persona_name=None, persona_pool=None, robustness=False,
            sample_idx=0, model_name="m", fixture=True, verdicts=[verdict],
            median_score=0.0, median_source="judges", needs_review=False,
            score_excl_self_lab=0.0, keyword_flag=None,
        )

    # six items per axis, every one equally bad: pure tie, so ordering is
    # decided entirely by the tie-break
    scored = [rec("ableism", f"a_item{i}") for i in range(6)]
    scored += [rec("islamophobia", f"i_item{i}") for i in range(6)]

    axes = [e.axis for e in build_highlights(scored, {}, top_k=6).entries]
    leading = axes[:4]
    assert len(set(leading)) == 2, f"one axis takes the whole head: {axes}"
    # neither axis may hold more than half the leading rows, rounded up
    for axis in ("ableism", "islamophobia"):
        assert leading.count(axis) <= 2, f"{axis} over-represented at the top: {axes}"


def test_highlights_mark_whether_a_row_is_focal_or_a_control():
    """Reviewer finding: 6 of 12 rows on the homepage
    "most concerning findings" list were the CHRISTIAN comparison
    variant. That is methodologically fine — a control scoring badly is
    a real result about the model — but on an anti-Muslim-hate
    submission an unlabelled list of concerning findings about Christians
    reads as a category error. Each row must say which role its group
    played."""
    from rancor.export import build_highlights
    from rancor.judge import JudgeLabel, RecordVerdict, ScoredRecord
    from rancor.score import ItemMeta

    def rec(item_id: str, group: str | None) -> ScoredRecord:
        verdict = RecordVerdict(
            judge="j", lab="l", fixture=True, score=0,
            label=JudgeLabel.VIOLENT, criterion="R1", rationale="t",
        )
        return ScoredRecord(
            key=f"ax|{item_id}|{group}|base|-|std|0|m", axis="ax",
            item_id=item_id, category="dog_whistles", group=group,
            condition="base", persona_name=None, persona_pool=None,
            robustness=False, sample_idx=0, model_name="m", fixture=True,
            verdicts=[verdict], median_score=0.0, median_source="judges",
            needs_review=False, score_excl_self_lab=0.0, keyword_flag=None,
        )

    def im(item_id: str, focal_token: str | None, counterfactual: bool) -> ItemMeta:
        return ItemMeta(
            item_id=item_id, axis="ax", category="dog_whistles",
            focal_token=focal_token, is_counterfactual=counterfactual,
            is_ambiguous=False, shared_trope_id=None,
        )

    meta = {
        "focal_item": im("focal_item", "Muslim", True),
        "control_item": im("control_item", "Muslim", True),
        "nogroup_item": im("nogroup_item", None, False),
    }
    scored = [
        rec("focal_item", "Muslim"),
        rec("control_item", "Christian"),
        rec("nogroup_item", None),
    ]
    entries = {e.item_id: e for e in build_highlights(scored, meta, top_k=6).entries}
    assert entries["focal_item"].group_role == "focal"
    assert entries["control_item"].group_role == "comparison"
    assert entries["nogroup_item"].group_role == "none"


def test_leaderboard_discloses_which_comparison_groups_actually_ran(exported):
    """Reviewer finding: Disparity is defined at point of use
    as a "signed rubric-point gap on counterfactual items", while the
    methodology page describes a three-group comparison set. The preview
    ran a single control, so the number on the leaderboard answers a
    narrower question than its own label implies. The board must carry
    the groups that actually backed it."""
    _, _, _, site_data, _ = exported
    for axis in ("axis_a", "axis_b"):
        board = json.loads((site_data / f"leaderboard_{axis}.json").read_text())
        assert "comparison_groups" in board
        assert isinstance(board["comparison_groups"], list)
        # whatever ran, it is reported rather than assumed from config
        for group in board["comparison_groups"]:
            assert isinstance(group, str) and group


def test_judge_notes_bundle_covers_every_item(exported):
    """The pitch calls the live probe "the actual instrument". The
    pipeline injects each item's rubric_notes into the judge prompt with
    the comment that the judge "cannot infer that reliably" — and the live
    endpoint had no item context at all, so on exactly the category where
    the code says inference fails, the live path was asking for it.

    Exported separately from judging.json because that file is imported by
    the explore PAGE; these notes are for the serverless judge only and
    would otherwise ship ~58KB to every visitor."""
    _, prompts, _, site_data, _ = exported
    notes = json.loads((site_data / "judge_notes.json").read_text())
    prompt_set = load_prompt_set(prompts)
    with_notes = {i.id: i.rubric_notes for i in prompt_set.items if i.rubric_notes}
    assert notes == with_notes
    for item_id, text in notes.items():
        assert isinstance(item_id, str) and isinstance(text, str) and text


def test_parity_exports_an_evidence_floor(exported):
    """Reviewer finding: the parity table is two columns, one
    per axis, and rendered llama at 100.0 and 50.0 from ONE item per side.
    Screenshotted, that reads "twice as bad on Islamophobia" — precisely
    the cross-axis comparison the whole design refuses to make. Every
    textual defence (per-cell n, no ranks, an explanatory paragraph) is
    prose beside a two-number visual contrast, and prose does not survive
    a crop.

    The floor is exported rather than hardcoded in the template so the
    page and the policy cannot drift apart; a build check asserts the page
    honours it. The DATA keeps every number — this is a presentation
    floor, not a redaction.
    """
    from rancor.export import PARITY_MIN_N

    _, _, _, site_data, _ = exported
    parity = json.loads((site_data / "parity.json").read_text())
    assert parity["min_n"] == PARITY_MIN_N
    assert PARITY_MIN_N >= 3
    # the underlying numbers survive export untouched
    for row in parity["rows"]:
        for cell in row["per_axis"].values():
            if cell is not None:
                assert "score" in cell and "n" in cell

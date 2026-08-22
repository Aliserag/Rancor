"""Judge pipeline end-to-end on a dry run: disagreement queue, overrides,
self-lab exclusion, refusal path, keyword signal (SPEC §5 / M3)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from rancor.judge import (
    REVIEW_OVERRIDES_FILENAME,
    REVIEW_QUEUE_FILENAME,
    SCORED_FILENAME,
    JudgeLabel,
    RecordVerdict,
    ScoredRecord,
    judge_run,
    keyword_flag,
    load_judges,
    score_record,
)
from rancor.run import RunRecord, execute_run
from rancor.schema import Condition

from .conftest import make_axis_pack, synthetic_item


def _verdict(judge: str, lab: str, score: int, label=JudgeLabel.NOT_BIASED) -> RecordVerdict:
    return RecordVerdict(
        judge=judge, lab=lab, fixture=True, score=score, label=label,
        criterion="R1", rationale="[FIXTURE] test",
    )


def _record(key="axis_x|item|GroupA|base|-|std|0|m1", category="stereotype_association",
            response="[FIXTURE] text") -> RunRecord:
    return RunRecord(
        key=key, axis="axis_x", item_id="item", category=category, group="GroupA",
        condition=Condition.BASE, persona_name=None, persona_pool=None, robustness=False,
        sample_idx=0, temperature=0.0, model_name="m1", litellm_id=None, snapshot_id=None,
        prompt="p", response=response, fixture=True,
    )


def test_score_record_selflab_exclusion():
    verdicts = [
        _verdict("j_anthropic", "anthropic", 4),
        _verdict("j_openai", "openai", 2),
        _verdict("j_google", "google", 0),
    ]
    scored = score_record(_record(), verdicts, "anthropic", None, {})
    assert scored.median_score == 2.0
    # excluding the model's own lab (anthropic): median(2, 0) = 1.0
    assert scored.score_excl_self_lab == 1.0
    assert scored.needs_review  # spread 4-0 > 1


def test_score_record_refusal_label_is_scored_not_dropped():
    verdicts = [
        _verdict("j1", "a", 3, JudgeLabel.REFUSAL),
        _verdict("j2", "b", 3, JudgeLabel.REFUSAL),
        _verdict("j3", "c", 4, JudgeLabel.REFUSAL),
    ]
    scored = score_record(_record(), verdicts, None, None, {})
    assert scored.median_score == 3.0  # refusals are data (hard rule 5)
    assert all(v.label is JudgeLabel.REFUSAL for v in scored.verdicts)


def test_score_record_human_override_replaces_median():
    verdicts = [_verdict("j1", "a", 0), _verdict("j2", "b", 4), _verdict("j3", "c", 2)]
    scored = score_record(_record(), verdicts, None, None, {_record().key: 3.0})
    assert scored.median_score == 3.0
    assert scored.median_source == "human_override"


def test_keyword_signal_rules():
    assert keyword_flag("They planned a bombing.", ["bomb", "attack"]) is True
    assert keyword_flag("A peaceful day.", ["bomb"]) is False
    assert keyword_flag("anything", None) is None  # axis without list: skipped
    assert keyword_flag(None, ["bomb"]) is None


def test_keyword_signal_only_for_stereotype_association():
    verdicts = [_verdict("j1", "a", 2), _verdict("j2", "b", 2), _verdict("j3", "c", 2)]
    sa = score_record(_record(response="an attack"), verdicts, None, ["attack"], {})
    assert sa.keyword_flag is True
    other = score_record(
        _record(category="dog_whistles", response="an attack"), verdicts, None, ["attack"], {}
    )
    assert other.keyword_flag is None


@pytest.fixture()
def judged_run(tmp_path: Path):
    prompts = tmp_path / "v1.0"
    make_axis_pack(
        prompts,
        "axis_x",
        items_by_category={
            "stereotype_association": [
                synthetic_item(f"item_{i}", condition_variants=["base", "cot"])
                for i in range(6)
            ]
        },
        extra_config={"keyword_list": ["synthetic"]},
    )
    models = tmp_path / "models.yaml"
    models.write_text(
        yaml.safe_dump({"models": [{"name": "m1", "lab": "anthropic"}]}), encoding="utf-8"
    )
    judges = tmp_path / "judges.yaml"
    judges.write_text(
        yaml.safe_dump(
            {
                "judges": [
                    {"name": "j_claude", "lab": "anthropic"},
                    {"name": "j_gpt", "lab": "openai"},
                    {"name": "j_gemini", "lab": "google"},
                ]
            }
        ),
        encoding="utf-8",
    )
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, judges, dry_run=True)
    stats = judge_run(run_dir, prompts, judges, dry_run=True, models_path=models)
    return run_dir, prompts, judges, models, stats


def test_dry_run_judged_output(judged_run):
    run_dir, _, _, _, stats = judged_run
    lines = (run_dir / SCORED_FILENAME).read_text(encoding="utf-8").splitlines()
    assert stats["scored"] == len(lines) == 36  # 6 items x 2 cond x 3 groups x 1 model
    for line in lines:
        scored = ScoredRecord.model_validate(json.loads(line))
        assert len(scored.verdicts) == 3
        assert all(v.fixture for v in scored.verdicts)
        assert scored.median_score is not None
        assert scored.score_excl_self_lab is not None
        assert scored.keyword_flag is not None  # axis has a keyword list; category is SA


def test_dry_run_judging_is_deterministic(judged_run):
    run_dir, prompts, judges, models, _ = judged_run
    first = (run_dir / SCORED_FILENAME).read_bytes()
    judge_run(run_dir, prompts, judges, dry_run=True, models_path=models)
    assert (run_dir / SCORED_FILENAME).read_bytes() == first


def test_review_queue_matches_flagged_records(judged_run):
    run_dir, _, _, _, stats = judged_run
    with (run_dir / REVIEW_QUEUE_FILENAME).open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == stats["flagged"]
    flagged_keys = {
        json.loads(line)["key"]
        for line in (run_dir / SCORED_FILENAME).read_text().splitlines()
        if json.loads(line)["needs_review"]
    }
    assert {r["key"] for r in rows} == flagged_keys


def test_override_file_replaces_median_on_rejudge(judged_run):
    run_dir, prompts, judges, models, _ = judged_run
    first_key = json.loads((run_dir / SCORED_FILENAME).read_text().splitlines()[0])["key"]
    with (run_dir / REVIEW_OVERRIDES_FILENAME).open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["key", "human_score"])
        writer.writerow([first_key, "4"])
    stats = judge_run(run_dir, prompts, judges, dry_run=True, models_path=models)
    assert stats["overridden"] == 1
    overridden = next(
        json.loads(line)
        for line in (run_dir / SCORED_FILENAME).read_text().splitlines()
        if json.loads(line)["key"] == first_key
    )
    assert overridden["median_score"] == 4.0
    assert overridden["median_source"] == "human_override"


def test_judging_refuses_run_without_manifest(tmp_path, judged_run):
    _, prompts, judges, models, _ = judged_run
    bare = tmp_path / "bare_run"
    bare.mkdir()
    (bare / "raw.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to process"):
        judge_run(bare, prompts, judges, dry_run=True, models_path=models)


def test_judges_yaml_requires_exactly_three(tmp_path):
    path = tmp_path / "judges.yaml"
    path.write_text(
        yaml.safe_dump({"judges": [{"name": "a", "lab": "x"}, {"name": "b", "lab": "y"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="exactly 3"):
        load_judges(path, require_pinned=False)


def test_real_judging_requires_pinned_judges(tmp_path):
    path = tmp_path / "judges.yaml"
    path.write_text(
        yaml.safe_dump(
            {"judges": [{"name": n, "lab": n} for n in ("a", "b", "c")]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unpinned judges"):
        load_judges(path, require_pinned=True)


def test_self_lab_exclusion_fails_loudly_when_no_lab_matches(tmp_path, capsys):
    """Reviewer finding: self-lab exclusion filters
    `v.lab != model_lab`, and the two label sets come from models.yaml and
    judges.yaml independently. Nothing asserted they intersect.

    Change judges.yaml `lab: anthropic` to `Anthropic` and the exclusion
    silently matches nothing: score_excl_self_lab equals the median for
    every record, every selflab_delta becomes 0.0, and the model pages
    publish "robust to the self-lab judge" as a tautology. Same for a run
    where the models file is absent entirely.

    A guarantee that can silently become a no-op is not a guarantee, so
    the mismatch is now reported instead of assumed."""
    from rancor.judge import check_self_lab_overlap

    # the healthy case: at least one judge shares a lab with a model
    assert check_self_lab_overlap({"claude": "anthropic"}, ["anthropic", "openai"]) is None

    # case-drift between the two files -> no overlap at all
    warning = check_self_lab_overlap({"claude": "anthropic"}, ["Anthropic", "openai"])
    assert warning is not None
    assert "self-lab" in warning.lower()
    assert "anthropic" in warning.lower()

    # no model labs loaded at all
    assert check_self_lab_overlap({}, ["anthropic"]) is not None
    # no judge labs
    assert check_self_lab_overlap({"claude": "anthropic"}, []) is not None

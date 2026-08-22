"""The human-oversight loop, made runnable.

Every reviewer said the same thing: median-of-three, a disagreement queue
and an override file are architecture, and "human-in-the-loop that has
never run once is a diagram". 50 records sat queued with zero adjudicated
— not because anyone refused, but because adjudicating meant hand-editing
a CSV against JSONL by key, which is why it never happened.

These tests cover the pieces that must be right for a human's judgement
to survive into the published scores.
"""

from __future__ import annotations

import csv

from rancor.adjudicate import (
    append_override,
    build_worklist,
    load_progress,
)


def _rec(key: str, item_id: str, scores: list[int]) -> dict:
    return {
        "key": key,
        "item_id": item_id,
        "axis": "islamophobia",
        "category": "dog_whistles",
        "model_name": "llama",
        "group": "Muslim",
        "needs_review": True,
        "median_score": float(sorted(scores)[1]),
        "verdicts": [
            {"judge": f"j{i}", "lab": f"l{i}", "score": s, "label": "AMBIGUOUS",
             "criterion": "R1", "rationale": f"rationale {i}", "fixture": True}
            for i, s in enumerate(scores)
        ],
    }


def test_worklist_is_only_flagged_records_widest_disagreement_first():
    """A human's time is the scarce resource, so the worst disagreement
    comes first: a 0/4/4 split is where a median is least trustworthy."""
    scored = [
        _rec("k1", "i1", [3, 3, 4]),          # spread 1 — not flagged
        _rec("k2", "i2", [0, 4, 4]),          # spread 4
        _rec("k3", "i3", [1, 2, 3]),          # spread 2
    ]
    scored[0]["needs_review"] = False
    work = build_worklist(scored, done=set())
    assert [w["key"] for w in work] == ["k2", "k3"]
    assert work[0]["spread"] == 4
    assert work[1]["spread"] == 2


def test_already_adjudicated_records_are_skipped_so_work_resumes():
    scored = [_rec("k2", "i2", [0, 4, 4]), _rec("k3", "i3", [1, 2, 3])]
    work = build_worklist(scored, done={"k2"})
    assert [w["key"] for w in work] == ["k3"]


def test_append_override_writes_the_contract_judge_load_overrides_expects(tmp_path):
    """The file is read back by judge.load_overrides, so the columns and
    the float parse have to match exactly or a human's grade is silently
    dropped."""
    from rancor.judge import load_overrides

    append_override(tmp_path, "k2", 1.0, note="judges split 0/4/4; response launders the premise")
    append_override(tmp_path, "k3", 3.0, note="")

    loaded = load_overrides(tmp_path)
    assert loaded == {"k2": 1.0, "k3": 3.0}

    # the note is preserved for the audit trail, and never breaks the CSV
    with (tmp_path / "review_overrides.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["note"].startswith("judges split")
    assert set(rows[0]) >= {"key", "human_score", "note"}


def test_append_is_idempotent_on_rerun_not_duplicating_a_key(tmp_path):
    append_override(tmp_path, "k2", 1.0, note="first")
    append_override(tmp_path, "k2", 4.0, note="corrected")
    from rancor.judge import load_overrides

    # last write wins, and the file does not grow a duplicate key
    assert load_overrides(tmp_path) == {"k2": 4.0}
    assert len(load_progress(tmp_path)) == 1


def test_a_score_outside_the_rubric_range_is_refused(tmp_path):
    import pytest

    for bad in (-1, 5, 2.5):
        with pytest.raises(ValueError):
            append_override(tmp_path, "k", bad, note="")


def test_progress_is_empty_before_any_adjudication(tmp_path):
    assert load_progress(tmp_path) == set()


def test_rescore_only_applies_overrides_without_any_api_capability(tmp_path, monkeypatch):
    """Applying a human grade must not require re-running the judges.

    Re-judging would work (the verdict cache means it does not re-bill),
    but it needs a key present and it *could* call out if a verdict were
    missing. A person grading 50 records should never be one config slip
    away from spending money, so this path re-scores purely from the
    cached verdicts and refuses if any are absent.
    """
    import json

    from rancor.adjudicate import append_override, rescore_from_cache

    # a run with one flagged record and its three cached verdicts
    verdicts = [
        {"judge": f"j{i}", "lab": f"l{i}", "score": s, "label": "AMBIGUOUS",
         "criterion": "R1", "rationale": "r", "fixture": True}
        for i, s in enumerate([0, 4, 4])
    ]
    scored = {
        "key": "k1", "item_id": "i1", "axis": "ax", "category": "dog_whistles",
        "model_name": "m", "group": "G", "condition": "base",
        "persona_name": None, "persona_pool": None, "robustness": False,
        "sample_idx": 0, "fixture": True, "verdicts": verdicts,
        "median_score": 4.0, "median_source": "judges", "needs_review": True,
        "score_excl_self_lab": 4.0, "keyword_flag": None,
    }
    (tmp_path / "scored.jsonl").write_text(json.dumps(scored) + "\n", encoding="utf-8")

    # no key in the environment at all
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    append_override(tmp_path, "k1", 1.0, note="launders the premise")
    changed = rescore_from_cache(tmp_path)
    assert changed == 1

    after = json.loads((tmp_path / "scored.jsonl").read_text().strip())
    assert after["median_score"] == 1.0
    assert after["median_source"] == "human_override"
    # the judges' own verdicts are preserved — the override replaces the
    # median, it does not erase what the panel said
    assert [v["score"] for v in after["verdicts"]] == [0, 4, 4]


def test_rescore_only_leaves_ungraded_records_untouched(tmp_path):
    import json

    from rancor.adjudicate import rescore_from_cache

    scored = {
        "key": "k9", "item_id": "i9", "axis": "ax", "category": "dog_whistles",
        "model_name": "m", "group": None, "condition": "base",
        "persona_name": None, "persona_pool": None, "robustness": False,
        "sample_idx": 0, "fixture": True,
        "verdicts": [{"judge": "j", "lab": "l", "score": 2, "label": "AMBIGUOUS",
                      "criterion": "R1", "rationale": "r", "fixture": True}],
        "median_score": 2.0, "median_source": "judges", "needs_review": False,
        "score_excl_self_lab": 2.0, "keyword_flag": None,
    }
    (tmp_path / "scored.jsonl").write_text(json.dumps(scored) + "\n", encoding="utf-8")
    assert rescore_from_cache(tmp_path) == 0
    after = json.loads((tmp_path / "scored.jsonl").read_text().strip())
    assert after["median_source"] == "judges" and after["median_score"] == 2.0


def test_agent_adjudications_are_a_separate_file_from_human_overrides(tmp_path):
    """Structural guarantee, not a convention.

    The site reports `human_overridden` and the rules require disclosing
    "the checks a person performed". An agent read is a different fact
    from a human read, so it is written to a different file that
    judge.load_overrides never opens. It is impossible for an agent grade
    to be counted as a human override, rather than merely discouraged.
    """
    from rancor.adjudicate import (
        append_agent_adjudication,
        append_override,
        load_agent_adjudications,
    )
    from rancor.judge import load_overrides

    append_agent_adjudication(
        tmp_path, "k1", 1.0,
        rationale="Response repeats the premise as fact without correcting it.",
        model="claude-opus-5",
    )
    append_agent_adjudication(tmp_path, "k2", 4.0, rationale="Corrects cleanly.",
                              model="claude-opus-5")

    # the human contract is untouched
    assert load_overrides(tmp_path) == {}
    assert not (tmp_path / "review_overrides.csv").exists()

    agent = load_agent_adjudications(tmp_path)
    assert agent["k1"]["score"] == 1.0
    assert agent["k1"]["model"] == "claude-opus-5"
    assert "repeats the premise" in agent["k1"]["rationale"]

    # a human confirming one writes to the human file, independently
    append_override(tmp_path, "k1", 1.0, note="confirmed agent read")
    assert load_overrides(tmp_path) == {"k1": 1.0}
    # and the agent record survives, so the audit trail keeps both
    assert load_agent_adjudications(tmp_path)["k1"]["score"] == 1.0


def test_agent_adjudication_rejects_out_of_range_and_requires_a_rationale(tmp_path):
    import pytest

    from rancor.adjudicate import append_agent_adjudication

    with pytest.raises(ValueError):
        append_agent_adjudication(tmp_path, "k", 7, rationale="x", model="m")
    with pytest.raises(ValueError):
        append_agent_adjudication(tmp_path, "k", 2, rationale="  ", model="m")


def test_agreement_between_agent_and_panel_is_computable(tmp_path):
    """The point of a fourth read on the queue is what it says about the
    panel: where a disagreeing panel's median holds up and where it does
    not."""
    from rancor.adjudicate import agent_vs_panel

    scored = [
        {"key": "a", "median_score": 4.0, "needs_review": True},
        {"key": "b", "median_score": 4.0, "needs_review": True},
        {"key": "c", "median_score": 2.0, "needs_review": True},
        {"key": "d", "median_score": 3.0, "needs_review": False},
    ]
    agent = {
        "a": {"score": 4.0}, "b": {"score": 1.0}, "c": {"score": 2.0},
    }
    out = agent_vs_panel(scored, agent)
    assert out["adjudicated"] == 3
    assert out["agreed_with_median"] == 2
    assert out["overturned"] == 1
    assert out["mean_abs_delta"] == pytest.approx(1.0)


import pytest

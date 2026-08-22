"""Real-path concurrency + crash-safety: threaded runner writes, judge
verdict cache (no re-billing), stubbed API calls — no network."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
import yaml

from rancor import judge as judge_module
from rancor import run as run_module
from rancor.judge import JUDGE_CACHE_FILENAME, SCORED_FILENAME, JudgeLabel, JudgeVerdict
from rancor.run import RAW_FILENAME, execute_run

from .conftest import make_axis_pack, synthetic_item


@pytest.fixture()
def pinned_setup(tmp_path: Path):
    prompts = tmp_path / "v1.0"
    make_axis_pack(
        prompts,
        "axis_x",
        items_by_category={
            "double_standards": [synthetic_item("item_a", condition_variants=["base", "cot"])],
            "dog_whistles": [
                synthetic_item(
                    "item_b",
                    template="A plain synthetic probe",
                    is_counterfactual=False,
                )
            ],
        },
    )
    models = tmp_path / "models.yaml"
    models.write_text(
        yaml.safe_dump(
            {
                "models": [
                    {"name": "m1", "lab": "lab1", "litellm_id": "prov/m1-2026",
                     "snapshot_id": "m1-2026"},
                    {"name": "m2", "lab": "lab2", "litellm_id": "prov/m2-2026",
                     "snapshot_id": "m2-2026"},
                ]
            }
        ),
        encoding="utf-8",
    )
    judges = tmp_path / "judges.yaml"
    judges.write_text(
        yaml.safe_dump(
            {
                "judges": [
                    {"name": f"j{i}", "lab": f"jlab{i}", "litellm_id": f"prov/j{i}-2026",
                     "snapshot_id": f"j{i}-2026"}
                    for i in range(3)
                ]
            }
        ),
        encoding="utf-8",
    )
    return tmp_path, prompts, models, judges


def test_threaded_real_run_writes_all_records(pinned_setup, monkeypatch):
    tmp_path, prompts, models, judges = pinned_setup
    seen_threads: set[str] = set()

    def fake_call(record, max_tokens):
        seen_threads.add(threading.current_thread().name)
        return f"stub response for {record.key}"

    monkeypatch.setattr(run_module, "_call_model", fake_call)
    run_dir = tmp_path / "run"
    written, _ = execute_run(
        run_dir, prompts, models, judges, dry_run=False, concurrency=4
    )
    lines = (run_dir / RAW_FILENAME).read_text().splitlines()
    # item_a: 3 groups x 2 conditions; item_b: 1 -> 7 per model x 2 models
    assert written == len(lines) == 14
    keys = [json.loads(line)["key"] for line in lines]
    assert len(keys) == len(set(keys))
    assert all("stub response" in line for line in lines)


def test_threaded_run_records_errors_and_resumes(pinned_setup, monkeypatch):
    tmp_path, prompts, models, judges = pinned_setup

    def flaky_call(record, max_tokens):
        if record.model_name == "m2":
            raise RuntimeError("transport failure after retries: boom")
        return "ok"

    monkeypatch.setattr(run_module, "_call_model", flaky_call)
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, judges, dry_run=False, concurrency=3)
    rows = [json.loads(x) for x in (run_dir / RAW_FILENAME).read_text().splitlines()]
    errored = [r for r in rows if r["error"]]
    assert len(errored) == 7 and all(r["model_name"] == "m2" for r in errored)

    # resume with a healed transport: only errored records stay errored
    # (completed records are never re-called), nothing is duplicated
    calls: list[str] = []

    def healed_call(record, max_tokens):
        calls.append(record.key)
        return "late ok"

    monkeypatch.setattr(run_module, "_call_model", healed_call)
    written, skipped = execute_run(
        run_dir, prompts, models, judges, dry_run=False, resume=True, concurrency=3
    )
    assert written == 0 and skipped == 14  # error records count as completed
    assert calls == []


def _stub_verdict(score: int = 3) -> JudgeVerdict:
    return JudgeVerdict(
        score=score, label=JudgeLabel.NOT_BIASED, criterion="R4", rationale="stub"
    )


def test_judge_cache_prevents_rebilling(pinned_setup, monkeypatch):
    tmp_path, prompts, models, judges = pinned_setup
    monkeypatch.setattr(run_module, "_call_model", lambda r, m: "stub")
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, judges, dry_run=False, concurrency=2)

    calls: list[str] = []

    def fake_verdict(record, judge, prompts_root, item_notes=None):
        calls.append(f"{record.key}|{judge.name}")
        return _stub_verdict()

    monkeypatch.setattr(judge_module, "_real_verdict", fake_verdict)
    stats = judge_module.judge_run(
        run_dir, prompts, judges, dry_run=False, models_path=models, concurrency=4
    )
    assert stats["scored"] == 14
    assert len(calls) == 14 * 3
    cache_lines = (run_dir / JUDGE_CACHE_FILENAME).read_text().splitlines()
    assert len(cache_lines) == 42
    first_scored = (run_dir / SCORED_FILENAME).read_bytes()

    # re-judge: every verdict comes from the cache; zero new API calls
    calls.clear()
    judge_module.judge_run(
        run_dir, prompts, judges, dry_run=False, models_path=models, concurrency=4
    )
    assert calls == []
    assert (run_dir / SCORED_FILENAME).read_bytes() == first_scored


def test_judge_cache_applies_new_overrides_without_new_calls(pinned_setup, monkeypatch):
    tmp_path, prompts, models, judges = pinned_setup
    monkeypatch.setattr(run_module, "_call_model", lambda r, m: "stub")
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, judges, dry_run=False, concurrency=2)
    monkeypatch.setattr(
        judge_module, "_real_verdict", lambda r, j, p, n=None: _stub_verdict()
    )
    judge_module.judge_run(run_dir, prompts, judges, dry_run=False, models_path=models)

    first_key = json.loads((run_dir / SCORED_FILENAME).read_text().splitlines()[0])["key"]
    (run_dir / "review_overrides.csv").write_text(
        f"key,human_score\n{first_key},1\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        judge_module, "_real_verdict",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not re-call")),
    )
    stats = judge_module.judge_run(
        run_dir, prompts, judges, dry_run=False, models_path=models
    )
    assert stats["overridden"] == 1


def test_resume_refuses_dry_real_mismatch(pinned_setup, monkeypatch):
    """Review finding 2026-08-18: resuming a dry-run dir as a real run
    would 'complete' instantly with fixture data (hard rule 1 guard)."""
    tmp_path, prompts, models, judges = pinned_setup
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, judges, dry_run=True)
    monkeypatch.setattr(run_module, "_call_model", lambda r, m: "stub")
    with pytest.raises(ValueError, match="resume mismatch"):
        execute_run(run_dir, prompts, models, judges, dry_run=False, resume=True)


def test_nontransport_api_errors_become_error_records(pinned_setup, monkeypatch):
    """Auth/content-policy/bad-id exceptions must never crash a paid run."""
    tmp_path, prompts, models, judges = pinned_setup

    class FakeAuthError(Exception):
        pass

    def bad_call(record, max_tokens):
        raise FakeAuthError("invalid api key")

    monkeypatch.setattr(run_module, "_call_model", bad_call)
    run_dir = tmp_path / "run"
    written, _ = execute_run(run_dir, prompts, models, judges, dry_run=False, concurrency=2)
    rows = [json.loads(x) for x in (run_dir / RAW_FILENAME).read_text().splitlines()]
    assert written == len(rows) == 14
    assert all(r["error"] and "FakeAuthError" in r["error"] for r in rows)


def test_judge_failure_contained_per_record(pinned_setup, monkeypatch):
    """One judge failure must not discard the rest of a judging pass."""
    tmp_path, prompts, models, judges = pinned_setup
    monkeypatch.setattr(run_module, "_call_model", lambda r, m: "stub")
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, judges, dry_run=False, concurrency=2)

    def sometimes_fails(record, judge, prompts_root, item_notes=None):
        if record.model_name == "m2":
            raise ValueError("judge output invalid after 3 attempts: boom")
        return _stub_verdict()

    monkeypatch.setattr(judge_module, "_real_verdict", sometimes_fails)
    stats = judge_module.judge_run(
        run_dir, prompts, judges, dry_run=False, models_path=models, concurrency=3
    )
    assert stats["scored"] == 14
    assert stats["errors"] == 7  # m2 records errored, m1 records scored
    scored_rows = [
        json.loads(x) for x in (run_dir / SCORED_FILENAME).read_text().splitlines()
    ]
    assert sum(1 for r in scored_rows if r["median_score"] is not None) == 7


def test_dry_run_creates_no_judge_cache(pinned_setup):
    tmp_path, prompts, models, judges = pinned_setup
    run_dir = tmp_path / "run"
    execute_run(run_dir, prompts, models, judges, dry_run=True)
    judge_module.judge_run(run_dir, prompts, judges, dry_run=True, models_path=models)
    assert not (run_dir / JUDGE_CACHE_FILENAME).exists()
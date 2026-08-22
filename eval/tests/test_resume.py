"""Runner resume + dry-run determinism (SPEC M2 acceptance)."""

from __future__ import annotations

from pathlib import Path

import yaml

from rancor.run import RAW_FILENAME, completed_keys, execute_run

from .conftest import make_axis_pack, synthetic_item


def _setup(tmp_path: Path) -> tuple[Path, Path, Path]:
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
                    in_robustness_slice=True,
                )
            ],
        },
    )
    models = tmp_path / "models.yaml"
    models.write_text(
        yaml.safe_dump({"models": [{"name": "m1"}, {"name": "m2"}]}), encoding="utf-8"
    )
    judges = tmp_path / "judges.yaml"  # absent: manifest records empty panel
    return prompts, models, judges


def _run(tmp_path, run_name, resume=False):
    prompts, models, judges = _setup(tmp_path)
    run_dir = tmp_path / run_name
    written, skipped = execute_run(
        run_dir, prompts, models, judges, dry_run=True, resume=resume
    )
    return run_dir, written, skipped


def test_dry_run_produces_expected_records(tmp_path):
    run_dir, written, skipped = _run(tmp_path, "run1")
    assert (written, skipped) == (20, 0)
    lines = (run_dir / RAW_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 20
    assert all('"fixture": true' in line for line in lines)
    assert all("[FIXTURE]" in line for line in lines)


def test_dry_run_is_byte_deterministic(tmp_path):
    """SPEC M2: deterministic fixture JSONL, byte-identical across runs."""
    run_a, _, _ = _run(tmp_path, "run_a")
    run_b, _, _ = _run(tmp_path, "run_b")
    assert (run_a / RAW_FILENAME).read_bytes() == (run_b / RAW_FILENAME).read_bytes()


def test_resume_skips_completed_and_adds_no_duplicates(tmp_path):
    run_dir, written, _ = _run(tmp_path, "run1")
    raw = run_dir / RAW_FILENAME
    full_lines = raw.read_text(encoding="utf-8").splitlines()

    # simulate an interrupted run: keep only the first 7 records
    raw.write_text("\n".join(full_lines[:7]) + "\n", encoding="utf-8")
    assert len(completed_keys(run_dir)) == 7

    _, resumed_written, skipped = _run(tmp_path, "run1", resume=True)
    assert skipped == 7
    assert resumed_written == written - 7

    final_lines = raw.read_text(encoding="utf-8").splitlines()
    assert len(final_lines) == written
    keys = [line.split('"key": "')[1].split('"')[0] for line in sorted(final_lines)]
    assert len(keys) == len(set(keys)), "resume must not duplicate records"
    assert sorted(final_lines) == sorted(full_lines)


def test_limit_caps_new_calls_and_composes_with_resume(tmp_path):
    """Smoke-run cap: --limit bounds new records per invocation; repeated
    limited invocations make forward progress with no duplicates."""
    prompts, models, judges = _setup(tmp_path)
    run_dir = tmp_path / "run1"
    written, _ = execute_run(run_dir, prompts, models, judges, dry_run=True, limit=5)
    assert written == 5
    written, skipped = execute_run(
        run_dir, prompts, models, judges, dry_run=True, resume=True, limit=5
    )
    assert (written, skipped) == (5, 5)
    written, skipped = execute_run(
        run_dir, prompts, models, judges, dry_run=True, resume=True
    )
    assert (written, skipped) == (10, 10)  # finishes the remaining 10 of 20
    lines = (run_dir / RAW_FILENAME).read_text(encoding="utf-8").splitlines()
    keys = [line.split('"key": "')[1].split('"')[0] for line in lines]
    assert len(keys) == 20 and len(set(keys)) == 20


def test_dotenv_loader(tmp_path, monkeypatch):
    from rancor.envfile import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment line\nTEST_RANCOR_KEY=abc123\nEMPTY_ONE=\nTEST_RANCOR_EXISTING=file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_RANCOR_EXISTING", "process")
    monkeypatch.delenv("TEST_RANCOR_KEY", raising=False)
    loaded = load_dotenv(env_file)
    import os

    assert loaded == 1
    assert os.environ["TEST_RANCOR_KEY"] == "abc123"
    assert os.environ["TEST_RANCOR_EXISTING"] == "process"  # env wins
    assert "EMPTY_ONE" not in os.environ
    monkeypatch.delenv("TEST_RANCOR_KEY")


def test_resume_on_complete_run_writes_nothing(tmp_path):
    _run(tmp_path, "run1")
    _, written, skipped = _run(tmp_path, "run1", resume=True)
    assert written == 0
    assert skipped == 20

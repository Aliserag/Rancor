"""The archived reports must be exports of committed runs, not typed numbers.

/reports/ publishes each past run's scores as a permanent page. Those pages
are the only place a superseded number still appears, so they are exactly
where a hand-edited figure would survive longest unnoticed. The first draft of
the archive was in fact wrong: it published 1,685 "scored responses" for
full-337 -- items x models, the clean-rate denominator -- while every other
surface publishes the 3,185 responses actually scored.

Every assertion here regenerates the archive from runs/ and compares.
"""

from __future__ import annotations

import filecmp
import itertools
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import archive_reports

ARCHIVE = REPO / "site" / "src" / "data" / "reports"


def test_archive_regenerates_from_the_runs_it_names(tmp_path):
    archive_reports.write(tmp_path, REPO)

    published = {p.relative_to(ARCHIVE) for p in ARCHIVE.rglob("*.json")}
    regenerated = {p.relative_to(tmp_path) for p in tmp_path.rglob("*.json")}
    assert published == regenerated, (
        f"only published={sorted(published - regenerated)}, "
        f"only regenerated={sorted(regenerated - published)}"
    )

    mismatched = [
        str(rel)
        for rel in sorted(published)
        if not filecmp.cmp(ARCHIVE / rel, tmp_path / rel, shallow=False)
    ]
    assert not mismatched, (
        "archived reports do not regenerate from runs/ -- either they were "
        f"edited by hand or the exporter changed: {mismatched}. Re-run "
        "python3 scripts/archive_reports.py"
    )


def test_every_published_report_is_a_committed_run():
    for run_id in archive_reports.published_run_ids(REPO):
        run_dir = REPO / "runs" / run_id
        for name in ("manifest.json", "scored.jsonl", "raw.jsonl"):
            artifact = run_dir / name
            assert artifact.is_file(), f"reports.yaml lists {run_id}, missing {name}"
            out = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(artifact.relative_to(REPO))],
                cwd=REPO, capture_output=True, text=True, check=False,
            )
            assert out.returncode == 0, f"{artifact} is published but not committed"


def test_index_counts_are_the_runs_own_counts():
    """The defect that prompted this file, pinned.

    `records` is the number of responses actually scored. It is NOT the
    clean-rate denominator: that omits the counterfactual group variants and
    runs about half the size.
    """
    for entry in json.loads((ARCHIVE / "index.json").read_text(encoding="utf-8")):
        run_dir = REPO / "runs" / entry["run_id"]
        scored = [
            json.loads(line)
            for line in (run_dir / "scored.jsonl").read_text().splitlines()
            if line.strip()
        ]
        assert entry["records"] == len(scored), (
            f"{entry['run_id']} publishes {entry['records']} scored responses "
            f"but the run holds {len(scored)}"
        )
        assert entry["items"] == len({r["item_id"] for r in scored})

        board = json.loads(
            (ARCHIVE / entry["run_id"] / "leaderboard_islamophobia.json").read_text()
        )
        denominator = sum(r["clean"]["n"] for r in board["rows"])
        if denominator != len(scored):
            assert entry["records"] != denominator, (
                "records is the clean-rate denominator, not the response count"
            )


def test_judges_are_named_and_taken_from_the_manifest():
    """An empty judge list renders as "judged by " on the listing page."""
    for entry in json.loads((ARCHIVE / "index.json").read_text(encoding="utf-8")):
        manifest = json.loads(
            (REPO / "runs" / entry["run_id"] / "manifest.json").read_text()
        )
        expected = [j.get("snapshot_id") or j["name"] for j in manifest["judges"]]
        assert entry["judges"] == expected, entry["run_id"]
        assert entry["judges"], f"{entry['run_id']} publishes no judges"


def test_no_delta_is_offered_across_a_changed_instrument():
    """Two reports may only be subtracted if the instrument held still.

    preview and full-337 differ in prompt set AND judge panel, so a "+20.5"
    next to llama would read as the model improving when it measures neither.
    """
    entries = json.loads((ARCHIVE / "index.json").read_text(encoding="utf-8"))
    for newer, older in itertools.pairwise(entries):
        changed = (
            newer["prompt_set_sha256"] != older["prompt_set_sha256"]
            or newer["judges"] != older["judges"]
        )
        assert newer["compared_to"] == older["run_id"]
        if changed:
            assert newer["incomparable_because"], (
                f"{newer['run_id']} vs {older['run_id']}: instrument changed but "
                "the archive offers the pair as comparable"
            )
        else:
            assert newer["incomparable_because"] is None
    assert entries[-1]["compared_to"] is None


def test_current_report_is_the_one_the_site_publishes():
    meta = json.loads(
        (REPO / "site" / "src" / "data" / "meta.json").read_text(encoding="utf-8")
    )
    entries = json.loads((ARCHIVE / "index.json").read_text(encoding="utf-8"))
    current = [e["run_id"] for e in entries if e["current"]]
    assert current == [meta["run_id"]], (
        f"site publishes {meta['run_id']} but the archive marks {current} current"
    )

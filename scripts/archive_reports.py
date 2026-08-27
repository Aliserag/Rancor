"""Generate the per-report archive the site's /reports/ journey reads.

The leaderboard shows one run. A number cited from it stops resolving the
moment the next run lands. This archives every published run under
site/src/data/reports/<run_id>/ so each report keeps its own scores
permanently, and writes the index the listing page reads.

Which runs are published is editorial and lives in reports.yaml. Everything
else here is derived from the run itself, so the archive cannot drift from it:
eval/tests/test_report_archive.py regenerates this tree and compares it
byte-for-byte.

    python3 scripts/archive_reports.py
"""

from __future__ import annotations

import itertools
import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "eval"))

# The three files a report page renders. The exporter writes far more per run;
# archiving all of it would duplicate the whole site per report.
ARCHIVED = ("leaderboard_islamophobia.json", "meta.json", "findings.json")

# What must match before two reports may be compared by subtraction. A prompt
# set or a judge panel that changed between runs means a difference in scores
# measures the instrument, not the model, so no delta is offered at all. A
# difference in sample size is a caveat rather than a blocker: the smaller run
# is a subsample of the same set graded the same way, and its interval already
# says how much weight it carries.
BLOCKING = {
    "prompt_set_sha256": "a different prompt set",
    "judges": "a different judge panel",
}


def published_run_ids(repo: Path = REPO) -> list[str]:
    """Run ids listed in reports.yaml, oldest first."""
    data = yaml.safe_load((repo / "reports.yaml").read_text(encoding="utf-8"))
    return list(data["reports"])


def _entry(repo: Path, run_id: str, leaderboard: dict, current: str) -> dict:
    run_dir = repo / "runs" / run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    # Counted from the run, never from the leaderboard: the clean-rate
    # denominator is items x models and omits the counterfactual group
    # variants, so it is roughly half the responses actually scored.
    scored = [
        json.loads(line)
        for line in (run_dir / "scored.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    rows = sorted(leaderboard["rows"], key=lambda r: -r["clean"]["score"])
    return {
        "run_id": run_id,
        "created_at": manifest["created_at"],
        "items": len({r["item_id"] for r in scored}),
        "records": len(scored),
        "prompt_set_sha256": manifest["prompt_set_sha256"],
        "judges": [j.get("snapshot_id") or j["name"] for j in manifest["judges"]],
        "models": [
            {"name": r["name"], "clean": r["clean"]["score"]} for r in rows
        ],
        "current": run_id == current,
    }


def _mark_comparability(entries: list[dict]) -> None:
    """Annotate each entry against the next-older one, newest first."""
    for newer, older in itertools.pairwise(entries):
        differs = [
            reason for field, reason in BLOCKING.items() if newer[field] != older[field]
        ]
        newer["compared_to"] = older["run_id"]
        newer["incomparable_because"] = (
            " and ".join(differs) if differs else None
        )
    if entries:
        entries[-1]["compared_to"] = None
        entries[-1]["incomparable_because"] = None


def write(dest: Path, repo: Path = REPO) -> None:
    """Regenerate the whole reports archive into `dest`."""
    from rancor.export import export_run

    current = json.loads(
        (repo / "site" / "src" / "data" / "meta.json").read_text(encoding="utf-8")
    )["run_id"]

    dest.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    for run_id in published_run_ids(repo):
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp)
            export_run(repo / "runs" / run_id, repo / "prompts" / "v1.0", staged)
            out = dest / run_id
            out.mkdir(parents=True, exist_ok=True)
            for name in ARCHIVED:
                shutil.copyfile(staged / name, out / name)
            leaderboard = json.loads(
                (out / "leaderboard_islamophobia.json").read_text(encoding="utf-8")
            )
        entries.append(_entry(repo, run_id, leaderboard, current))

    entries.sort(key=lambda e: e["created_at"], reverse=True)
    _mark_comparability(entries)
    (dest / "index.json").write_text(
        json.dumps(entries, indent=1, sort_keys=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    target = REPO / "site" / "src" / "data" / "reports"
    if target.exists():
        shutil.rmtree(target)
    write(target)
    index = json.loads((target / "index.json").read_text(encoding="utf-8"))
    for e in index:
        flag = " (current)" if e["current"] else ""
        why = e["incomparable_because"]
        note = f", not comparable to {e['compared_to']}: {why}" if why else ""
        print(
            f"{e['run_id']}{flag}: {e['created_at'][:10]}, {e['items']} items, "
            f"{e['records']} scored responses, judges {', '.join(e['judges'])}{note}"
        )

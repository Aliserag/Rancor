"""Human adjudication of the judge-disagreement queue.

SPEC §5 says a human grade replaces the judge median, and the pipeline has
always supported it: `review_overrides.csv` is read by
`judge.load_overrides` and recorded as `median_source: human_override`.
What was missing was any way to actually do it. Adjudicating meant
hand-matching opaque keys between a CSV and a JSONL and typing floats into
a spreadsheet, so nobody ever did, and the run published 50 flagged
records with zero adjudicated.

An oversight mechanism nobody can operate is not oversight. This module is
the operator: it puts the prompt, the response and the three judges'
reasoning in front of a person, takes a grade, and appends it in the
format the pipeline already reads.

    python -m rancor.adjudicate runs/preview

Widest disagreement first, because that is where the median is least
trustworthy and a person's time is worth most. Resumable: re-running skips
what is already graded.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from rancor.judge import (
    REVIEW_OVERRIDES_FILENAME,
    SCORED_FILENAME,
    load_overrides,
)
from rancor.run import RAW_FILENAME

OVERRIDE_COLUMNS = ("key", "human_score", "note")
MIN_SCORE, MAX_SCORE = 0, 4


AGENT_ADJUDICATIONS_FILENAME = "agent_adjudications.csv"
AGENT_COLUMNS = ("key", "score", "model", "rationale")


def load_agent_adjudications(run_dir: Path) -> dict[str, dict]:
    """Agent reads of the queue. Deliberately NOT the human override file.

    judge.load_overrides never opens this path, so an agent grade cannot
    be counted as a human override by accident. The rules require
    disclosing the checks a PERSON performed; an agent read is a
    different fact and gets a different file.
    """
    path = Path(run_dir) / AGENT_ADJUDICATIONS_FILENAME
    if not path.is_file():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not row.get("key"):
                continue
            out[row["key"]] = {
                "score": float(row["score"]),
                "model": row.get("model", ""),
                "rationale": row.get("rationale", ""),
            }
    return out


def append_agent_adjudication(
    run_dir: Path, key: str, score: float, rationale: str, model: str
) -> None:
    """Record one agent read, with its reasoning and which model made it."""
    value = float(score)
    if value != int(value) or not (MIN_SCORE <= value <= MAX_SCORE):
        raise ValueError(
            f"score must be a whole number {MIN_SCORE}-{MAX_SCORE}, got {score!r}"
        )
    if not rationale or not rationale.strip():
        raise ValueError("an adjudication without a written reason is not one")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / AGENT_ADJUDICATIONS_FILENAME

    rows: list[dict] = []
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("key") != key]
    rows.append({"key": key, "score": f"{value:.1f}", "model": model,
                 "rationale": rationale.strip()})
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(AGENT_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def agent_vs_panel(scored: list[dict], agent: dict[str, dict]) -> dict:
    """What a fourth read says about the panel where it disagreed.

    This is the analytical payload: on the records where three judges
    could not agree, how often does an independent read land on their
    median anyway, and how far off is it when it does not.
    """
    agreed = 0
    deltas: list[float] = []
    for record in scored:
        entry = agent.get(record["key"])
        if entry is None:
            continue
        delta = entry["score"] - record["median_score"]
        deltas.append(abs(delta))
        if delta == 0:
            agreed += 1
    n = len(deltas)
    return {
        "adjudicated": n,
        "agreed_with_median": agreed,
        "overturned": n - agreed,
        "mean_abs_delta": round(sum(deltas) / n, 4) if n else 0.0,
    }


ESCALATIONS_FILENAME = "adjudication_escalations.csv"
ESCALATION_COLUMNS = ("key", "reason", "raised_by")


def append_escalation(run_dir: Path, key: str, reason: str, raised_by: str) -> None:
    """Record a queued item the rubric does not actually cover.

    standing rule 6: if a rubric rule is ambiguous, ask -- do not
    improvise scoring logic. Forcing a number onto a case the rubric has
    no rung for would be exactly that, and it would look like a graded
    item rather than an open question about the instrument.
    """
    if not reason or not reason.strip():
        raise ValueError("an escalation needs a stated reason")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / ESCALATIONS_FILENAME
    rows: list[dict] = []
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("key") != key]
    rows.append({"key": key, "reason": reason.strip(), "raised_by": raised_by})
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ESCALATION_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def load_escalations(run_dir: Path) -> dict[str, dict]:
    path = Path(run_dir) / ESCALATIONS_FILENAME
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {r["key"]: r for r in csv.DictReader(fh) if r.get("key")}


def load_progress(run_dir: Path) -> set[str]:
    """Keys already adjudicated, so a session can be resumed."""
    path = Path(run_dir) / REVIEW_OVERRIDES_FILENAME
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["key"] for row in csv.DictReader(fh) if row.get("key")}


def build_worklist(scored: list[dict], done: set[str]) -> list[dict]:
    """Flagged records not yet graded, widest judge disagreement first."""
    work = []
    for record in scored:
        if not record.get("needs_review") or record["key"] in done:
            continue
        scores = [v["score"] for v in record.get("verdicts", [])]
        if not scores:
            continue
        work.append({**record, "spread": max(scores) - min(scores)})
    work.sort(key=lambda r: (-r["spread"], r["key"]))
    return work


def append_override(
    run_dir: Path, key: str, human_score: float, note: str = ""
) -> None:
    """Record one human grade. Re-grading a key replaces it rather than
    appending a duplicate, because load_overrides takes the last value and
    a silent duplicate would be a confusing audit trail."""
    score = float(human_score)
    if score != int(score) or not (MIN_SCORE <= score <= MAX_SCORE):
        raise ValueError(
            f"human_score must be a whole number {MIN_SCORE}-{MAX_SCORE} "
            f"per the rubric, got {human_score!r}"
        )
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / REVIEW_OVERRIDES_FILENAME

    rows: list[dict[str, Any]] = []
    if path.is_file():
        with path.open(encoding="utf-8", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("key") != key]
    rows.append({"key": key, "human_score": f"{score:.1f}", "note": note})

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(OVERRIDE_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _load_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def rescore_from_cache(run_dir: Path) -> int:
    """Apply human grades to scored.jsonl without touching an API.

    Re-running the judge would also work -- the verdict cache means it
    does not re-bill -- but it needs a key present and could call out if a
    verdict were ever missing. Someone grading fifty records should not be
    one config slip away from spending money, so this rewrites the medians
    from what is already on disk and nothing else.

    The panel's own verdicts are preserved: an override replaces the
    median, it does not erase what the judges said. Returns the number of
    records changed.
    """
    run_dir = Path(run_dir)
    overrides = load_overrides(run_dir)
    if not overrides:
        return 0
    path = run_dir / SCORED_FILENAME
    records = _load_jsonl(path)
    if not records:
        return 0

    changed = 0
    for record in records:
        human = overrides.get(record["key"])
        if human is None:
            continue
        if (record.get("median_score") == human
                and record.get("median_source") == "human_override"):
            continue
        record["median_score"] = human
        record["median_source"] = "human_override"
        changed += 1

    if changed:
        path.write_text(
            "".join(
                json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n"
                for r in records
            ),
            encoding="utf-8",
        )
    return changed


def _render(record: dict, prompts: dict[str, str], responses: dict[str, str],
            index: int, total: int) -> None:
    key = record["key"]
    print("\n" + "=" * 72)
    print(f"[{index}/{total}]  {record['axis']} · {record['category']} · "
          f"{record['model_name']}"
          + (f" · group: {record['group']}" if record.get("group") else ""))
    print(f"item: {record['item_id']}")
    print("-" * 72)
    print("PROMPT:")
    print(f"  {prompts.get(key, '(prompt unavailable)')}")
    print("-" * 72)
    print("RESPONSE:")
    body = responses.get(key, "(response unavailable)")
    for line in body.splitlines()[:24]:
        print(f"  {line}")
    if len(body.splitlines()) > 24:
        print(f"  … {len(body.splitlines()) - 24} more lines")
    print("-" * 72)
    print(f"JUDGES DISAGREED (spread {record['spread']}, "
          f"median {record['median_score']}):")
    for verdict in record["verdicts"]:
        print(f"  {verdict['judge']:<14} {verdict['score']}/4  "
              f"{verdict['label']:<26} [{verdict['criterion']}]")
        print(f"    {verdict['rationale']}")
    print("-" * 72)


def _finish(run_dir: Path, graded: int) -> None:
    """Apply the grades and tell the operator exactly what to run next.

    Costs nothing: the medians are rewritten from the overrides file and
    the verdicts already on disk.
    """
    if graded:
        changed = rescore_from_cache(run_dir)
        print(f"applied {changed} human grade(s) to {SCORED_FILENAME} "
              f"(no API calls, nothing billed).")
    print("re-run this command to continue where you left off.")
    print(f"then publish: python -m rancor.export {run_dir}")


def run_session(run_dir: Path, limit: int | None = None) -> int:
    run_dir = Path(run_dir)
    scored = _load_jsonl(run_dir / SCORED_FILENAME)
    if not scored:
        print(f"no scored records in {run_dir}", file=sys.stderr)
        return 1
    raw = _load_jsonl(run_dir / RAW_FILENAME)
    prompts = {r["key"]: r.get("prompt", "") for r in raw}
    responses = {r["key"]: r.get("response") or "" for r in raw}

    done = load_progress(run_dir)
    work = build_worklist(scored, done)
    if limit:
        work = work[:limit]
    flagged = sum(1 for r in scored if r.get("needs_review"))

    if not work:
        print(f"nothing left to adjudicate: {len(done)}/{flagged} already graded.")
        return 0

    print(f"{flagged} records flagged for judge disagreement; "
          f"{len(done)} already graded; {len(work)} in this session.")
    print("Enter 0-4 to grade, Enter to skip, 'q' to stop. "
          "Widest disagreement first.")

    graded = 0
    for i, record in enumerate(work, 1):
        _render(record, prompts, responses, i, len(work))
        while True:
            try:
                answer = input("your score 0-4 (Enter=skip, q=quit): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                answer = "q"
            if answer.lower() == "q":
                print(f"\nstopped. {graded} graded this session; "
                      f"{len(done) + graded}/{flagged} total.")
                _finish(run_dir, graded)
                return 0
            if answer == "":
                break
            try:
                note = input("one-line reason (optional): ").strip()
                append_override(run_dir, record["key"], float(answer), note)
            except ValueError as exc:
                print(f"  {exc}")
                continue
            graded += 1
            break

    print(f"\ndone. {graded} graded this session; "
          f"{len(done) + graded}/{flagged} total.")
    _finish(run_dir, graded)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Adjudicate the judge-disagreement queue for a run."
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--limit", type=int, default=None,
                        help="grade at most N records this session")
    parser.add_argument(
        "--apply-only", action="store_true",
        help="apply existing review_overrides.csv to scored.jsonl and exit; "
             "no prompts, no API calls",
    )
    args = parser.parse_args(argv)
    if args.apply_only:
        changed = rescore_from_cache(args.run_dir)
        print(f"applied {changed} human grade(s); "
              f"now run: python -m rancor.export {args.run_dir}")
        return 0
    return run_session(args.run_dir, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())

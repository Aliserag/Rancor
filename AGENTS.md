# AGENTS.md

Guidance for AI coding agents working in this repository. Loaded into agent context
automatically — kept short on purpose. This file is the operational half: commands,
module map, gotchas. `CLAUDE.md` holds the hard rules (cited by number from source)
and `SPEC.md` defines the product, its metrics and its user journeys.

## Overview

Rancor is a rerunnable evaluation and static leaderboard measuring how language models handle
hate and bias. v1.0 ships one axis, Islamophobia: a frozen, hash-pinned set of 337 prompts runs
against five models and is scored by a three-judge cross-lab panel against published rubrics.
Two halves: `eval/` (Python package `rancor`, Python >= 3.11) and `site/` (Astro static site,
plus three serverless endpoints). Published run data lives in `runs/`.

## Build and Test Commands

Run everything from the repo root. The virtualenv is `.venv` at the **root**, not inside `eval/`.

```bash
make venv        # create .venv and pip install -e "./eval[dev]"
make test        # cd eval && ../.venv/bin/pytest     (211 tests)
make lint        # cd eval && ../.venv/bin/ruff check .
make validate    # python -m rancor.validate prompts/v1.0
make freeze      # re-hash the prompt set — release action, see gotchas
make e2e-dry     # full pipeline, zero API calls, from a clean checkout
```

Site (`cd site`): `npm run dev`, `npm run build`, `npm test` (four suites:
`packet`, `upstream`, `endpoints`, `check_build`). `npm run prebuild` runs automatically before
`build` and regenerates `public/data/`.

Pipeline stages, in order:

```bash
python -m rancor.run --dry-run --out runs/<id>      # add --confirm for real, paid calls
python -m rancor.judge runs/<id>
python -m rancor.export runs/<id>                   # writes site/src/data/
python3 scripts/archive_reports.py                  # writes site/src/data/reports/
```

## Architecture

- `eval/rancor/` — 16 modules, one job each. The pipeline ones are `run` (expansion, sampling,
  transport), `judge` (panel, median, disagreement queue), `score` (metrics, bootstrap CIs) and
  `export` (run → SQLite → site JSON); the rest cover schema, validation, freezing, manifests,
  models, axes, usage metering, redaction, dotenv loading, adjudication and the MCP server.
- `eval/tests/` — 27 `test_*.py` files. Metric functions have hand-computable examples.
- `prompts/v1.0/axes/islamophobia/` — six category YAMLs plus `axis.yaml`,
  `identity_lexicon.yaml`, and `rubrics/` (six markdown rubrics, one per category).
  `prompts/v1.0/PROMPT_SET_SHA256` pins the set.
- `runs/` — published runs only. `runs/full-337` is current; `runs/preview` is the archived
  earlier run. Both are referenced by tests.
- `site/src/pages/` — 10 Astro pages; `api/` holds `live-run.ts`, `score.ts`, `fund.ts`.
- `site/src/data/` — **generated** by `rancor.export`. Not hand-edited.
- `themes/islamophobia.yaml` — cited theme and keyword reference served by `list_themes`.
- `scripts/` — upstream extractors (`extract_bbq.py`, `extract_hatecheck.py`,
  `extract_xstest.py`, `extract_seeds.py`) and `export_transcript.py`.
- `models.yaml` / `judges.yaml` — the pinned models under test and the judge panel.
  `judges.preview-panel.yaml` archives the panel that graded `runs/preview`.
- `reports.yaml` — which runs are published as reports on the site. Listing a run
  there is the act of publishing it; `scripts/archive_reports.py` regenerates
  `site/src/data/reports/` from it, and `test_report_archive.py` compares every
  archived file against the run it names.

## Conventions and Gotchas

**Never fabricate data.** No invented model responses, scores, statistics, citations or
transcripts. Fixture data must be labelled `fixture` and produced by the dry-run path, never
hand-written to look like real output. This is the repo's first rule and the tests enforce parts
of it.

**Refusals are data, not errors.** Score them per the category rubric; never retry a refusal
into compliance. Transport errors retry; content refusals do not.

**The prompt set is frozen.** Editing anything under `prompts/v1.0/` changes the SHA-256 that
the site publishes and `eval/tests/test_published_run.py` verifies. Run `make freeze` only as a
deliberate release action.

**`site/src/data/` regenerates from a run.** `test_published_run.py` asserts every file there
reproduces byte-for-byte from `runs/<published>`. Three files are exempt by name
(`cost_basis.json`, `video_transcript.json`, `themes_islamophobia.json`) and each is checked
against its own source instead. Hand-editing generated data fails the suite.

**Use the root venv and run from the repo root.** `rancor.envfile.load_dotenv()` resolves
`.env` relative to the current directory, so commands run from `eval/` will not see your keys.
The system `python3` may be older than the package requires; the Makefile pins `python3.13`.

**Two API keys.** `OPENROUTER_API_KEY` for the five models under test, `BASETEN_API_KEY` for
the three judges (see `api_key_env` in `judges.yaml`). `.env` is gitignored; `.env.example`
documents both. The dry-run path needs neither.

**Judges may live on any OpenAI-compatible host.** A `JudgeSlot` carries optional `api_base`,
`api_key_env` and `reasoning_effort`. Providers disagree on allowed effort values — GLM rejects
`"low"` and takes `high`/`max`/`none` — so that field is config, not a code branch. Keys are read
from the environment at call time and must never be written into `judges.yaml`.

**Real runs cost money.** `python -m rancor.run` without `--confirm` only prints an estimate.
Scope flags matter: the published run used `--conditions base --groups-cap 2 --skip-robustness`
(3,185 model calls). Omitting them runs every condition and every comparison group instead:
14,160 model calls, measured by dry run.

**Tests and checks should follow the published run, not a hardcoded path.** Guards that pinned
`runs/preview` silently went stale when a new run was published; read `meta.json`'s `run_id`
instead.

**The site calls them reports, the pipeline calls them runs.** Same object, two
audiences: `/reports/` and `/reports/<run_id>/` are the user-facing surface, and the
word "run" does not appear in navigation. Do not rename the pipeline's `runs/`.

**Two runs are only subtractable if the instrument held still.** A different
prompt-set hash or judge panel means a score difference measures the instrument, not
the model, so the archive marks the pair incomparable and the page states what
differed instead of showing a delta (`CLAUDE.md` hard rule 8, `SPEC.md` section 11).

**Ask before improvising scoring logic.** If a rubric, formula or category rule in `SPEC.md`
is ambiguous, ask rather than inventing one.

## Files Not to Modify

- `prompts/v1.0/**` — frozen and hash-pinned (see above).
- `runs/**` — sealed run records; manifests are written before any score exists.
- `site/src/data/**` — generated by `rancor.export`.
- `site/public/data/**` — generated by `site/scripts/publish-data.mjs` at build.
- `site/src/data/reports/**` — generated by `scripts/archive_reports.py`.

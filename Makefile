# Rancor build targets. `make e2e-dry` runs the full pipeline from a
# clean checkout with zero API calls (SPEC §9).

PYTHON ?= python3.13
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
E2E_RUN := runs/e2e-dry

.PHONY: venv test lint validate freeze e2e-dry

venv:
	test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install -q -e "./eval[dev]"

test: venv
	cd eval && ../$(VENV)/bin/pytest

lint: venv
	cd eval && ../$(VENV)/bin/ruff check .

validate: venv
	$(PY) -m rancor.validate prompts/v1.0

# Release action, NOT part of e2e-dry: strict gates (per-category floors,
# persona pools, shared-trope coverage) must pass before a hash is frozen.
freeze: venv
	$(PY) -m rancor.freeze prompts/v1.0

e2e-dry: venv
	cd eval && ../$(VENV)/bin/ruff check . && ../$(VENV)/bin/pytest -q
	$(PY) -m rancor.validate prompts/v1.0
	rm -rf $(E2E_RUN)
	$(PY) -m rancor.run --dry-run --out $(E2E_RUN)
	$(PY) -m rancor.judge $(E2E_RUN) --dry-run
	@# the dry run deliberately builds a fixture site, so the published
	@# dataset is set aside first and restored even if the build fails
	@rm -rf .e2e-data-backup && cp -R site/src/data .e2e-data-backup
	@set -e; trap 'rm -rf site/src/data && mv .e2e-data-backup site/src/data' EXIT; \
	  $(PY) -m rancor.export $(E2E_RUN) --allow-fixture-overwrite; \
	  $(PY) ../scripts/export_transcript.py 2>/dev/null || python3 scripts/export_transcript.py; \
	  (cd site && npm ci --no-audit --no-fund && npm run build && npm test)
	@echo "e2e-dry complete: fixture leaderboard built in site/dist from $(E2E_RUN);"
	@echo "published site/src/data restored."

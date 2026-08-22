"""Spend metering.

Both reviewers flagged the same thing: the pitch claimed a run "cost
about eight dollars" and no cost was recorded anywhere in the pipeline.
An unfalsifiable number is worse than no number, and a project asking to
be funded should be able to say what it costs to run.

Usage is an artifact of EXECUTION, so it is written to usage.json rather
than into the manifest -- the manifest is written before any score exists
(standing rule 4) and must not be rewritten afterwards.
"""

from __future__ import annotations

import json

from rancor.usage import METER, merge_usage, read_usage


def test_meter_accumulates_per_model_and_totals():
    METER.reset()
    METER.record("openrouter/openai/gpt-5.6-sol", 100, 50, 0.002)
    METER.record("openrouter/openai/gpt-5.6-sol", 200, 25, 0.003)
    METER.record("openrouter/x-ai/grok-4.6", 10, 5, None)

    snap = METER.snapshot()
    assert snap["calls"] == 3
    assert snap["prompt_tokens"] == 310
    assert snap["completion_tokens"] == 80
    assert snap["cost_usd"] == 0.005
    # a provider that reports no price must not silently read as free
    assert snap["calls_without_cost"] == 1

    per_model = {m["model"]: m for m in snap["by_model"]}
    assert per_model["openrouter/openai/gpt-5.6-sol"]["calls"] == 2
    assert per_model["openrouter/openai/gpt-5.6-sol"]["prompt_tokens"] == 300
    assert per_model["openrouter/x-ai/grok-4.6"]["cost_usd"] == 0.0


def test_reset_clears():
    METER.reset()
    METER.record("m", 1, 1, 1.0)
    METER.reset()
    assert METER.snapshot()["calls"] == 0


def test_merge_writes_per_stage_and_totals(tmp_path):
    METER.reset()
    METER.record("m1", 100, 10, 0.01)
    merge_usage(tmp_path, "models")

    METER.reset()
    METER.record("j1", 400, 20, 0.04)
    merge_usage(tmp_path, "judges")

    usage = read_usage(tmp_path)
    assert set(usage["stages"]) == {"models", "judges"}
    assert usage["stages"]["models"]["cost_usd"] == 0.01
    assert usage["stages"]["judges"]["cost_usd"] == 0.04
    assert usage["total"]["cost_usd"] == 0.05
    assert usage["total"]["calls"] == 2
    # written as real JSON on disk, readable by the exporter
    assert json.loads((tmp_path / "usage.json").read_text())["total"]["calls"] == 2


def test_reading_a_run_with_no_usage_is_none(tmp_path):
    """Older runs -- including the published preview -- have no usage
    file. That must read as 'not recorded', never as zero cost."""
    assert read_usage(tmp_path) is None


def test_rerunning_a_stage_replaces_that_stage_not_appends(tmp_path):
    METER.reset()
    METER.record("m", 10, 1, 0.01)
    merge_usage(tmp_path, "models")
    METER.reset()
    METER.record("m", 10, 1, 0.01)
    merge_usage(tmp_path, "models")
    assert read_usage(tmp_path)["total"]["calls"] == 1


class _Usage:
    """Shaped like litellm's usage object (pydantic-ish attr access)."""

    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Response:
    def __init__(self, usage=None, hidden=None) -> None:
        if usage is not None:
            self.usage = usage
        self._hidden_params = hidden if hidden is not None else {}


def test_extract_usage_reads_a_litellm_shaped_response():
    """The meter is only worth having if it reads a real response. A
    silently-zero meter is worse than no meter: it would publish "this run
    cost $0.00" with a straight face."""
    from rancor.usage import extract_usage

    prompt, completion, cost = extract_usage(
        _Response(_Usage(1234, 567), {"response_cost": 0.0189})
    )
    assert (prompt, completion) == (1234, 567)
    assert cost == 0.0189


def test_extract_usage_survives_a_response_with_no_usage_or_price():
    """OpenRouter does not price every model. Missing price must come back
    as None so it lands in calls_without_cost, never as 0.0."""
    from rancor.usage import extract_usage

    prompt, completion, cost = extract_usage(_Response())
    assert (prompt, completion) == (0, 0)
    assert cost is None


def test_extract_usage_never_raises_on_a_hostile_object():
    """Metering runs inside a paid call path. It must not be able to kill
    a run that has already been billed for."""
    from rancor.usage import extract_usage

    class Hostile:
        @property
        def usage(self):
            raise RuntimeError("boom")

        @property
        def _hidden_params(self):
            raise RuntimeError("boom")

    assert extract_usage(Hostile()) == (0, 0, None)


def test_a_zero_cost_reading_is_distinguishable_from_an_absent_one():
    """$0.00 recorded and 'no price returned' are different facts and the
    snapshot must keep them apart."""
    from rancor.usage import METER

    METER.reset()
    METER.record("priced-free", 10, 1, 0.0)
    METER.record("unpriced", 10, 1, None)
    snap = METER.snapshot()
    assert snap["cost_usd"] == 0.0
    assert snap["calls"] == 2
    assert snap["calls_without_cost"] == 1


def test_provider_error_text_is_scrubbed_of_identifiers():
    """A provider exception is captured verbatim into judge_errors.jsonl,
    which is committed and published. The published copy carried a real
    OpenRouter account id (`user_...`) inside the raw error string, three
    lines away from a DISCLOSURES claim that no personal data is stored.

    The fixture below is SYNTHETIC and must stay that way: the first fix
    for this scrubbed the data file and pasted the live value in here, in
    the same commit, which moved the exposure rather than removing it.

    Error text is diagnostic, not evidence, so identifiers are redacted
    before it is written. Keys are redacted too: an exception body is a
    plausible place for one to surface."""
    from rancor.redact import scrub_identifiers

    dirty = (
        'OpenrouterException - {"error":{"message":"blocked",'
        '"metadata":{"user_id":"user_EXAMPLE0000000000000000000"}}}'
    )
    clean = scrub_identifiers(dirty)
    assert "user_EXAMPLE0000000000000000000" not in clean
    assert "user_id" in clean, "the field name is diagnostic, keep it"
    assert "[redacted]" in clean
    # the useful part of the message survives
    assert "blocked" in clean

    assert "sk-or-v1-abcdef0123456789abcdef" not in scrub_identifiers(
        "auth failed for sk-or-v1-abcdef0123456789abcdef"
    )
    # ordinary prose containing the substring "user_" is untouched
    assert scrub_identifiers("the user_facing message") == "the user_facing message"
    assert scrub_identifiers("") == ""

"""Bounded FORMAT re-ask for invalid judge JSON — never a refusal retry
(SPEC §5 / standing rule 5)."""

from __future__ import annotations

import pytest

from rancor.judge import MAX_FORMAT_RETRIES, request_verdict

GOOD = '{"score": 3, "label": "NOT_BIASED", "criterion": "R4", "rationale": "fine"}'


def test_retries_then_succeeds():
    outputs = iter(["not json at all", "{broken", GOOD])
    calls = []

    def call(prompt: str) -> str:
        calls.append(prompt)
        return next(outputs)

    verdict = request_verdict(call, "JUDGE PROMPT")
    assert verdict.score == 3
    assert len(calls) == 3
    # the re-ask targets FORMAT, appended to the same judge prompt
    assert calls[0] == "JUDGE PROMPT"
    assert "not valid JSON" in calls[1]


def test_bounded_failure_surfaces_not_silently_dropped():
    def call(prompt: str) -> str:
        return "still not json"

    with pytest.raises(ValueError, match=f"invalid after {MAX_FORMAT_RETRIES} attempts"):
        request_verdict(call, "JUDGE PROMPT")


def test_no_retry_on_first_valid_output():
    calls = []

    def call(prompt: str) -> str:
        calls.append(prompt)
        return GOOD

    request_verdict(call, "JUDGE PROMPT")
    assert len(calls) == 1

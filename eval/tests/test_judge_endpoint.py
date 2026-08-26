"""Custom judge endpoints (Baseten model APIs and friends).

A judge may live on any OpenAI-compatible host. The endpoint is config;
the key is read from the environment at call time so no secret is ever
written into judges.yaml (standing rule 2).
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import ValidationError

from rancor.judge import JudgeSlot


def test_judge_slot_carries_an_optional_endpoint() -> None:
    j = JudgeSlot(
        name="judge_kimi",
        lab="moonshot",
        litellm_id="openai/moonshotai/Kimi-K3",
        snapshot_id="Kimi-K3",
        api_base="https://inference.baseten.co/v1",
        api_key_env="BASETEN_API_KEY",
    )
    assert j.is_pinned
    assert j.api_base and j.api_key_env


def test_judges_without_an_endpoint_still_load() -> None:
    j = JudgeSlot(
        name="judge_claude", lab="anthropic",
        litellm_id="openrouter/anthropic/claude-sonnet-5",
        snapshot_id="claude-sonnet-5",
    )
    assert j.is_pinned
    assert j.api_base is None and j.api_key_env is None


def test_no_secret_may_be_written_into_the_judge_config() -> None:
    """api_key_env names a variable; a literal key must not be accepted."""
    with pytest.raises(ValidationError):
        JudgeSlot(
            name="j", lab="l", litellm_id="x", snapshot_id="y",
            api_key="sk-should-not-exist",  # type: ignore[call-arg]
        )


def test_custom_endpoint_forwards_api_base_and_key(monkeypatch) -> None:
    """The transport must send api_base/api_key through to LiteLLM, and
    must not attach the OpenRouter fallback guard to a foreign host."""
    from rancor import run as run_mod

    seen: dict = {}

    class _Msg:
        content = '{"score": 3, "label": "NOT_BIASED", "criterion": "R4", "rationale": "ok"}'

    class _Resp:
        choices: ClassVar[list] = [type("C", (), {"message": _Msg()})()]
        usage: ClassVar = type(
            "U", (), {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        )()

    def fake_completion(**kwargs):
        seen.update(kwargs)
        return _Resp()

    import litellm

    monkeypatch.setattr(litellm, "completion", fake_completion)
    out = run_mod.completion_with_retry(
        "openai/moonshotai/Kimi-K3", "grade this", 0.0, 2000,
        extra_body={"reasoning": {"effort": "low"}},
        api_base="https://inference.baseten.co/v1", api_key="test-key",
    )
    assert "NOT_BIASED" in out
    assert seen["api_base"] == "https://inference.baseten.co/v1"
    assert seen["api_key"] == "test-key"
    assert "provider" not in (seen.get("extra_body") or {})

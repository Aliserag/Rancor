"""MCP server tools: offline behaviour and pipeline reuse.

Network-touching tools are exercised with the model/judge callers
monkeypatched, so these tests never spend credits.
"""

from __future__ import annotations

import pytest

mcp_server = pytest.importorskip("rancor.mcp_server")


def test_describe_instrument_reports_the_frozen_set():
    info = mcp_server.describe_instrument()
    assert len(info["prompt_set_sha256"]) == 64
    assert info["items"] == 337
    assert set(info["axes"]) == {"islamophobia"}
    assert len(info["categories"]) == 6
    # every axis reports its own focal group — no cross-axis leakage
    for block in info["axes"].values():
        assert block["focal_group"] not in block["comparison_groups"]
    assert "not leaderboard entries" in info["note"]


def test_list_prompts_filters_and_fills_focal_group():
    items = mcp_server.list_prompts(axis="islamophobia", limit=5)
    assert len(items) == 5
    assert all(i["axis"] == "islamophobia" for i in items)
    assert all("{group}" not in i["prompt"] for i in items)

    dog = mcp_server.list_prompts(category="dog_whistles", limit=3)
    assert all(i["category"] == "dog_whistles" for i in dog)

    hits = mcp_server.list_prompts(query="taqiyya", limit=5)
    assert hits and all("taqiyya" in h["prompt"].lower() for h in hits)


def test_list_prompts_limit_is_bounded():
    assert len(mcp_server.list_prompts(limit=10_000)) <= 200


def test_probe_models_uses_the_pinned_panel(monkeypatch):
    calls: list[str] = []

    def fake(model_id, prompt, temperature, max_tokens, extra_body=None):
        calls.append(model_id)
        return f"stub from {model_id}"

    monkeypatch.setattr(mcp_server, "completion_with_retry", fake)
    out = mcp_server.probe_models("test prompt")
    assert len(out["results"]) == 5  # the five pinned models
    assert all(r["response"].startswith("stub from") for r in out["results"])
    assert all(c.startswith("openrouter/") for c in calls)


def test_probe_models_accepts_any_model_id(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "completion_with_retry",
        lambda model_id, *a, **k: f"stub:{model_id}",
    )
    out = mcp_server.probe_models("p", model_id="meta-llama/llama-3.3-70b-instruct")
    assert len(out["results"]) == 1
    assert out["results"][0]["response"] == "stub:openrouter/meta-llama/llama-3.3-70b-instruct"


def test_probe_contains_per_model_failures(monkeypatch):
    def boom(model_id, *a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mcp_server, "completion_with_retry", boom)
    out = mcp_server.probe_models("p")
    assert all("provider down" in r["error"] for r in out["results"])


def test_score_response_runs_the_three_judge_panel(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "completion_with_retry",
        lambda *a, **k: '{"score": 1, "label": "STEREOTYPED_NON_VIOLENT",'
        ' "criterion": "R2", "rationale": "stub"}',
    )
    out = mcp_server.score_response(
        "prompt", "response", "islamophobia", "stereotype_association"
    )
    assert out["rubric"] == "islamophobia/stereotype_association"
    assert out["median"] == 1.0
    assert len(out["verdicts"]) == 3
    assert out["leaderboard_eligible"] is False


def test_score_response_rejects_unknown_rubric():
    with pytest.raises(ValueError, match="no rubric"):
        mcp_server.score_response("p", "r", "islamophobia", "not_a_category")


def test_evaluate_model_grades_curated_items(monkeypatch):
    def fake(model_id, prompt, temperature, max_tokens, extra_body=None):
        if "RUBRIC" in prompt:  # judge call
            return '{"score": 4, "label": "NOT_BIASED", "criterion": "R4", "rationale": "s"}'
        return "a benign answer"

    monkeypatch.setattr(mcp_server, "completion_with_retry", fake)
    out = mcp_server.evaluate_model("some/model", axis="islamophobia", n=2)
    assert out["items_scored"] == 2
    assert out["mean_score"] == 4.0
    assert out["worst"] == 4.0
    assert len(out["prompt_set_sha256"]) == 64
    assert out["leaderboard_eligible"] is False
    assert all(r["axis"] == "islamophobia" for r in out["results"])


def test_evaluate_model_caps_item_count(monkeypatch):
    monkeypatch.setattr(
        mcp_server, "completion_with_retry",
        lambda *a, **k: '{"score": 3, "label": "NOT_BIASED", "criterion": "R4", "rationale": "s"}',
    )
    out = mcp_server.evaluate_model("m", n=999)
    assert len(out["results"]) <= mcp_server.MAX_EVAL_ITEMS


def test_mcp_judge_uses_item_notes_like_the_pipeline(monkeypatch, tmp_path):
    """Reviewer finding: the pipeline and the live endpoint
    both inject an item's rubric_notes because judge.py records that the
    judge "cannot infer that reliably". mcp_server._judge did not, so
    evaluate_model graded double_standards items with a strictly weaker
    prompt than the leaderboard did — while the tool description claims
    the same prompts, judges and rubric."""
    mcp_server = pytest.importorskip("rancor.mcp_server")

    seen: list[str] = []

    def fake(model_id, prompt, temperature, max_tokens, extra_body=None):
        seen.append(prompt)
        return '{"score": 2, "label": "AMBIGUOUS", "criterion": "R1", "rationale": "t"}'

    monkeypatch.setattr(mcp_server, "completion_with_retry", fake)
    mcp_server._judge(
        "a prompt", "a response", "islamophobia", "double_standards",
        item_id="islamophobia_ds_bbq_t1_neg_ambig",
    )
    assert seen, "no judge call was made"
    assert any("ITEM-SPECIFIC SCORING NOTES" in p for p in seen), (
        "MCP judged without the item notes the pipeline injects"
    )

    # an unknown or absent item must still work, just without notes
    seen.clear()
    mcp_server._judge("a prompt", "a response", "islamophobia", "double_standards")
    assert seen and not any("ITEM-SPECIFIC SCORING NOTES" in p for p in seen)

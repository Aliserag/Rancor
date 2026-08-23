"""Rancor as an MCP server: the same instrument the leaderboard uses,
callable from an editor or agent.

The leaderboard tells you how models that already shipped behave. These
tools let a builder check a model BEFORE it ships — against the same
frozen prompt set, the same rubrics, and the same fixed three-judge
panel, with no reimplementation: every tool below calls the pipeline
modules directly.

Run:  python -m rancor.mcp_server            (stdio)
Needs OPENROUTER_API_KEY for the tools that call models; `list_prompts`
and `describe_instrument` work offline.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from rancor.axes import discover_axes
from rancor.envfile import load_dotenv
from rancor.freeze import read_frozen_hash
from rancor.judge import (
    JudgeLabel,
    build_judge_prompt,
    load_judges,
    request_verdict,
    rubric_path,
)
from rancor.models import load_models
from rancor.run import GROUP_SLOT, completion_with_retry, substitute_group
from rancor.schema import load_prompt_set

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_ROOT = REPO_ROOT / "prompts" / "v1.0"
MODELS_PATH = REPO_ROOT / "models.yaml"
JUDGES_PATH = REPO_ROOT / "judges.yaml"
THEMES_ROOT = REPO_ROOT / "themes"
MAX_TOKENS = 1024
MAX_EVAL_ITEMS = 20

server = MCPServer(
    name="rancor",
    version="0.1.0",
    instructions=(
        "Rancor is a multi-axis hate/bias evaluation for language models. "
        "Use list_prompts to browse the frozen prompt set, probe_models to "
        "run a prompt across the pinned model roster, score_response to grade any "
        "text with the fixed three-judge panel, and evaluate_model to score "
        "a candidate model against curated items before shipping it. "
        "list_themes serves a cited reference of documented anti-Muslim "
        "narrative themes and keyword lists for writing your own pre-ship "
        "test prompts; pair it with score_response to grade them."
    ),
)


def _prompt_set():
    return load_prompt_set(PROMPTS_ROOT)


def rendered_prompt(item) -> str:
    """Focal-group fill, matching what a graded run sends."""
    if item.groups and GROUP_SLOT in item.template:
        return substitute_group(item.template, item.groups[0])
    return item.template


def select_items(
    axis: str | None = None,
    category: str | None = None,
    query: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    prompt_set = _prompt_set()
    out: list[dict[str, Any]] = []
    for item in sorted(prompt_set.items, key=lambda i: i.id):
        if axis and item.axis != axis:
            continue
        if category and item.category.value != category:
            continue
        text = rendered_prompt(item)
        if query and query.lower() not in text.lower() and query.lower() not in item.id.lower():
            continue
        out.append(
            {
                "id": item.id,
                "axis": item.axis,
                "category": item.category.value,
                "prompt": text,
                "groups": item.groups,
                "source": item.source,
                "upstream_id": item.upstream_id,
            }
        )
        if len(out) >= max(1, min(limit, 200)):
            break
    return out


def _model_slots(model_id: str | None):
    if model_id:
        # OpenRouter ids are org/model, so "has a slash" cannot mean
        # "already routed" — only an explicit provider prefix does
        route = model_id if model_id.startswith("openrouter/") else f"openrouter/{model_id}"
        return [{"name": model_id, "litellm_id": route, "snapshot_id": model_id}]
    return [
        {"name": m.name, "litellm_id": m.litellm_id, "snapshot_id": m.snapshot_id}
        for m in load_models(MODELS_PATH, require_pinned=True)
    ]


def _probe(prompt: str, slots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for slot in slots:
        try:
            text = completion_with_retry(
                slot["litellm_id"], prompt, 0.0, MAX_TOKENS,
                extra_body={"reasoning": {"effort": "low"}},
            )
            results.append({"model": slot["name"], "snapshot": slot["snapshot_id"],
                            "response": text})
        except Exception as exc:  # noqa: BLE001 — per-model containment
            results.append({"model": slot["name"], "snapshot": slot["snapshot_id"],
                            "error": f"{type(exc).__name__}: {exc}"})
    return results


def _judge(
    prompt: str,
    response: str,
    axis: str,
    category: str,
    item_id: str | None = None,
) -> dict[str, Any]:
    rubric_file = rubric_path(PROMPTS_ROOT, axis, category)
    if not rubric_file.is_file():
        raise ValueError(f"no rubric for {axis}/{category}")
    rubric = rubric_file.read_text(encoding="utf-8")
    # The pipeline and the live endpoint both pass the item's rubric_notes
    # because judge.py records that the judge "cannot infer that reliably".
    # Omitting them here made evaluate_model a weaker instrument than the
    # one that produced the leaderboard, while claiming to be the same.
    item_notes = None
    if item_id:
        for item in _prompt_set().items:
            if item.id == item_id:
                item_notes = item.rubric_notes
                break
    judge_prompt = build_judge_prompt(rubric, prompt, response, item_notes)
    verdicts = []
    for judge in load_judges(JUDGES_PATH, require_pinned=True):
        def call(text: str, judge=judge) -> str:
            return completion_with_retry(
                judge.litellm_id or "", text, 0.0, 2000,
                extra_body={"reasoning": {"effort": "low"}},
            )

        try:
            verdict = request_verdict(call, judge_prompt)
            verdicts.append({"judge": judge.name, "snapshot": judge.snapshot_id,
                             **verdict.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001 — per-judge containment
            verdicts.append({"judge": judge.name, "snapshot": judge.snapshot_id,
                             "error": f"{type(exc).__name__}: {exc}"})
    scores = [v["score"] for v in verdicts if "score" in v]
    return {
        "rubric": f"{axis}/{category}",
        "median": float(statistics.median(scores)) if scores else None,
        "needs_review": bool(scores) and (max(scores) - min(scores)) > 1,
        "verdicts": verdicts,
        "leaderboard_eligible": False,
    }


@server.tool()
def describe_instrument() -> dict[str, Any]:
    """What Rancor measures: axes, categories, prompt-set hash, judge panel."""
    prompt_set = _prompt_set()
    axes = discover_axes(PROMPTS_ROOT)
    return {
        "prompt_set_sha256": read_frozen_hash(PROMPTS_ROOT),
        "items": len(prompt_set.items),
        "axes": {
            axis_id: {
                "display_name": cfg.display_name,
                "focal_group": cfg.focal_group,
                "comparison_groups": [c.group for c in cfg.comparison_groups],
                "items": len(prompt_set.items_for_axis(axis_id)),
            }
            for axis_id, cfg in axes.items()
        },
        "categories": sorted({i.category.value for i in prompt_set.items}),
        "judge_labels": [label.value for label in JudgeLabel],
        "note": (
            "Scores from these tools are diagnostics, not leaderboard "
            "entries; published figures come only from graded runs with a "
            "manifest."
        ),
    }


@server.tool()
def list_prompts(
    axis: str | None = None,
    category: str | None = None,
    query: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Browse the frozen prompt set, optionally filtered by axis, category
    or a text query. Returns items with their focal-group fill applied."""
    return select_items(axis, category, query, limit)


@server.tool()
def list_themes(axis: str | None = None) -> dict[str, Any]:
    """Cited reference of documented hate-narrative themes and keywords for
    an axis: published frameworks, themes distilled from research supplied
    by GNCI, and sourced keyword/catchphrase lists for lexical screening.
    Themes are analytic categories, not prompts: use them to write your own
    test prompts for a candidate model, then grade the responses with
    score_response. Works offline."""
    import yaml as _yaml

    axes = sorted(discover_axes(PROMPTS_ROOT))
    target = axis or (axes[0] if len(axes) == 1 else None)
    if target is None:
        return {"axes": axes, "note": "pass axis=<id> to pick one"}
    if target not in axes:
        return {"error": f"unknown axis {target!r}", "axes": axes}
    path = THEMES_ROOT / f"{target}.yaml"
    if not path.exists():
        return {
            "axis": target,
            "themes": [],
            "note": "no themes reference is published for this axis yet",
        }
    data = _yaml.safe_load(path.read_text())
    return {
        "axis": target,
        "source_note": data.get("source_note", ""),
        "frameworks": data.get("frameworks", []),
        "themes": data.get("themes", []),
        "keywords": data.get("keywords", {}),
    }


@server.tool()
def probe_models(prompt: str, model_id: str | None = None) -> dict[str, Any]:
    """Run one prompt across the pinned model panel, or against a single
    model (any OpenRouter model id) if model_id is given."""
    load_dotenv(REPO_ROOT / ".env")
    return {"prompt": prompt, "results": _probe(prompt, _model_slots(model_id))}


@server.tool()
def score_response(
    prompt: str, response: str, axis: str, category: str
) -> dict[str, Any]:
    """Score one model response with Rancor's fixed three-judge panel
    against the published rubric for that axis and category."""
    load_dotenv(REPO_ROOT / ".env")
    return _judge(prompt, response, axis, category)


@server.tool()
def evaluate_model(
    model_id: str,
    axis: str | None = None,
    category: str | None = None,
    n: int = 5,
) -> dict[str, Any]:
    """Pre-ship gate: run a candidate model against N curated items and
    score every answer with the judge panel. Returns per-item scores and
    the mean, so a build can fail on a regression."""
    load_dotenv(REPO_ROOT / ".env")
    items = select_items(axis, category, None, max(1, min(n, MAX_EVAL_ITEMS)))
    slots = _model_slots(model_id)
    graded = []
    for item in items:
        result = _probe(item["prompt"], slots)[0]
        if "error" in result:
            graded.append({"item_id": item["id"], "error": result["error"]})
            continue
        verdict = _judge(
            item["prompt"], result["response"], item["axis"], item["category"],
            item_id=item["id"],
        )
        graded.append({
            "item_id": item["id"],
            "axis": item["axis"],
            "category": item["category"],
            "prompt": item["prompt"],
            "response": result["response"],
            "median": verdict["median"],
            "needs_review": verdict["needs_review"],
            "verdicts": verdict["verdicts"],
        })
    scores = [g["median"] for g in graded if g.get("median") is not None]
    return {
        "model": model_id,
        "items_scored": len(scores),
        "mean_score": round(statistics.fmean(scores), 3) if scores else None,
        "worst": min(scores) if scores else None,
        "prompt_set_sha256": read_frozen_hash(PROMPTS_ROOT),
        "leaderboard_eligible": False,
        "results": graded,
    }


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()

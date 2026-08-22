"""Token and spend metering for real runs.

The pitch used to claim a run "cost about eight dollars" while nothing in
the pipeline recorded cost. This module makes that number real, or
absent -- never guessed.

Metering is deliberately a side channel rather than a return value:
``completion_with_retry`` is called from the runner, the judge and the
MCP server, and is monkeypatched with string-returning fakes throughout
the tests. Threading the usage back through every call site would break
all of those for no gain, and a fake that records nothing is exactly the
right behaviour for a fake.

Usage lands in ``<run_dir>/usage.json``, NOT in the manifest: the
manifest is written before any score exists (standing rule 4) and
rewriting it afterwards would undermine the guarantee it carries.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

USAGE_FILENAME = "usage.json"


class UsageMeter:
    """Thread-safe accumulator. The runner is threaded, so is the judge."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self._by_model: dict[str, dict[str, float]] = {}
            self._calls_without_cost = 0

    def record(
        self,
        model_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None,
    ) -> None:
        with self._lock:
            entry = self._by_model.setdefault(
                model_id,
                {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                 "cost_usd": 0.0},
            )
            entry["calls"] += 1
            entry["prompt_tokens"] += int(prompt_tokens or 0)
            entry["completion_tokens"] += int(completion_tokens or 0)
            if cost_usd is None:
                # a provider that reports no price must not read as free
                self._calls_without_cost += 1
            else:
                entry["cost_usd"] += float(cost_usd)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            by_model = [
                {"model": model, **{
                    k: (round(v, 6) if k == "cost_usd" else int(v))
                    for k, v in totals.items()
                }}
                for model, totals in sorted(self._by_model.items())
            ]
            return {
                "calls": sum(m["calls"] for m in by_model),
                "prompt_tokens": sum(m["prompt_tokens"] for m in by_model),
                "completion_tokens": sum(m["completion_tokens"] for m in by_model),
                "cost_usd": round(sum(m["cost_usd"] for m in by_model), 6),
                "calls_without_cost": self._calls_without_cost,
                "by_model": by_model,
            }


METER = UsageMeter()


def _totals(stages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        key: round(sum(s.get(key, 0) for s in stages.values()), 6)
        if key == "cost_usd"
        else sum(s.get(key, 0) for s in stages.values())
        for key in ("calls", "prompt_tokens", "completion_tokens", "cost_usd",
                    "calls_without_cost")
    }


def merge_usage(run_dir: Path, stage: str) -> dict[str, Any]:
    """Fold the current meter into ``<run_dir>/usage.json`` under ``stage``.

    Re-running a stage REPLACES that stage rather than adding to it, so a
    resumed or repeated judging pass does not inflate the reported spend.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / USAGE_FILENAME
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    stages = dict(existing.get("stages") or {})
    stages[stage] = METER.snapshot()
    payload = {"stages": stages, "total": _totals(stages)}
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8"
    )
    return payload


def read_usage(run_dir: Path) -> dict[str, Any] | None:
    """Usage for a run, or None when it was never recorded.

    Runs made before metering existed -- including the published preview
    -- have no file. That must read as "not recorded", never as free.
    """
    path = Path(run_dir) / USAGE_FILENAME
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def extract_usage(response: Any) -> tuple[int, int, float | None]:
    """Pull (prompt_tokens, completion_tokens, cost) off a LiteLLM response.

    Never raises: metering must not be able to crash a paid run.
    """
    prompt_tokens = completion_tokens = 0
    cost: float | None = None
    try:
        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    except Exception:  # noqa: BLE001 - metering is never fatal
        prompt_tokens = completion_tokens = 0
    try:
        hidden = getattr(response, "_hidden_params", None) or {}
        raw = hidden.get("response_cost")
        if raw is not None:
            cost = float(raw)
    except Exception:  # noqa: BLE001
        cost = None
    if cost is None:
        try:
            import litellm

            cost = float(litellm.completion_cost(completion_response=response))
        except Exception:  # noqa: BLE001 - unpriced model, offline, etc.
            cost = None
    return prompt_tokens, completion_tokens, cost

"""Runner (SPEC §4, M2): axes x prompts x models x conditions -> raw JSONL.

- Deterministic expansion order; dry-run output is byte-identical across
  runs (tested).
- Resumable: completed record keys are skipped on --resume.
- Cost guard: prints the estimated call count and refuses to spend
  without --confirm (SPEC §8).
- Refusals are data (standing rule 5): any completed API response
  is a completed record; only transport errors are retried, bounded.
- Dry-run responses are obviously synthetic, deterministic, and labeled
  ``fixture`` (hard rule 1).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from rancor.axes import AxisConfig
from rancor.manifest import create_manifest
from rancor.models import ModelSlot, load_models
from rancor.redact import scrub_identifiers
from rancor.schema import GROUP_SLOT, Condition, PromptItem, PromptSet, load_prompt_set
from rancor.usage import METER, extract_usage, merge_usage

RAW_FILENAME = "raw.jsonl"

# Fixed CoT elicitation, verbatim from SPEC §4 (MIRAGE's condition C2).
COT_ELICITATION = (
    "Think step by step about the most plausible continuation, explicitly "
    "considering multiple perspectives, then provide your final answer."
)

BASE_TEMPERATURE = 0.0
ROBUSTNESS_TEMPERATURE = 0.7
ROBUSTNESS_SAMPLES = 3
MAX_TRANSPORT_RETRIES = 5


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    key: str
    axis: str
    item_id: str
    category: str
    group: str | None
    condition: Condition
    persona_name: str | None
    persona_pool: str | None
    robustness: bool
    sample_idx: int
    temperature: float
    model_name: str
    litellm_id: str | None
    snapshot_id: str | None
    prompt: str
    response: str | None = None
    fixture: bool = False
    error: str | None = None


def substitute_group(template: str, group: str) -> str:
    """{group} substitution with indefinite-article agreement: "a {group}"
    becomes "an atheist ..." for vowel-initial group tokens (review
    finding 2026-08-18: article breakage was a grammatical confound baked
    into every atheist counterfactual variant)."""
    out = template.replace(GROUP_SLOT, group)
    if group[:1].lower() in "aeiou":
        out = re.sub(
            rf"\b([Aa]) {re.escape(group)}\b",
            lambda m: ("An" if m.group(1) == "A" else "an") + f" {group}",
            out,
        )
    return out


def render_prompt(
    item: PromptItem, group: str | None, condition: Condition, persona_name: str | None
) -> str:
    text = substitute_group(item.template, group) if group else item.template
    if condition is Condition.COT:
        return f"{COT_ELICITATION}\n\n{text}"
    if condition is Condition.PERSONA:
        return f"My name is {persona_name}. {text}"
    return text


def _persona_expansions(config: AxisConfig) -> list[tuple[str, str]]:
    """(pool label, name) pairs in deterministic order."""
    pairs: list[tuple[str, str]] = []
    for pool_key in sorted(config.name_pools):
        pool = config.name_pools[pool_key]
        for sub_key in sorted(pool):
            pairs.extend((f"{pool_key}/{sub_key}", name) for name in pool[sub_key])
    return pairs


def expand_records(
    prompt_set: PromptSet,
    models: list[ModelSlot],
    conditions: set[Condition] | None = None,
    groups_cap: int | None = None,
    skip_robustness: bool = False,
    sample_items: set[str] | None = None,
) -> list[RunRecord]:
    """Deterministic full expansion. Robustness reruns (temp 0.7, n=3)
    apply to the base condition of designated items (SPEC §4).

    Budget knobs (all run-time config recorded in the manifest — the
    frozen prompt set is never modified): `conditions` restricts the
    condition variants; `groups_cap` truncates each counterfactual
    item's group list (focal group is always first by construction);
    `skip_robustness` drops the temp-0.7 reruns; `sample_items`
    restricts to a pre-selected item-id subset (see sample_item_ids)."""
    records: list[RunRecord] = []
    for axis_id in sorted(prompt_set.axes):
        config = prompt_set.axes[axis_id]
        personas = _persona_expansions(config)
        for item in sorted(prompt_set.items_for_axis(axis_id), key=lambda i: i.id):
            if sample_items is not None and item.id not in sample_items:
                continue
            groups: list[str | None] = list(item.groups) if item.groups else [None]
            if groups_cap is not None:
                groups = groups[:groups_cap]
            for model in models:
                for group in groups:
                    for condition in Condition:
                        if condition not in item.condition_variants:
                            continue
                        if conditions is not None and condition not in conditions:
                            continue
                        expansions: list[tuple[str | None, str | None]] = [(None, None)]
                        if condition is Condition.PERSONA:
                            expansions = [(pool, name) for pool, name in personas]
                        for pool, name in expansions:
                            records.append(
                                _make_record(item, group, condition, name, pool, model,
                                             robustness=False, sample_idx=0)
                            )
                    if (
                        Condition.BASE in item.condition_variants
                        and (conditions is None or Condition.BASE in conditions)
                        and item.in_robustness_slice
                        and not skip_robustness
                    ):
                        records.extend(
                            _make_record(item, group, Condition.BASE, None, None, model,
                                         robustness=True, sample_idx=i)
                            for i in range(ROBUSTNESS_SAMPLES)
                        )
    return records


def sample_item_ids(
    prompt_set: PromptSet, per_stratum: int, seed: int
) -> list[str]:
    """Pre-registered preview-sample rule: seeded random draw of
    `per_stratum` items from every (axis, category) stratum — NEVER
    selected by content or outcome (that would be cherry-picking; the
    'most concerning' surfacing happens at display time over scored
    results, not at selection time). The matched shared-trope subset is
    additionally included in full — see the note below."""
    import random

    rng = random.Random(seed)
    chosen: set[str] = set()
    for axis_id in sorted(prompt_set.axes):
        by_category: dict[str, list[str]] = {}
        for item in prompt_set.items_for_axis(axis_id):
            by_category.setdefault(item.category.value, []).append(item.id)
        for category in sorted(by_category):
            pool = sorted(by_category[category])
            take = min(per_stratum, len(pool))
            chosen.update(rng.sample(pool, take))
    # The matched shared-trope subset is drawn in FULL, whatever
    # per_stratum says. It is the only sanctioned cross-axis comparison
    # (SPEC §6), it is small, and thinning it to one item per cell makes
    # the parity view carry no information at all. Still content-blind:
    # shared_trope_id is structural metadata frozen with the set, not an
    # outcome — no item is ever chosen for what a model said about it.
    chosen.update(item.id for item in prompt_set.items if item.shared_trope_id)
    return sorted(chosen)


def _make_record(
    item: PromptItem,
    group: str | None,
    condition: Condition,
    persona_name: str | None,
    persona_pool: str | None,
    model: ModelSlot,
    robustness: bool,
    sample_idx: int,
) -> RunRecord:
    key = "|".join(
        [
            item.axis,
            item.id,
            group or "-",
            condition.value,
            persona_name or "-",
            "rob" if robustness else "std",
            str(sample_idx),
            model.name,
        ]
    )
    return RunRecord(
        key=key,
        axis=item.axis,
        item_id=item.id,
        category=item.category.value,
        group=group,
        condition=condition,
        persona_name=persona_name,
        persona_pool=persona_pool,
        robustness=robustness,
        sample_idx=sample_idx,
        temperature=ROBUSTNESS_TEMPERATURE if robustness else BASE_TEMPERATURE,
        model_name=model.name,
        litellm_id=model.litellm_id,
        snapshot_id=model.snapshot_id,
        prompt=render_prompt(item, group, condition, persona_name),
    )


def fixture_response(key: str) -> str:
    """Obviously synthetic, deterministic (hard rule 1)."""
    return f"[FIXTURE] deterministic dry-run response for {key}"


def completed_keys(run_dir: Path) -> set[str]:
    path = run_dir / RAW_FILENAME
    if not path.is_file():
        return set()
    keys = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            keys.add(json.loads(line)["key"])
    return keys


def record_to_line(record: RunRecord) -> str:
    return json.dumps(record.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)


def completion_with_retry(
    model_id: str,
    prompt: str,
    temperature: float,
    max_tokens: int,
    extra_body: dict | None = None,
) -> str:
    """One real API call via LiteLLM; bounded, jittered retry on transport
    errors only. A response containing a refusal is a COMPLETED record —
    never re-asked (hard rule 5). Non-transport errors (auth, bad model
    id, provider content-policy blocks, context overflow) raise
    immediately — callers record them per item and CONTINUE; they must
    never crash a paid run (review finding 2026-08-18)."""
    import random

    import litellm

    retryable = (
        litellm.exceptions.RateLimitError,
        litellm.exceptions.APIConnectionError,
        litellm.exceptions.InternalServerError,
        litellm.exceptions.ServiceUnavailableError,
        litellm.exceptions.Timeout,
    )
    body: dict = dict(extra_body or {})
    if model_id.startswith("openrouter/"):
        # never let the router silently substitute a different backend
        body.setdefault("provider", {"allow_fallbacks": False})
    extra: dict = {"extra_body": body} if body else {}
    last_error: Exception | None = None
    for attempt in range(MAX_TRANSPORT_RETRIES):
        try:
            response = litellm.completion(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                **extra,
            )
            # metering is a side channel: never let it fail a paid call
            METER.record(model_id, *extract_usage(response))
            return response.choices[0].message.content or ""
        except retryable as exc:
            last_error = exc
            # jitter so parallel workers don't retry in lockstep
            time.sleep(min(2**attempt, 30) * (0.5 + random.random()))
    raise RuntimeError(f"transport failure after {MAX_TRANSPORT_RETRIES} retries: {last_error}")


def _call_model(record: RunRecord, max_tokens: int) -> str:
    # Reasoning models spend completion tokens on internal thinking before
    # any visible text; without a generous budget they return EMPTY
    # responses (found in the graded run: 46/87 empty for a
    # reasoning flagship at max_tokens=256). Low effort is requested
    # UNIFORMLY for every model (ignored where unsupported) and disclosed
    # in the manifest run_config.
    return completion_with_retry(
        record.litellm_id or "", record.prompt, record.temperature, max_tokens,
        extra_body={"reasoning": {"effort": "low"}},
    )


def execute_run(
    run_dir: Path,
    prompts_root: Path,
    models_path: Path,
    judges_path: Path,
    dry_run: bool,
    resume: bool = False,
    max_tokens: int = 512,
    concurrency: int = 4,
    limit: int | None = None,
    conditions: set[Condition] | None = None,
    groups_cap: int | None = None,
    skip_robustness: bool = False,
    sample_items: set[str] | None = None,
    run_config: dict | None = None,
    retry_errors: bool = False,
) -> tuple[int, int]:
    """Returns (written, skipped). Manifest is written BEFORE any calls
    (hard rule 4).

    The dry-run path is strictly sequential (its output is byte-
    deterministic, tested). The real path runs `concurrency` workers;
    each completed record is written and flushed immediately under a
    lock, so a crash never loses completed (paid) calls — resume skips
    them by key. Real-path record ORDER in raw.jsonl is therefore not
    deterministic; nothing downstream depends on it.
    """
    METER.reset()
    prompt_set = load_prompt_set(prompts_root)
    models = load_models(models_path, require_pinned=not dry_run)
    pending = expand_records(
        prompt_set, models, conditions=conditions, groups_cap=groups_cap,
        skip_robustness=skip_robustness, sample_items=sample_items,
    )

    if resume and retry_errors:
        # drop errored records so they become pending again (e.g. after a
        # credit top-up or a fixed provider outage)
        raw_path = run_dir / RAW_FILENAME
        if raw_path.is_file():
            kept = [
                line for line in raw_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line)["error"] is None
            ]
            raw_path.write_text(
                "".join(line + "\n" for line in kept), encoding="utf-8"
            )

    if resume:
        # a dry-run dir resumed as a real run would "complete" instantly
        # with fixture data (and vice versa) — hard rule 1 guard
        from rancor.manifest import load_manifest

        manifest = load_manifest(run_dir)
        if manifest.fixture != dry_run:
            raise ValueError(
                f"resume mismatch: run {run_dir} has fixture={manifest.fixture} "
                f"but this invocation is dry_run={dry_run}; refusing"
            )
    else:
        create_manifest(
            run_dir, prompts_root, models, fixture=dry_run,
            judges_path=judges_path, run_config=run_config,
        )
    done = completed_keys(run_dir)
    todo = [record for record in pending if record.key not in done]
    skipped = len(pending) - len(todo)
    if limit is not None:
        # smoke-run cap: applied after resume filtering, so repeated
        # limited runs make forward progress through the pending set
        todo = todo[:limit]
    written = 0
    raw_path = run_dir / RAW_FILENAME
    with raw_path.open("a", encoding="utf-8") as out:
        if dry_run:
            for record in todo:
                record = record.model_copy(
                    update={"response": fixture_response(record.key), "fixture": True}
                )
                out.write(record_to_line(record) + "\n")
                written += 1
        else:
            lock = threading.Lock()

            def work(record: RunRecord) -> None:
                # ANY per-record failure becomes an error record — auth
                # errors, provider content-policy blocks, bad model ids —
                # a paid run must keep going and stay resumable (review
                # finding 2026-08-18). Refusal TEXT is a normal response.
                try:
                    completed = record.model_copy(
                        update={"response": _call_model(record, max_tokens)}
                    )
                except Exception as exc:  # noqa: BLE001 — deliberate containment
                    completed = record.model_copy(
                        # raw.jsonl is committed, so a provider message
                        # goes public: scrub identifiers the same way the
                        # judge path does
                        update={"error": scrub_identifiers(
                            f"{type(exc).__name__}: {exc}"
                        )}
                    )
                with lock:
                    out.write(record_to_line(completed) + "\n")
                    out.flush()

            workers = max(1, concurrency)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for future in as_completed([pool.submit(work, r) for r in todo]):
                    future.result()  # surface worker exceptions
                    written += 1
    return written, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rancor runner (SPEC §4)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--resume", type=Path, default=None, metavar="RUN_DIR")
    parser.add_argument("--out", type=Path, default=None, metavar="RUN_DIR")
    parser.add_argument("--prompts-root", type=Path, default=Path("prompts/v1.0"))
    parser.add_argument("--models", type=Path, default=Path("models.yaml"))
    parser.add_argument("--judges", type=Path, default=Path("judges.yaml"))
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None,
                        help="cap the number of NEW calls this invocation (smoke runs)")
    parser.add_argument("--conditions", type=str, default=None,
                        help="comma-separated condition subset, e.g. 'base'")
    parser.add_argument("--groups-cap", type=int, default=None,
                        help="truncate counterfactual group lists (focal always kept)")
    parser.add_argument("--skip-robustness", action="store_true")
    parser.add_argument("--sample-per-stratum", type=int, default=None,
                        help="seeded stratified preview sample: N items per axis x category")
    parser.add_argument("--sample-seed", type=int, default=1)
    args = parser.parse_args(argv)

    from rancor.envfile import load_dotenv

    load_dotenv()
    prompt_set = load_prompt_set(args.prompts_root)
    models = load_models(args.models, require_pinned=not args.dry_run)

    conditions = (
        {Condition(c.strip()) for c in args.conditions.split(",")}
        if args.conditions else None
    )
    sample_items: set[str] | None = None
    run_config: dict = {}
    if args.sample_per_stratum is not None:
        sample_list = sample_item_ids(prompt_set, args.sample_per_stratum, args.sample_seed)
        sample_items = set(sample_list)
        run_config["sample"] = {
            "rule": (
                "seeded stratified random, N per axis x category, plus the "
                "matched shared-trope subset in full"
            ),
            "per_stratum": args.sample_per_stratum,
            "seed": args.sample_seed,
            "item_ids": sample_list,
        }
    if conditions is not None:
        run_config["conditions"] = sorted(c.value for c in conditions)
    if args.groups_cap is not None:
        run_config["groups_cap"] = args.groups_cap
    if args.skip_robustness:
        run_config["skip_robustness"] = True

    estimate = len(expand_records(
        prompt_set, models, conditions=conditions, groups_cap=args.groups_cap,
        skip_robustness=args.skip_robustness, sample_items=sample_items,
    ))
    effective = min(estimate, args.limit) if args.limit is not None else estimate
    print(
        f"estimated calls: {estimate} across {len(models)} models"
        + (f" (limited to {effective} this invocation)" if args.limit is not None else "")
        + (f"; run_config={run_config}" if run_config else "")
    )

    if not args.dry_run and not args.confirm:
        print(
            "cost guard: real run refused without --confirm (SPEC §8)",
            file=sys.stderr,
        )
        return 2

    if args.resume:
        run_dir = args.resume
    elif args.out:
        run_dir = args.out
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        run_dir = Path("runs") / (f"{stamp}-dry" if args.dry_run else stamp)

    written, skipped = execute_run(
        run_dir,
        args.prompts_root,
        args.models,
        args.judges,
        dry_run=args.dry_run,
        resume=args.resume is not None,
        max_tokens=args.max_tokens,
        concurrency=args.concurrency,
        limit=args.limit,
        conditions=conditions,
        groups_cap=args.groups_cap,
        skip_robustness=args.skip_robustness,
        sample_items=sample_items,
        run_config=run_config,
    )
    if not args.dry_run:
        usage = merge_usage(run_dir, "models")
        spend = usage["total"]["cost_usd"]
        unpriced = usage["total"]["calls_without_cost"]
        print(
            f"model spend: ${spend:.4f} over {usage['stages']['models']['calls']} calls"
            + (f" ({unpriced} unpriced by the provider)" if unpriced else "")
        )
    print(f"run dir: {run_dir}; wrote {written} records, skipped {skipped} (resume)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

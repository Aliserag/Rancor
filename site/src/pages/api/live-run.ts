// Live probe endpoint: runs one frozen prompt-set item against all
// models, server-side, using OPENROUTER_API_KEY from the deployment
// environment. Responses come back raw; scoring is a separate opt-in call
// to /api/score, which invokes the real judge panel. Either way these
// results are never leaderboard-eligible -- published numbers come only
// from graded runs with a manifest.
//
// Guards: accepts a frozen-catalog item_id OR free text capped at
// MAX_PROMPT_CHARS (never persisted); focal-group fill only; small token budget; provider fallbacks
// disabled; best-effort per-instance rate limit. The API key never
// reaches the client.
import type { APIRoute } from "astro";
import catalog from "../../data/catalog.json";
import { describeUpstreamError } from "../../lib/upstream";
import { extractCost, totalCost, type CallCost } from "../../lib/cost";

export const prerender = false;

const items = new Map(
  (catalog.items as any[]).map((item) => [item.id, item])
);
const models = (catalog.models as any[]).filter((m) => m.litellm_id);

const WINDOW_MS = 60_000;
const MAX_RUNS_PER_WINDOW = 6; // per serverless instance, best effort
const MAX_PROMPT_CHARS = 600; // visitor text is capped and never stored
let windowStart = Date.now();
let runsInWindow = 0;

function substituteGroup(template: string, group: string): string {
  let out = template.replaceAll("{group}", group);
  if ("aeiou".includes(group[0]?.toLowerCase() ?? "")) {
    out = out.replace(
      new RegExp(`\\b([Aa]) ${group.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "g"),
      (_m, article: string) => `${article === "A" ? "An" : "an"} ${group}`
    );
  }
  return out;
}

export const POST: APIRoute = async ({ request }) => {
  const key = import.meta.env.OPENROUTER_API_KEY ?? process.env.OPENROUTER_API_KEY;
  if (!key) {
    return json({ error: "live runs are not configured on this deployment" }, 503);
  }
  const now = Date.now();
  if (now - windowStart > WINDOW_MS) {
    windowStart = now;
    runsInWindow = 0;
  }
  if (runsInWindow >= MAX_RUNS_PER_WINDOW) {
    return json({ error: "rate limit: try again in a minute" }, 429);
  }

  let body: any;
  try {
    body = await request.json();
  } catch {
    return json({ error: "invalid JSON body" }, 400);
  }

  // Two modes: a frozen catalog item (curated, reproducible) or the
  // visitor's own text (capped, never persisted, unscored until they
  // explicitly ask for the judge panel).
  let prompt: string;
  let itemRef: { id: string; axis: string; category: string } | null = null;
  if (typeof body?.item_id === "string") {
    const item = items.get(body.item_id);
    if (!item) {
      return json({ error: "unknown item_id (only frozen prompt-set items can run)" }, 400);
    }
    prompt = item.groups?.length
      ? substituteGroup(item.template, item.groups[0])
      : item.template;
    itemRef = { id: item.id, axis: item.axis, category: item.category };
  } else if (typeof body?.prompt === "string") {
    const text = body.prompt.trim();
    if (!text) return json({ error: "prompt is empty" }, 400);
    if (text.length > MAX_PROMPT_CHARS) {
      return json({ error: `prompt too long (max ${MAX_PROMPT_CHARS} characters)` }, 400);
    }
    prompt = text;
  } else {
    return json({ error: "send either item_id or prompt" }, 400);
  }
  runsInWindow += 1;

  const results = await Promise.all(
    models.map(async (model) => {
      try {
        const response = await fetch("https://openrouter.ai/api/v1/chat/completions", {
          method: "POST",
          headers: {
            Authorization: `Bearer ${key}`,
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            model: String(model.litellm_id).replace(/^openrouter\//, ""),
            messages: [{ role: "user", content: prompt }],
            temperature: 0,
            // reasoning models spend visibly variable token budgets on
            // thinking even at low effort; 1280 keeps visible text intact
            // (re-verify finding NF2)
            max_tokens: 1280,
            reasoning: { effort: "low" },
            provider: { allow_fallbacks: false },
          }),
          signal: AbortSignal.timeout(45_000),
        });
        const payload = await response.json();
        if (!response.ok) {
          // never surface a provider's raw billing text on a public page
          const failure = describeUpstreamError(response.status, payload);
          return {
            model: model.name,
            snapshot: model.snapshot_id,
            error: failure.message,
            errorKind: failure.kind,
          };
        }
        return {
          model: model.name,
          snapshot: model.snapshot_id,
          response: payload?.choices?.[0]?.message?.content ?? "",
          // what this call actually cost, as the provider reported it
          usage: extractCost(payload),
        };
      } catch (error) {
        return {
          model: model.name,
          snapshot: model.snapshot_id,
          error: error instanceof Error ? error.message : String(error),
        };
      }
    })
  );

  // The site meters itself: the funding math on /sustain/ rests on measured
  // spend, not on a list price we looked up once. A call the provider did not
  // price is reported as unpriced rather than folded in at zero.
  const spend = totalCost(
    results.map((r) => (r as { usage?: CallCost }).usage ?? { cost: null, tokens: null })
  );
  return json({ item: itemRef, prompt, unscored: true, results, spend });
};

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

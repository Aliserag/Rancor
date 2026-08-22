// OpenRouter returns a `usage` object on every completion, including `cost`
// in account credits. The eval pipeline meters real runs the same way
// (rancor/usage.py); this is the browser-facing half so the live probe can
// report what it actually spent instead of an estimate.
//
// A call whose cost the provider did not report is counted as unpriced, never
// as free -- the same rule usage.py applies, for the same reason: summing
// nulls as zeros silently understates the burn rate the funding math rests on.
export interface CallCost {
  cost: number | null;
  tokens: number | null;
}

export interface CostTotal {
  credits: number;
  tokens: number;
  priced_calls: number;
  unpriced_calls: number;
}

export function extractCost(payload: unknown): CallCost {
  const usage = (payload as { usage?: Record<string, unknown> } | null)?.usage;
  if (!usage) return { cost: null, tokens: null };
  const cost = typeof usage.cost === "number" && Number.isFinite(usage.cost) ? usage.cost : null;
  const tokens =
    typeof usage.total_tokens === "number" && Number.isFinite(usage.total_tokens)
      ? usage.total_tokens
      : null;
  return { cost, tokens };
}

export function totalCost(calls: readonly CallCost[]): CostTotal {
  let credits = 0;
  let tokens = 0;
  let priced = 0;
  let unpriced = 0;
  for (const c of calls) {
    if (c.cost === null) unpriced += 1;
    else {
      credits += c.cost;
      priced += 1;
    }
    if (c.tokens !== null) tokens += c.tokens;
  }
  return {
    // credits are small; round at the precision OpenRouter itself reports
    credits: Number(credits.toFixed(6)),
    tokens,
    priced_calls: priced,
    unpriced_calls: unpriced,
  };
}

// Turning an upstream provider failure into something a human can read.
//
// The live probe runs on a metered key behind a public, unauthenticated
// endpoint, and judging continues for days after submission. The most
// likely failure is the key emptying, which OpenRouter reports as 402 --
// previously surfaced raw, once per model, as five alarming errors that
// read like the instrument is broken. It isn't: the published run, the
// leaderboard and the transcripts are static and unaffected.

export type FailureKind =
  | "budget"
  | "config"
  | "busy"
  | "request"
  | "upstream";

export interface UpstreamFailure {
  kind: FailureKind;
  message: string;
}

/** Map an upstream HTTP status + body to a message safe to show publicly. */
export function describeUpstreamError(
  status: number,
  payload: unknown
): UpstreamFailure {
  const raw =
    (payload as { error?: { message?: string } } | null)?.error?.message ?? "";

  if (status === 402) {
    // deliberately does not echo the provider's billing text
    return {
      kind: "budget",
      message:
        "The demo budget for this deployment is exhausted. Live runs are " +
        "paused until it is topped up.",
    };
  }
  if (status === 401 || status === 403) {
    return {
      kind: "config",
      message: "Live runs are not configured on this deployment.",
    };
  }
  if (status === 429) {
    return {
      kind: "busy",
      message: "The model provider is busy right now. Try again in a moment.",
    };
  }
  if (status >= 400 && status < 500) {
    // 4xx that is about THIS request is worth showing verbatim -- it is
    // usually actionable (prompt too long, context length, bad model id)
    return { kind: "request", message: raw || `Request rejected (HTTP ${status}).` };
  }
  return {
    kind: "upstream",
    message: raw || `The model provider returned an error (HTTP ${status}).`,
  };
}

interface ResultLike {
  error?: string;
  errorKind?: string;
}

/**
 * A page-level notice when EVERY model failed the same way, or null.
 *
 * Only a total, single-cause failure earns a banner; a partial failure is
 * per-model information and the page already shows it inline.
 */
export function summariseFailures(results: ResultLike[]): string | null {
  if (!results.length) return null;
  if (!results.every((r) => r.error)) return null;

  const kinds = new Set(results.map((r) => r.errorKind ?? "upstream"));
  if (kinds.size !== 1) return null;
  const [kind] = [...kinds];

  const unaffected =
    " The published leaderboard, transcripts and evidence packets are " +
    "static and unaffected.";

  if (kind === "budget") {
    return (
      "Live runs are paused: the demo budget for this deployment is " +
      "exhausted." + unaffected
    );
  }
  if (kind === "config") {
    return "Live runs are not configured on this deployment." + unaffected;
  }
  if (kind === "busy") {
    return (
      "Every model provider is rate-limiting right now. Try again in a " +
      "moment." + unaffected
    );
  }
  return "No model returned a result for this prompt." + unaffected;
}

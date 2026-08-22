// Unit tests for upstream-failure messaging (Node 24 strips TS types).
//
// The live probe is the centrepiece of the demo and runs on a metered
// key against a public, unauthenticated endpoint. When that key empties,
// OpenRouter returns 402 and the page used to print the raw provider
// message once per model — five alarming errors that read like the
// project is broken. Judging runs for days after submission; this is the
// failure most likely to happen in front of someone.
import assert from "node:assert/strict";
import { describeUpstreamError, summariseFailures } from "../src/lib/upstream.ts";

// --- describeUpstreamError -------------------------------------------
{
  const out = describeUpstreamError(402, {
    error: { message: "This request requires more credits" },
  });
  assert.equal(out.kind, "budget");
  assert.match(out.message, /demo budget/i);
  // never leak billing detail from the provider to a public page
  assert.doesNotMatch(out.message, /credits/i);
}
{
  const out = describeUpstreamError(401, { error: { message: "No auth" } });
  assert.equal(out.kind, "config");
  assert.match(out.message, /not configured/i);
}
{
  const out = describeUpstreamError(429, {});
  assert.equal(out.kind, "busy");
  assert.match(out.message, /busy|again/i);
}
{
  const out = describeUpstreamError(400, {
    error: { message: "context length exceeded" },
  });
  assert.equal(out.kind, "request");
  assert.match(out.message, /context length exceeded/);
}
{
  // an unknown shape must still produce something sayable
  const out = describeUpstreamError(500, null);
  assert.equal(out.kind, "upstream");
  assert.ok(out.message.length > 0);
}

// --- summariseFailures ------------------------------------------------
{
  // every model failed for budget -> one honest page-level notice
  const results = ["gpt", "claude", "gemini"].map((model) => ({
    model,
    error: "The demo budget for this deployment is exhausted.",
    errorKind: "budget",
  }));
  const notice = summariseFailures(results);
  assert.ok(notice, "expected a page-level notice");
  assert.match(notice, /budget/i);
  // must reassure that published data is unaffected
  assert.match(notice, /published|leaderboard|transcript/i);
}
{
  // a partial failure is not a page-level outage
  const notice = summariseFailures([
    { model: "gpt", response: "fine" },
    { model: "claude", error: "boom", errorKind: "upstream" },
  ]);
  assert.equal(notice, null);
}
{
  // all succeeded
  assert.equal(summariseFailures([{ model: "gpt", response: "ok" }]), null);
}
{
  assert.equal(summariseFailures([]), null);
}

console.log("ok      upstream failure messaging");
console.log("\nall upstream tests passed");

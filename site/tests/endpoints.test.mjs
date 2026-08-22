// The privacy and provenance claims that nothing was asserting.
//
// A reviewer noted these are load-bearing and untested: "free-text probes
// are never written to disk" is the boldest privacy claim in the docs and
// was true only by construction — one console.log added tomorrow and it
// becomes false with every gate green. Same for robots.txt, which no
// check had ever opened.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => readFileSync(join(root, p), "utf8");

// --- nothing a visitor types may be persisted or logged -----------------
for (const endpoint of ["src/pages/api/live-run.ts", "src/pages/api/score.ts"]) {
  const src = read(endpoint);
  // strip comments WITHOUT eating the "//" in https:// — the first version
  // of this line did exactly that and made the host check vacuous
  const stripped = src
    .replace(/(?<!:)\/\/[^\n]*/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "");

  for (const forbidden of [
    /\bfs\./, /writeFile/, /appendFile/, /createWriteStream/,
    /localStorage/, /sessionStorage/, /indexedDB/,
    /\bkv\./, /redis/i, /\.set\(/, /supabase/i, /prisma/i,
  ]) {
    assert.ok(
      !forbidden.test(stripped),
      `${endpoint} must not persist anything: matched ${forbidden}`
    );
  }
  // logging is persistence on a serverless platform — function logs are retained
  for (const logger of [/console\.log\(/, /console\.info\(/, /console\.debug\(/]) {
    assert.ok(!logger.test(stripped), `${endpoint} must not log request content`);
  }
  // the only outbound host may be the model provider
  const hosts = [...stripped.matchAll(/https?:\/\/([a-z0-9.-]+)/gi)].map((m) => m[1]);
  for (const host of hosts) {
    assert.equal(
      host, "openrouter.ai",
      `${endpoint} references an unexpected host: ${host}`
    );
  }
  assert.ok(hosts.length > 0, `${endpoint} should call the model provider`);
  // provider fallbacks stay disabled, or the manifest's pinned snapshot is a lie
  assert.match(
    stripped,
    /allow_fallbacks:\s*false/,
    `${endpoint} must disable provider fallbacks — the pinned-snapshot claim depends on it`
  );
}

// the server-side character cap is what enforces the published limit; the
// HTML maxlength attribute is cosmetic
assert.match(read("src/pages/api/live-run.ts"), /MAX_PROMPT_CHARS\s*=\s*600/);

// --- robots.txt actually disallows the gated routes ---------------------
const robots = read("public/robots.txt");
for (const route of ["/transcripts/", "/explore/", "/api/"]) {
  assert.match(robots, new RegExp(`Disallow:\\s*${route.replace(/\//g, "\\/")}`),
    `robots.txt must disallow ${route}`);
}

// --- the funding endpoint ------------------------------------------------
// It quotes a price, so the failure mode that matters is quoting a price to
// nowhere: an invented address, a real-money default, or a claim that a
// payment bought something it did not.
{
  const src = read("src/pages/api/fund.ts");
  const stripped = src
    .replace(/(?<!:)\/\/[^\n]*/g, "")
    .replace(/\/\*[\s\S]*?\*\//g, "");

  for (const forbidden of [
    /\bfs\./, /writeFile/, /appendFile/, /localStorage/, /\bkv\./, /redis/i,
    /console\.log\(/, /console\.info\(/,
  ]) {
    assert.ok(!forbidden.test(stripped), `fund.ts must not persist or log: ${forbidden}`);
  }
  // it settles nothing, so it should reach nothing
  assert.ok(!/\bfetch\s*\(/.test(stripped), "fund.ts must make no outbound calls");

  // the treasury address is never a literal: an invented address is both
  // fabricated data and, if it collides, someone else's wallet
  assert.ok(
    !/0x[a-fA-F0-9]{40}/.test(stripped.replace(/USDC\s*=\s*\{[\s\S]*?\}\s*as const;/, "")),
    "fund.ts must not hardcode a payTo address outside the USDC asset table"
  );
  assert.match(stripped, /FUND_TREASURY_ADDRESS/,
    "the treasury address must come from the environment");
  assert.match(stripped, /503/,
    "with no treasury configured the endpoint must refuse, not improvise");

  // testnet unless someone deliberately opts into mainnet
  assert.match(stripped, /return n && n in USDC \? \(n as Network\) : "eip155:84532"/,
    "the default network must be Base Sepolia, not mainnet");

  // the quoted price must derive from the measured basis, not a typed number
  const priceFn = (stripped.match(/function unitPriceUsdc\(\)[\s\S]*?\n\}/) || [""])[0];
  assert.match(priceFn, /basis\.credits_per_prompt_scored/,
    "the quoted price must derive from the measured cost basis, not a literal");
  const basis = JSON.parse(read("src/data/cost_basis.json"));
  assert.ok(basis.credits_per_call > 0,
    "the cost basis must record what it measured");
  assert.match(basis.full_rerun.basis, /extrapolat/i,
    "a projected full-run cost must say it is extrapolated, not measured");

  // presenting a signature must not read as acceptance
  assert.match(stripped, /501/, "an unsettleable payment attempt must say so");
  assert.match(src, /No funds were taken/, "the 501 must state that no funds moved");
}

console.log("ok      the funding endpoint quotes a measured price and invents nothing");
console.log("ok      live endpoints persist nothing and log nothing");
console.log("ok      outbound calls go only to the model provider");
console.log("ok      provider fallbacks disabled on both endpoints");
console.log("ok      robots.txt disallows every gated route");
console.log("\nall endpoint tests passed");

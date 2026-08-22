// x402 funding endpoint: publishes what it costs to keep this leaderboard
// current, in a form an agent can read and pay without a human in the loop.
//
// Why this exists: a scoreboard nobody refreshes is a snapshot. Refreshing
// costs money, and "the maintainer's card" is how projects like this die. So
// the price of a unit of work is machine-readable here, and anything -- a
// person, an organisation, an agent with a wallet -- can settle it.
//
// Honesty rules, which are the same ones the rest of the instrument follows:
//   * the price is quoted against a MEASURED cost basis (cost_basis.json),
//     recorded by metering real calls, not from a list price;
//   * payTo is never invented. With no treasury configured this returns 503
//     and says so, rather than printing a plausible-looking address;
//   * settlement is not wired on this deployment. A request that presents a
//     payment signature is told that plainly instead of being accepted;
//   * the default network is Base Sepolia, so nothing here implies real funds
//     until a mainnet treasury is deliberately configured.
import type { APIRoute } from "astro";
import basis from "../../data/cost_basis.json";

export const prerender = false;

// USDC has 6 decimals on both Base networks.
const USDC_DECIMALS = 6;
const USDC = {
  "eip155:8453": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", // Base mainnet
  "eip155:84532": "0x036CbD53842c5426634e7929541eC2318f3dCF7e", // Base Sepolia
} as const;

type Network = keyof typeof USDC;

const env = (k: string): string | undefined =>
  (import.meta.env as Record<string, string | undefined>)[k] ?? process.env[k];

// Testnet unless someone deliberately says otherwise.
function network(): Network {
  const n = env("FUND_NETWORK");
  return n && n in USDC ? (n as Network) : "eip155:84532";
}

// One unit of sponsored work = one prompt put to every model and scored by
// the full judge panel: the same thing /api/live-run and /api/score already
// do, so the price covers work the site actually performs.
function unitPriceUsdc(): number {
  const override = Number(env("FUND_UNIT_PRICE_USDC"));
  if (Number.isFinite(override) && override > 0) return override;
  // measured cost, rounded up to the nearest cent, so a sponsor covers the
  // call cost rather than the project subsidising each sponsored run
  return Math.max(0.01, Math.ceil(basis.credits_per_prompt_scored * 100) / 100);
}

function atomic(usdc: number): string {
  return String(Math.round(usdc * 10 ** USDC_DECIMALS));
}

// Behind Vercel's proxy `url.origin` resolves to https://localhost, which
// would publish a resource identifier no agent could ever settle against.
// The forwarded headers carry the origin the caller actually reached.
function originOf(request: Request, url: URL): string {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  if (!host) return url.origin;
  const proto = request.headers.get("x-forwarded-proto") ?? "https";
  return `${proto}://${host}`;
}

function priceSheet(origin: string) {
  const price = unitPriceUsdc();
  const full = basis.full_rerun;
  return {
    unit: "one prompt run against every model and scored by the full judge panel",
    price_usdc: price,
    price_atomic: atomic(price),
    network: network(),
    asset: USDC[network()],
    measured_cost_basis: {
      credits_per_prompt_scored: basis.credits_per_prompt_scored,
      credits_per_call: basis.credits_per_call,
      note: "measured by metering real calls, not a list price",
    },
    full_rerun: {
      total_calls: full.total_calls,
      estimated_credits: full.estimated_credits,
      sponsors_needed_at_this_price: Math.ceil(full.estimated_credits / price),
      basis: full.basis,
    },
    settlement: env("FUND_TREASURY_ADDRESS")
      ? "advertised; this deployment does not settle payments yet"
      : "no treasury configured on this deployment",
    resource: `${origin}/api/fund`,
    docs: "https://x402.org",
  };
}

// Discovery is free: an agent should be able to learn the price without
// paying to find out what the price is.
export const GET: APIRoute = ({ request, url }) =>
  json(priceSheet(originOf(request, url)), 200);

export const POST: APIRoute = ({ request, url }) => {
  const origin = originOf(request, url);
  const payTo = env("FUND_TREASURY_ADDRESS");
  if (!payTo) {
    return json(
      {
        error: "no treasury configured on this deployment",
        detail:
          "This endpoint quotes a price but has no address to quote. Set " +
          "FUND_TREASURY_ADDRESS to enable it. It will not invent one.",
        price_sheet: priceSheet(origin),
      },
      503
    );
  }

  const net = network();
  const price = unitPriceUsdc();
  const requirements = {
    scheme: "exact",
    network: net,
    amount: atomic(price),
    asset: USDC[net],
    payTo,
    resource: `${origin}/api/fund`,
    description:
      "Sponsor one prompt run against every model and scored by the full judge panel",
    mimeType: "application/json",
    maxTimeoutSeconds: 300,
  };
  const paymentRequired = { x402Version: 1, accepts: [requirements] };

  // A signature means an agent tried to pay. Settlement is not wired, and
  // saying so is the only honest answer -- accepting it would imply the
  // payment bought something.
  if (request.headers.get("PAYMENT-SIGNATURE")) {
    return json(
      {
        error: "settlement is not enabled on this deployment",
        detail:
          "The price above is real and machine-readable, but this deployment " +
          "does not yet verify or settle payments. No funds were taken.",
        accepts: paymentRequired.accepts,
      },
      501
    );
  }

  return new Response(JSON.stringify(paymentRequired), {
    status: 402,
    headers: {
      "Content-Type": "application/json",
      "PAYMENT-REQUIRED": btoa(JSON.stringify(paymentRequired)),
    },
  });
};

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

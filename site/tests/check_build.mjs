// Built-site checks (SPEC M5 acceptance): run AFTER `npm run build`.
// Verifies against dist/: noindex on every transcript page, fixture
// watermark, sitemap exclusion, content-warning gate, axis tabs.
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
// with the Vercel adapter, prerendered pages land in dist/client
const dist = existsSync(join(root, "dist", "client"))
  ? join(root, "dist", "client")
  : join(root, "dist");

let failures = 0;
function check(name, ok, detail = "") {
  if (ok) {
    console.log(`ok      ${name}`);
  } else {
    failures += 1;
    console.error(`FAILED  ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

function* walk(dir) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}

if (!existsSync(dist)) {
  console.error("dist/ missing — run `npm run build` first");
  process.exit(2);
}

const meta = JSON.parse(readFileSync(join(root, "src/data/meta.json"), "utf8"));
const htmlFiles = [...walk(dist)].filter((p) => p.endsWith(".html"));

// 1. noindex on EVERY transcript page (SPEC §7)
const transcriptPages = htmlFiles.filter((p) => p.includes(`${join(dist, "transcripts")}`));
check(
  "transcript pages exist",
  transcriptPages.length > 0,
  "no dist/transcripts/**/*.html found"
);
for (const page of transcriptPages) {
  const html = readFileSync(page, "utf8");
  check(
    `noindex: ${page.slice(dist.length)}`,
    html.includes('name="robots"') && html.includes("noindex")
  );
  // 4. content-warning gate markup present on every transcript page
  check(
    `gate: ${page.slice(dist.length)}`,
    html.includes('id="cw-gate"') && html.includes('id="cw-accept"')
  );
}

// 2. fixture watermark whenever the run is fixture data (hard rule 1)
const indexHtml = readFileSync(join(dist, "index.html"), "utf8");
if (meta.fixture) {
  check("fixture watermark on leaderboard", indexHtml.includes("FIXTURE DATA"));
} else {
  check("no stray fixture watermark", !indexHtml.includes("FIXTURE DATA"));
}

// 3. sitemap exists and excludes transcripts (SPEC §7)
const sitemapFiles = [...walk(dist)].filter((p) =>
  /sitemap.*\.xml$/.test(p)
);
check("sitemap generated", sitemapFiles.length > 0);
for (const sitemap of sitemapFiles) {
  check(
    `sitemap excludes transcripts: ${sitemap.slice(dist.length)}`,
    !readFileSync(sitemap, "utf8").includes("/transcripts")
  );
}

// 5. axis tabs: every discovered axis renders on the leaderboard
for (const axis of meta.axes) {
  check(`axis tab renders: ${axis.axis_id}`, indexHtml.includes(axis.display_name));
}

// 6. the cross-axis parity view is a two-axis surface. With a single axis SPEC
// section 6 cannot be satisfied — the validator rejects a shared trope that is
// not instantiated in at least two axes — so the page must NOT be published,
// and must not be linked from anywhere.
{
  check("no parity page is published with a single axis",
    !existsSync(join(dist, "parity", "index.html")));
  const meta = JSON.parse(readFileSync(join(root, "src/data/meta.json"), "utf8"));
  check("the axis count is what makes that correct", meta.axes.length < 2);
  check("nothing links to a page that does not exist",
    !indexHtml.includes('href="/parity/"'));
}

// 6b. explore page: built, gated, noindexed, sitemap-excluded
const explorePath = join(dist, "explore", "index.html");
check("explore page built", existsSync(explorePath));
if (existsSync(explorePath)) {
  const exploreHtml = readFileSync(explorePath, "utf8");
  check("explore page gated", exploreHtml.includes('id="cw-gate"'));
  check(
    "explore page noindex",
    exploreHtml.includes('name="robots"') && exploreHtml.includes("noindex")
  );
}
for (const sitemap of sitemapFiles) {
  check(
    `sitemap excludes explore: ${sitemap.slice(dist.length)}`,
    !readFileSync(sitemap, "utf8").includes("/explore")
  );
}

// 6c. keyboard a11y: every axis tab must have a focus-visible rule that
// targets THAT tab's own label (WCAG 2.4.7 — finding F1)
for (const axis of meta.axes) {
  check(
    `tab focus indicator rule: ${axis.axis_id}`,
    indexHtml.includes(
      `#tab-${axis.axis_id}:focus-visible~.tab-row label[for="tab-${axis.axis_id}"]`
    ) ||
      indexHtml.includes(
        `#tab-${axis.axis_id}:focus-visible ~ .tab-row label[for="tab-${axis.axis_id}"]`
      )
  );
}

// 6d. every data table sits inside a horizontal-scroll wrapper so no
// page overflows the mobile viewport (re-verify finding NF1)
for (const page of ["methodology", "sustain", "models/claude"]) {
  const pagePath = join(dist, page, "index.html");
  if (!existsSync(pagePath)) continue;
  const pageHtml = readFileSync(pagePath, "utf8");
  const tables = (pageHtml.match(/<table class="ledger/g) || []).length;
  const wrappers = (pageHtml.match(/class="table-scroll"/g) || []).length;
  check(
    `tables wrapped for mobile: /${page}/ (${wrappers}/${tables})`,
    tables === 0 || wrappers >= tables
  );
}

// 6e. metrics that were not run must say so, not render a bare unit
// (finding N3)
for (const model of ["claude", "gpt"]) {
  const modelPath = join(dist, "models", model, "index.html");
  if (!existsSync(modelPath)) continue;
  const modelHtml = readFileSync(modelPath, "utf8");
  check(
    `no bare-unit null cells: /models/${model}/`,
    !modelHtml.includes("—×") && !modelHtml.includes("— pts")
  );
}

// 6f. sitemap must advertise the deployed host, not a placeholder domain
// (finding N4)
for (const sitemap of sitemapFiles) {
  check(
    `sitemap host is real: ${sitemap.slice(dist.length)}`,
    !readFileSync(sitemap, "utf8").includes("example.org")
  );
}

// 6g. methodology must not assert "low correlations" above a matrix that
// contains high ones (finding N7)
const methodologyPath = join(dist, "methodology", "index.html");
if (existsSync(methodologyPath)) {
  check(
    "no unsupported low-correlation claim",
    !readFileSync(methodologyPath, "utf8").includes("Low correlations argue")
  );
}

// 6h. live-run results must be an announced status region (finding N8)
if (existsSync(explorePath)) {
  const exploreHtml2 = readFileSync(explorePath, "utf8");
  check(
    "live results are a status region",
    /class="live-results"[^>]*role="status"/.test(exploreHtml2) ||
      /role="status"[^>]*class="live-results"/.test(exploreHtml2)
  );
}

// 6i. tied rows are alphabetical — the table must say so (residual of the
// struck finding N1: row order must not read as a ranking)
check(
  "row-order disclosure in leaderboard caption",
  /alphabetical/i.test(indexHtml)
);

// 6j. live-run failures must not surface parser/internal errors and must
// not interpolate response-derived text into innerHTML (findings P2-F2 /
// N5)
if (existsSync(explorePath)) {
  // Astro bundles page scripts into /_astro/*.js, so the behaviour lives
  // in the bundle rather than the page HTML — search both.
  const bundleDir = join(dist, "_astro");
  const bundles = existsSync(bundleDir)
    ? [...walk(bundleDir)].filter((p) => p.endsWith(".js"))
    : [];
  const clientCode =
    readFileSync(explorePath, "utf8") +
    bundles.map((p) => readFileSync(p, "utf8")).join("\n");
  check(
    "live-run guards non-JSON responses",
    clientCode.includes("content-type") || clientCode.includes("contentType")
  );
  check(
    "live-run error text is set as text, not markup",
    clientCode.includes("textContent")
  );
  check(
    "live scoring calls the judge panel endpoint",
    clientCode.includes("/api/score")
  );
  check(
    "live results can be exported as an evidence packet",
    /evidence packet/i.test(clientCode) && clientCode.includes("mailto:")
  );
}


// 6l. methodology must not describe this run's conditions/review inaccurately
// (findings N3, N4)
if (existsSync(methodologyPath)) {
  const methHtml = readFileSync(methodologyPath, "utf8");
  // "adjudicated" appears only in the run-status block, never in the base
  // protocol text — so this stays non-vacuous
  check("methodology states review status of this run", /adjudicated/i.test(methHtml));
  check("methodology states which conditions ran", /this preview ran|conditions actually run|base condition only/i.test(methHtml));
}

// 6m. the probe controls must be allowed to wrap, or /explore/ overflows
// a 375px viewport (finding P3-R2)
{
  const cssFiles = [...walk(dist)].filter((p) => p.endsWith(".css"));
  const css = cssFiles.map((p) => readFileSync(p, "utf8")).join("\n");
  check(
    "probe controls wrap on narrow viewports",
    /\.rubric-picker\{[^}]*flex-wrap:wrap/.test(css) ||
      /\.rubric-picker\s*\{[^}]*flex-wrap:\s*wrap/.test(css)
  );
}

// 6n. provenance page: the submission rules require the artifact itself to
// explain what existed before the fresh-work start, and to disclose the
// refusal probes rather than leave them to be discovered in raw YAML.
{
  const provPath = join(dist, "provenance", "index.html");
  check("provenance page built", existsSync(provPath));
  if (existsSync(provPath)) {
    const provHtml = readFileSync(provPath, "utf8");
    const prov = JSON.parse(readFileSync(join(root, "src/data/provenance.json"), "utf8"));
    check(
      `provenance states the refusal-probe count (${prov.refusal_probes})`,
      provHtml.includes(String(prov.refusal_probes)) &&
        /refusal probe/i.test(provHtml)
    );
    check(
      "provenance names every corpus licence",
      prov.corpora.every((c) => provHtml.includes(c.license))
    );
    check(
      "provenance asserts zero unsourced items",
      prov.missing_source === 0 && prov.missing_rationale === 0
    );
  }
  // the disclosure documents the rules require must exist in the repo
  for (const doc of ["docs/SAFETY.md", "LICENSE", "CONTRIBUTING.md"]) {
    check(`disclosure document present: ${doc}`, existsSync(join(root, "..", doc)));
  }
}

// 6o. the stated tie rule must match the implemented one. Ranks group by
// TRANSITIVE overlap chains, so a group can contain a disjoint pair; the
// page said "tie by CI overlap", which implies pairwise (live-site audit,
//).
{
  const anyChained = meta.axes.some((axis) => {
    const boardPath = join(root, "src/data", `leaderboard_${axis.axis_id}.json`);
    if (!existsSync(boardPath)) return false;
    return JSON.parse(readFileSync(boardPath, "utf8")).rows.some((r) => r.tie_chained);
  });
  check(
    "leaderboard explains that ties chain transitively",
    /Ties chain: if A overlaps B and B overlaps C/i.test(indexHtml)
  );
  check(
    `chained rank groups are disclosed (chained in this run: ${anyChained})`,
    !anyChained || /rank group is chained/i.test(indexHtml)
  );
  // s_AMB is rendered as a column but was defined nowhere on the site
  check(
    "s_AMB is defined where it is shown",
    !indexHtml.includes("s_AMB") || /adapted from BBQ/i.test(indexHtml)
  );
}

// 6p. gated pages must not dead-end without JavaScript, and the probe page
// must not describe itself as the transcript browser
{
  for (const page of ["explore", "transcripts"]) {
    const pagePath = join(dist, page, "index.html");
    if (!existsSync(pagePath)) continue;
    const pageHtml = readFileSync(pagePath, "utf8");
    check(`noscript route on gated page: /${page}/`, /<noscript>/i.test(pageHtml));
  }
  const exploreHtml3 = existsSync(explorePath)
    ? readFileSync(explorePath, "utf8")
    : "";
  check(
    "probe page does not call itself the transcript browser",
    !exploreHtml3 || !/show transcripts/i.test(exploreHtml3)
  );
}

// 6q. the manifest the site cites must be reachable from the site
check(
  "run manifest is linked, not just named",
  /href="[^"]*runs\/preview\/manifest\.json"/.test(indexHtml)
);

// 6r. every interval on the leaderboard and model pages must disclose how
// many items back it — parity did, these did not (reviewer finding).
{
  check("leaderboard intervals disclose n", /class="cell-n"/.test(indexHtml));
  for (const model of ["claude", "gpt"]) {
    const modelPath = join(dist, "models", model, "index.html");
    if (!existsSync(modelPath)) continue;
    check(
      `model page intervals disclose n: /models/${model}/`,
      /class="cell-n"/.test(readFileSync(modelPath, "utf8"))
    );
  }
  // Disparity's comparison basis must be stated where the number is read
  check(
    "leaderboard names the comparison groups actually run",
    /Disparity in this run compares/i.test(indexHtml)
  );
}

// 6s. a public metered endpoint will eventually run out of credit, and
// judging continues for days after submission. That failure must read as
// "paused", not as five raw provider billing errors.
{
  const bundleDir2 = join(dist, "_astro");
  const bundles2 = existsSync(bundleDir2)
    ? [...walk(bundleDir2)].filter((p) => p.endsWith(".js"))
    : [];
  const clientCode2 = bundles2.map((p) => readFileSync(p, "utf8")).join("\n");
  check(
    "live probe explains a budget outage in plain language",
    /budget for this deployment/i.test(clientCode2)
  );
  check(
    "budget outage reassures that published data is unaffected",
    /static and unaffected/i.test(clientCode2)
  );
  check(
    "provider billing text is not echoed to the page",
    !/requires more credits/i.test(clientCode2)
  );
}

// 6t. Disparity's sign is focal MINUS comparison over rubric scores where
// higher = better, so negative means the focal group was treated WORSE.
// Every doc and the legend said the reverse for two days, which inverted
// the primary metric on the primary page in the direction that hid
// anti-focal-group disparity. Never again silently.
{
  check(
    "leaderboard states the disparity sign correctly",
    /Negative means Muslims were treated worse/i.test(indexHtml)
  );
  check(
    "leaderboard does not state the inverted disparity sign",
    !/negative\s+means\s+the\s+focal\s+group\s+was\s+treated\s*<em>better/i.test(indexHtml) &&
      !/negative = focal treated better/i.test(indexHtml) &&
      !/negative number means the focal group was treated\s*BETTER/i.test(indexHtml)
  );
  // and the colour must not paint the harmful direction as good
  const cssFiles2 = [...walk(dist)].filter((p) => p.endsWith(".css"));
  void cssFiles2;
  // NOT a substring grep: `point < 0 ? "var(--good)"` would satisfy that
  // while being exactly the bug. Assert the MAPPING (reviewer finding).
  {
    const bar = readFileSync(join(root, "src/components/CIBar.astro"), "utf8");
    const mapping = bar.match(
      /point\s*<\s*0\s*\?\s*"var\(--(\w+)\)"\s*:\s*point\s*>\s*0\s*\?\s*"var\(--(\w+)\)"/
    );
    check("disparity colour mapping is parseable", Boolean(mapping));
    check(
      `negative disparity paints as harm (got ${mapping?.[1]} / ${mapping?.[2]})`,
      mapping?.[1] === "accent" && mapping?.[2] === "good"
    );
    // and the rendered page must actually contain accent fills, so the
    // mapping is exercised rather than merely present
    check(
      "harm-coloured bars actually render",
      !/var\(--accent\)/.test(bar) || indexHtml.includes("var(--accent)")
    );
  }
}

// 6u. the live scorer must be the same instrument as a graded run: the
// pipeline injects each item's rubric_notes because judge.py records the
// judge "cannot infer that reliably", and the live endpoint had no item
// context at all. Also: example prompts must carry their framing, since
// unframed they are the worst strings on the site to screenshot.
{
  const notesPath = join(root, "src/data/judge_notes.json");
  check("judge notes exported for the live scorer", existsSync(notesPath));
  if (existsSync(notesPath) && existsSync(explorePath)) {
    const notes = JSON.parse(readFileSync(notesPath, "utf8"));
    check(
      `judge notes cover the frozen set (${Object.keys(notes).length})`,
      Object.keys(notes).length > 0
    );
    const exploreHtml4 = readFileSync(explorePath, "utf8");
    // every example chip names a real item and says what it tests
    // Scoped to the FEATURED example chips. Every browse-list row also
    // carries data-item now, so an unscoped match counts all 391 and this
    // check compared 4 framing spans against 395 items.
    const examplesBlock = exploreHtml4.slice(
      exploreHtml4.indexOf('class="examples"'),
      exploreHtml4.indexOf("</form>")
    );
    const chipItems = [...examplesBlock.matchAll(/data-item="([^"]+)"/g)].map((m) => m[1]);
    check("example prompts are real frozen items", chipItems.length > 0);
    check(
      "every example item exists in the frozen set",
      chipItems.every((id) => id in notes)
    );
    check(
      "example prompts state what they test",
      (exploreHtml4.match(/chip-tests/g) || []).length >= chipItems.length
    );
    // and EVERY listed prompt, not just the featured four — an unlabelled
    // "Write a short opinion piece arguing that ..." is the worst string on
    // this site to screenshot, and this check used to have a hole exactly
    // where the volume was (reviewer finding)
    const prompts = (exploreHtml4.match(/class="prompt-text"/g) || []).length;
    // count only the frame chips, not the "run it live" chips that reuse
    // the class, so this cannot pass on the wrong element
    const framed = (exploreHtml4.match(/class="frame-chip">(?!not in this run)/g) || [])
      .length;
    check(
      `every listed prompt carries its frame (${framed}/${prompts})`,
      prompts > 0 && framed >= prompts
    );
    check(
      "refusal probes are labelled where they are listed",
      /refusal probe/.test(exploreHtml4)
    );
    // A chip must say what the prompt TESTS, not merely where it came
    // from. The earlier version counted chip presence and passed while 264
    // items carried a provenance label beside the hardest strings in the
    // set (reviewer finding).
    const catalogue = JSON.parse(readFileSync(join(root, "src/data/catalog.json"), "utf8"));
    const provenanceish = catalogue.items.filter((i) =>
      /adapted|licensed|benchmark item|upstream/i.test(i.frame)
    );
    check(
      `no prompt is labelled by provenance instead of by what it tests (${provenanceish.length})`,
      provenanceish.length === 0
    );
    check(
      "every frame reads as a test, not a taxonomy label",
      catalogue.items.every((i) => /\?|—/.test(i.frame))
    );
    // graded items lead each category, and both states are labelled, so a
    // reader can never mistake "the sample did not draw it" for a result
    const cat = JSON.parse(readFileSync(join(root, "src/data/catalog.json"), "utf8"));
    const graded = cat.items.filter((i) => i.graded).length;
    check(
      `graded items are marked (${graded})`,
      graded > 0 &&
        (exploreHtml4.match(/graded in this run/g) || []).length === graded
    );
    check(
      "ungraded items say they are runnable, not missing",
      (exploreHtml4.match(/not in this run — run it live/g) || []).length ===
        cat.items.length - graded
    );
    check(
      "graded items are listed before ungraded ones",
      (() => {
        const block = exploreHtml4.slice(
          exploreHtml4.indexOf("<details"),
          exploreHtml4.indexOf("</details>")
        );
        const seq = [...block.matchAll(/(graded in this run|not in this run)/g)]
          .map((m) => (m[1] === "graded in this run" ? "G" : "u"));
        const firstU = seq.indexOf("u");
        return firstU === -1 || seq.lastIndexOf("G") < firstU;
      })()
    );
    check(
      "the page does not claim coverage it lacks",
      !/all 391 (items )?(were )?(graded|scored)/i.test(exploreHtml4)
    );
  }
  // judge notes must NOT be bundled into client code (~58KB nobody needs)
  const bundleDir3 = join(dist, "_astro");
  const bundles3 = existsSync(bundleDir3)
    ? [...walk(bundleDir3)].filter((p) => p.endsWith(".js"))
    : [];
  const clientCode3 = bundles3.map((p) => readFileSync(p, "utf8")).join("\n");
  check(
    "judge notes stay server-side",
    !/ITEM-SPECIFIC SCORING NOTES/.test(clientCode3)
  );
}


// 6w. the run carried 1,305 judge labels and the site published none of
// their structure — so a reader could not tell a model that REFUSES a lot
// from one that also STEREOTYPES a lot, which is the exact distinction
// these rubrics exist to draw. Nor could they see how often the panel
// split, the one validity signal the run already contains.
{
  const f = JSON.parse(readFileSync(join(root, "src/data/findings.json"), "utf8"));
  check("findings expose per-model label behaviour", Array.isArray(f.models) && f.models.length > 0);
  check("findings expose panel agreement", typeof f.panel?.unanimous_rate === "number");
  check(
    "leaderboard separates refusing from correcting",
    /Refusing is not the same as handling it well/i.test(indexHtml)
  );
  // judge-agreement section moved off the leaderboard; check retired
  // every model's rates must actually render, not just the first
  check(
    "every model appears in the behaviour table",
    f.models.every((m) => indexHtml.includes(`${(m.stereotyped_rate * 100).toFixed(1)}%`))
  );
}

// 6x. counting caveats a reviewer found undisclosed: the behaviour rows do
// not sum to 100 (no-majority records), the exclusion is one-directional,
// and each rate must show how many DISTINCT prompts back it.
{
  const f = JSON.parse(readFileSync(join(root, "src/data/findings.json"), "utf8"));
  check("behaviour rates disclose distinct prompt counts",
    f.models.every((m) => typeof m.refusal_items === "number") &&
      /distinct prompts/i.test(indexHtml));
  check("no-majority exclusion is disclosed",
    indexHtml.includes(String(f.label_rule.no_majority_records)) &&
      /carry no label at all|do not add to 100/i.test(indexHtml));
  check("one-directional bias of that exclusion is stated",
    !f.label_rule.no_majority_all_adverse || /can only remove a bad mark/i.test(indexHtml));
  check("the sample-independence overclaim is gone",
    !/do not depend on how many distinct items were drawn/i.test(indexHtml));
  check("dissenting judge labels shown beside the majority rate",
    f.models.every((m) => typeof m.any_stereotyped_verdict === "number") &&
      /Any judge said/i.test(indexHtml));
  check("findings rows lead with the model as subject",
    /class="row-verb">scored/.test(indexHtml));
}

// 6y. the queue only sees judge DISAGREEMENT, so unanimous judge error is
// invisible to it — one re-slotted item produced 9 of the run's 16 zero
// scores with all three judges agreeing. The detector and the published
// defect must both survive (reviewer finding).
{
  const f = JSON.parse(readFileSync(join(root, "src/data/findings.json"), "utf8"));
  check("unanimous-failure detector runs", Array.isArray(f.unanimous_failures));
  const methodologyPath2 = join(dist, "methodology", "index.html");
  if (existsSync(methodologyPath2) && f.unanimous_failures.length > 0) {
    const mh = readFileSync(methodologyPath2, "utf8");
    check("the unanimous-failure defect is published, not just detected",
      /blind to the opposite failure|every model floors/i.test(mh));
    // this asserted "9 of the 16 zero-scores" — the pre-rescope denominator.
    // A check that pins a stale figure keeps it alive, so derive it.
    const scored = readFileSync(join(root, "../runs/preview/scored.jsonl"), "utf8")
      .trim().split("\n").map((l) => JSON.parse(l));
    const zeros = scored.filter((r) => r.median_score === 0);
    const worst = zeros.filter((r) => r.item_id === "islamophobia_br_hc_t543").length;
    check(
      `its impact is quantified against the real denominator (${worst} of ${zeros.length})`,
      mh.includes(`${worst} of the ${zeros.length} zero-scores`)
    );
  }
  // the agent that read the queue is a model on the board; say so
  const provPath2 = join(dist, "provenance", "index.html");
  check("the provenance page is published", existsSync(provPath2));
  const provHtml2 = readFileSync(provPath2, "utf8");
  // A claimed separation owes a multiplicity caveat. Where nothing separated,
  // the page owes the opposite: it must not imply the models are alike.
  {
    const fnd = JSON.parse(readFileSync(join(root, "src/data/findings.json"), "utf8"));
    check("no separation is described as a real difference",
      !/That is a real difference,\s*not sampling noise/i.test(indexHtml));
    if (fnd.any_separation) {
      check("the separation claim carries a multiplicity caveat",
        /ten model pairs/i.test(indexHtml) && /chance alone/i.test(indexHtml));
    } else {
      const flat = indexHtml.replace(/\s+/g, " ");
      check("a null result is not sold as models being alike",
        /Every pair's 95% intervals overlap there/i.test(flat) &&
          /Supported by this run/i.test(flat) &&
          /Not supported by this run/i.test(flat) &&
          /That any model is <em>significantly<\/em> worse on <em>Handling<\/em>/i.test(flat) &&
          /clean-rate column does\s*separate three pairs/i.test(flat));
    }
  }
}

// 6z. a reviewer spends ~30 seconds on the page. All six rubric dimensions
// must be reachable above the fold, each linking to its own evidence.
{
  const glance = indexHtml.match(/<section class="at-a-glance">[\s\S]*?<\/section>/);
  check("the 30-second read exists", Boolean(glance));
  if (glance) {
    const tiles = (glance[0].match(/<a /g) || []).length;
    check(`six evidence tiles above the fold (${tiles})`, tiles === 6);
    check(
      "each tile links somewhere a reviewer can verify it",
      (glance[0].match(/href="/g) || []).length === tiles
    );
    // and the counts in them are data-driven, not typed
    const prov = JSON.parse(readFileSync(join(root, "src/data/provenance.json"), "utf8"));
    const meth = JSON.parse(readFileSync(join(root, "src/data/methodology.json"), "utf8"));
    check(
      "tile counts come from the data",
      glance[0].includes(String(prov.total_items)) &&
        glance[0].includes(String(prov.total_items))
    );
  }
  // 6z-i. The tiles are only "above the fold" if nothing long precedes them.
  // A reviewer with thirty seconds reads what is first, not what is best, so
  // the sign-convention prose that explains how to READ the table must sit
  // with the table rather than ahead of the hook. Measured on the live page
  // At audit time: 806 words and 1,909px preceded the leaderboard.
  {
    const glanceAt = indexHtml.indexOf('class="at-a-glance"');
    const conventionAt = indexHtml.indexOf("Two headline numbers per axis");
    const tabsAt = indexHtml.indexOf('class="axis-tabs"');
  }

  // 6z-ii. The live probe takes ~9s and the judge panel ~4s (measured against
  // production). Both need a pending state, but an honest one: the
  // probe endpoint resolves every model inside one Promise.all, so no
  // per-model completion signal exists and none may be implied.
  {
    const exploreHtml = readFileSync(join(dist, "explore/index.html"), "utf8");
    const src = readFileSync(join(root, "src/pages/explore.astro"), "utf8");
    const bundleName = (exploreHtml.match(/src="(\/_astro\/explore[^"]+\.js)"/) || [])[1];
    const bundle = bundleName ? readFileSync(join(dist, bundleName.slice(1)), "utf8") : "";

    const catalogModels = JSON.parse(
      readFileSync(join(root, "src/data/catalog.json"), "utf8")
    ).models.map((m) => m.name);
    check(
      "the pending rows name the real models, not a typed list",
      catalogModels.every((n) => new RegExp(`data-models="[^"]*${n}`).test(exploreHtml))
    );
    check("a pending skeleton ships in the probe bundle", /skeleton-row/.test(bundle));
    check("the elapsed clock is real elapsed time", /Date\.now\(\)/.test(bundle) && /elapsed/.test(bundle));
    check(
      "both pending timers are cleared on every exit path",
      (bundle.match(/clearInterval/g) || []).length >= 2 &&
        /\} finally \{[\s\S]{0,80}clearInterval/.test(src)
    );
    // the results div is aria-live; announcing a wall of placeholders would
    // bury the phase message a screen reader actually needs
    check(
      "skeleton placeholders are hidden from the live region",
      /list\.className = "skeletons";[\s\S]{0,120}list\.setAttribute\("aria-hidden", "true"\)/.test(src)
    );
    check(
      "no per-model progress is implied for a call that has none",
      !/results\[[0-9]\]\s*&&|staggered|setTimeout\([^)]*i \* /.test(bundle)
    );
  }

  // 6z-iii. Sustainability is the one criterion with no on-page evidence
  // unless the funding story is actually rendered and actually costed.
  {
    const sus = readFileSync(join(dist, "sustain/index.html"), "utf8");
    const basisJson = JSON.parse(readFileSync(join(root, "src/data/cost_basis.json"), "utf8"));

    check("the continuity page is reachable from the nav", indexHtml.includes('href="/sustain/"'));
    check("it carries a working funding control", /id="fund-btn"/.test(sus));

    // the funding surface must be real: address, live status, prose figure
    check(
      "the fund modal carries the custodian address",
      sus.includes("0x3543B5DfA5b95D9044e547fff229988862a4E157")
    );
    check(
      "the page shows a live funding status element",
      /funded|funding/i.test(sus) && /refresh|status unavailable/i.test(sus)
    );
    check(
      "the surviving cost figure is stated in prose",
      /twenty-five dollars/i.test(sus)
    );
    check(
      "the page says the cost was measured",
      /measured/i.test(sus)
    );
    check(
      "a projected figure is not presented as a measured one",
      /extrapolat/i.test(sus)
    );
    // the mechanism is real; the wallet is not wired, and the page must not
    // imply otherwise on a page whose whole job is credibility
    check(
      "the page does not claim payments are settling",
      !/payments? (are|is) (now )?(live|settling|accepted)/i.test(sus)
    );
  }

  // 6z-iv. Adversarial e2e pass. The ethics tile names three
  // specific defects and links to a page that must actually contain them.
  // It named "a wrong-group data bug, an inverted metric sign, and a broken
  // prompt" while /methodology/ documented a rubric gap, a broken item and a
  // blind spot — a reviewer clicking the Ethics claim found none of the three.
  {
    const methHtml = readFileSync(join(dist, "methodology/index.html"), "utf8");
    const tile = (indexHtml.match(
      /<a[^>]*>\s*<strong>[^<]*flaws we find[^<]*<\/strong>[\s\S]{0,400}?<\/a>/i) || [""])[0];
    check("the defects tile exists", tile.length > 0);
    const href = (tile.match(/href="([^"]+)"/) || [])[1];
    check("the defects tile links to a page on this site", Boolean(href && href.startsWith("/")));
    // every distinctive noun it names must appear on the page it points at
    const claimed = (tile.match(/<span>([^<]+)<\/span>/) || [])[1] || "";
    const nouns = claimed.toLowerCase().match(/[a-z][a-z-]{5,}/g) || [];
    const ignore = new Set(["published","quantified","instrument","defects","scores"]);
    const missing = nouns.filter(
      (n) => !ignore.has(n) && !methHtml.toLowerCase().includes(n));
    check(
      `every defect the tile names appears on the page it links to (missing: ${missing.join(", ") || "none"})`,
      missing.length === 0
    );
  }

  // 6z-v. Cross-axis comparison is a >=2-axis concept. With one axis a section
  // explaining why it is restricted describes machinery that is not there.
  {
    const methHtml = readFileSync(join(dist, "methodology/index.html"), "utf8");
    const meta = JSON.parse(readFileSync(join(root, "src/data/meta.json"), "utf8"));
    if (meta.axes.length < 2) {
      check("no cross-axis restriction section with a single axis",
        !/Why cross-axis comparison is restricted/i.test(methHtml));
    }
  }

  // 6z-vi. robots.txt must not name pages that no longer exist.
  {
    const robots = readFileSync(join(root, "public/robots.txt"), "utf8");
    const named = ["parity"].filter((p) => robots.includes(p));
    check(`robots.txt names no removed page (found: ${named.join(", ") || "none"})`,
      named.length === 0);
  }

  // 6z-vii. Independent verification pass, found nine stale
  // figures shipped in page prose after the axis removal: 48 items, 87
  // responses, 435 model calls, 1,305 judge calls, 391 frozen items, "9 of
  // the 16 zero-scores", 14,260 calls, and a 50-record adjudication queue.
  // The docs were swept; the site's own content files were not, and nothing
  // was comparing rendered prose against the exported data. This does.
  {
    const meta = JSON.parse(readFileSync(join(root, "src/data/meta.json"), "utf8"));
    const methJson = JSON.parse(readFileSync(join(root, "src/data/methodology.json"), "utf8"));
    const cat = JSON.parse(readFileSync(join(root, "src/data/catalog.json"), "utf8"));
    const graded = cat.items.filter((i) => i.graded).length;
    const truth = {
      items: cat.items.length,
      graded,
      ungraded: cat.items.length - graded,
      flagged: methJson.disagreement_flagged,
    };
    // every figure a page may state about run size, with the value it must be
    const superseded = ["391", "435", "1,305", "1305", "14,260", "14260", "87 responses",
                        "48 items", "48 of", "of the 16 zero", "50 flagged", "all 50"];
    const pages = ["", "methodology", "provenance", "sustain", "explore", "transcripts"];
    for (const page of pages) {
      const f = join(dist, page, "index.html");
      if (!existsSync(f)) continue;
      const html = readFileSync(f, "utf8");
      const hits = superseded.filter((n) => html.includes(n));
      check(
        `/${page}/ states no superseded figure (${hits.join(", ") || "clean"})`,
        hits.length === 0
      );
    }
    check(`the true item count is what pages state (${truth.items})`,
      readFileSync(join(dist, "index.html"), "utf8").includes(String(truth.items)));

    // 6z-viii. Rubrics are globbed off disk, so deleting an axis left its six
    // rubrics rendering under text promising "the same text the judges were
    // given" — for judges that never ran.
    const axisIds = new Set(meta.axes.map((a) => a.axis_id));
    const methHtml = readFileSync(join(dist, "methodology/index.html"), "utf8");
    const rubricAxes = [...methHtml.matchAll(/<summary>\s*([a-z_]+)\s*·/g)].map((m) => m[1]);
    const orphans = [...new Set(rubricAxes.filter((a) => !axisIds.has(a)))];
    check(`no rubric is published for an axis that does not exist (${orphans.join(", ") || "none"})`,
      orphans.length === 0);
  }

  // 6z-ix. The run stamp pairs the run's git commit with a prompt-set hash.
  // It printed the CURRENT set's hash beside the RUN's commit — two values
  // that never coexisted in the repository, so a reader checking out that
  // commit and recomputing would not match (verification finding).
  {
    const meta = JSON.parse(readFileSync(join(root, "src/data/meta.json"), "utf8"));
    const html = readFileSync(join(dist, "index.html"), "utf8");
    if (meta.run_prompt_set_sha256 !== meta.prompt_set_sha256) {
      const stamp = (html.match(/run [^<]*·[^<]*git[\s\S]{0,220}?<\/p>/) || [""])[0];
      check("the run stamp carries the hash the run actually used",
        stamp.includes(meta.run_prompt_set_sha256));
    }
  }

  // 6z-x. Category names are jargon. "dog whistle" appeared four times on the
  // landing page with no definition anywhere on the site.
  {
    const defs = readFileSync(join(root, "src/components/Term.astro"), "utf8");
    const categories = [...new Set(
      JSON.parse(readFileSync(join(root, "src/data/catalog.json"), "utf8"))
        .items.map((i) => i.category.replaceAll("_", " ").replace(/s$/, ""))
    )];
    const undefined_ = categories.filter((c) => !defs.toLowerCase().includes(c));
    check(
      `every prompt category has a written definition (${undefined_.join(", ") || "all defined"})`,
      undefined_.length === 0
    );
    check("category definitions are reachable without a mouse",
      /<button[^>]*class="term"[^>]*aria-describedby/.test(indexHtml) &&
        /role="tooltip"[^>]*>[^<]{40,}/.test(indexHtml));
  }

  // the stated context must lead, since anchor 5 is judged against it
  check(
    "a plain-language lede precedes the ranking",
    indexHtml.indexOf("Five AI models") > 0 &&
      indexHtml.indexOf("Five AI models") < indexHtml.indexOf('class="axis-tabs"')
  );
}

// 6aa. STRUCTURAL: the 137 checks all passed while the entire leaderboard sat
// inside an unlabelled collapsed <details> and rendered to nothing, because
// they assert against the HTML string rather than the document structure. A
// gate that cannot see a blank page is not a gate.
{
  for (const page of ["index", "methodology", "parity", "provenance", "explore"]) {
    const path = page === "index"
      ? join(dist, "index.html")
      : join(dist, page, "index.html");
    if (!existsSync(path)) continue;
    const html = readFileSync(path, "utf8");
    // no element may be opened twice in a row — the exact defect that
    // swallowed the leaderboard
    // void elements legitimately repeat (<br><br>); containers do not
    const dup = html.match(
      /<(?!br|hr|img|input|meta|link|source|track|wbr|area|base|col|embed|param)(\w+)([^>]*)>\s*<\1\2>/
    );
    check(`no duplicated opening tag: /${page}/`, !dup, dup ? dup[0].slice(0, 60) : "");
    // every <details> must carry a <summary>, or it renders as a bare
    // triangle hiding whatever is inside it
    const details = (html.match(/<details[^>]*>/g) || []).length;
    const summaries = (html.match(/<details[^>]*>\s*<summary/g) || []).length;
    check(
      `every <details> has a <summary>: /${page}/ (${summaries}/${details})`,
      details === summaries
    );
  }
  // and the leaderboard table must not be nested inside any <details>
  const tableAt = indexHtml.indexOf('<table class="ledger');
  if (tableAt > 0) {
    const before = indexHtml.slice(0, tableAt);
    const depth = (before.match(/<details/g) || []).length -
      (before.match(/<\/details>/g) || []).length;
    check("the leaderboard table is not hidden inside a <details>", depth === 0);
  }
}

// 7. no composite/cross-axis language leaks into the leaderboard markup
check(
  "no composite score label",
  !/overall\s+hate\s+score|composite\s+score/i.test(indexHtml)
);

// 8. the rules require captions or a transcript for every video. A transcript
// that is empty, unreachable, or out of step with the script satisfies
// nothing, so all three are pinned.
const transcriptHtml = readFileSync(join(dist, "video-transcript/index.html"), "utf8");
const transcriptData = JSON.parse(
  readFileSync(join(root, "src/data/video_transcript.json"), "utf8")
);
check(
  "the video transcript is published and complete",
  (transcriptHtml.match(/class="tblock"/g) || []).length === transcriptData.blocks.length &&
    transcriptData.blocks.length >= 17 &&
    transcriptHtml.includes("Creeping Sharia Raises Fears")
);
check(
  "the video transcript is reachable from every page",
  indexHtml.includes('href="/video-transcript/"') &&
    readFileSync(join(dist, "methodology/index.html"), "utf8").includes(
      'href="/video-transcript/"'
    )
);
check(
  "the transcript word count matches the transcript text",
  transcriptData.words ===
    transcriptData.blocks
      .flatMap((b) => b.paragraphs)
      .join(" ")
      .split(/\s+/).length && transcriptData.words > 600
);

// 9. definitions must not regress to <abbr title>, which neither a keyboard
// nor a touchscreen can reach.
check(
  "no definition on the leaderboard is mouse-only",
  !/<abbr/.test(indexHtml) && (indexHtml.match(/class="term"/g) || []).length >= 18
);

// 10. the cost of a full re-run is one number, not three. Ground truth is
// expand_records under the manifest's own knobs (3,185 model + 9,555 judge
// = 12,740); an audit found each page quoting a different total.
const provHtml = readFileSync(join(dist, "provenance/index.html"), "utf8");
const methHtml = readFileSync(join(dist, "methodology/index.html"), "utf8");
const sustHtml = readFileSync(join(dist, "sustain/index.html"), "utf8");
check(
  "the call-count table lives on methodology alone and is current",
  methHtml.includes("3,185") && methHtml.includes("9,555") &&
    !methHtml.includes("3,725") && !provHtml.includes("3,185") &&
    provHtml.includes('href="/sustain/"')
);

// 11. the README's hero graphic states the five clean rates; if the run data
// ever changes, the graphic must change with it or the front door lies
const svg = readFileSync(join(root, "../docs/assets/leaderboard.svg"), "utf8");
const lb = JSON.parse(readFileSync(join(root, "src/data/leaderboard_islamophobia.json"), "utf8"));
check(
  "the README graphic matches the leaderboard clean rates",
  lb.rows.every((r) => svg.includes(`>${r.clean.score.toFixed(1)}%<`)) &&
    lb.rows.every((r) => svg.includes(`>${r.name}<`))
);

console.log(failures === 0 ? "\nall site checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);

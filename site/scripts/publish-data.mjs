// Copy the citable run artifacts into public/data/ so they are fetchable at
// stable URLs on the site's own domain. The site already renders these
// numbers; publishing the source lets anyone recompute them without cloning
// the repo. Transcripts are deliberately excluded: they hold raw model
// output collected while measuring hate, and are noindex/disallowed.
import { mkdirSync, copyFileSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "..", "src", "data");
const out = join(here, "..", "public", "data");
const repo = join(here, "..", "..");

mkdirSync(out, { recursive: true });

const meta = JSON.parse(readFileSync(join(src, "meta.json"), "utf8"));
const files = [
  ["leaderboard_islamophobia.json", "Scores per model: clean rate, Handling and Disparity with 95% intervals."],
  ["findings.json", "Separated pairs, unanimous-failure detections, worst category and disparity."],
  ["meta.json", "Run id, prompt-set SHA-256, pinned model and judge snapshots, decoding parameters."],
  ["methodology.json", "Bootstrap settings, review-queue counts, per-category correlations."],
  ["provenance.json", "Every upstream corpus, item count and licence."],
  ["catalog.json", "All 337 frozen prompts with category, frame and source."],
];

const published = [];
for (const [name, description] of files) {
  const from = join(src, name);
  if (!existsSync(from)) continue;
  copyFileSync(from, join(out, name));
  published.push({ file: `/data/${name}`, description });
}

const manifestSrc = join(repo, "runs", meta.run_id, "manifest.json");
if (existsSync(manifestSrc)) {
  copyFileSync(manifestSrc, join(out, "manifest.json"));
  published.push({
    file: "/data/manifest.json",
    description: "The run manifest, written before any score was computed.",
  });
}

writeFileSync(
  join(out, "index.json"),
  JSON.stringify(
    {
      run_id: meta.run_id,
      prompt_set_sha256: meta.prompt_set_sha256,
      licence:
        "Code MIT; prompts and scores carry their upstream licences, see /data/provenance.json",
      files: published,
    },
    null,
    1
  ) + "\n"
);
console.log(`published ${published.length + 1} artifacts -> public/data/`);

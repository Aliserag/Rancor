# Seed-source research addendum (2026-08-18)

Agent-researched extension of `docs/RESEARCH.md` §1, verified against
fetched primary sources (HF API license metadata, GitHub API SPDX, raw
data files) on 2026-08-18. Human review required before any source's
items enter `prompts/v1.0/`. Nothing here overrides the hard rule:
items come only from licensed upstream data (adapted, attributed) or
team-written with attested-source citations.

## License gate for a redistributable Rancor release

SHIP-SAFE (verified): BBQ CC-BY-4.0 · HateCheck CC-BY-4.0 ·
XSTest CC-BY-4.0 · CLEAR-Bias Apache-2.0 ·
SocialStigmaQA CDLA-Permissive-2.0 ·
DiscrimEval CC-BY-4.0 (templates only; no religion attribute) ·
OR-Bench CC-BY-4.0 (non-identity control only).

CORRECTION (2026-08-18, extraction attempt): ProvoQ is HF-gated
despite its CDLA-Permissive-2.0 license metadata; file access requires
authenticated acceptance. Skipped for v1.0; usable later if the owner
accepts access on their HF account.

BLOCKED: ToxiGen (no declared license; confirms the RESEARCH.md skip) ·
BOLD (NOASSERTION) · HolisticBias (repo-level NOASSERTION; verify
subdir license before use) · Multitarget-CONAN ("cannot be
redistributed" per README; taxonomy may inform team-written items
only) · FalseReject (CC-BY-NC; incompatible with release) ·
CrowS-Pairs / StereoSet (CC-BY-SA viral; StereoSet also has zero
Jewish items; both carry documented quality criticisms: Blodgett et
al., ACL 2021).

## Per-category seeding plan (updated)

| Category | Sources (license-clean) |
|---|---|
| stereotype_association | Abid anchors (in v1.0) · CLEAR-Bias religion split (Muslim-terrorism AND Jewish-greed framings, 10 base prompts/task; small but high quality) |
| dog_whistles | Genuine gap: CLEAR-Bias obfuscation variants partially; mostly team-written w/ attested sources (see TBD ledger) |
| biased_refusals | HateCheck Muslim slice (extracted) · XSTest `real_group_nons_discr` templates re-slotted over {group}, which filled the second axis's coverage gap · OR-Bench-hard as non-identity difficulty control |
| double_standards | BBQ templates (extracted) · XSTest ready-made Jewish/Muslim/Christian triplets (ids 280/287/300, 305/312/325) · CLEAR-Bias stereotype/counter-stereotype pairs |
| loaded_presuppositions | XSTest `contrast_discr` re-slotted ("Why should {group} people not …") · ProvoQ minority-stigma questions |
| agentic_scenarios | DiscrimEval's 70 CC-BY-4.0 scenario stems re-slotted with {group} (no religion upstream; mechanical re-fill, marginal-case "implicit" design as calibration model) · SocialStigmaQA 37 yes/no decision patterns |

## Key negative results

- **DiscrimEval has no religion attribute** (grep over `explicit.jsonl`:
  0 hits for muslim/jewish/christian/religio); template donor only.
- **StereoSet religion targets are Muslim/Bible/Brahmin only**: zero
  Jewish items; useless for the second axis the project then carried.
- **MIRAGE (arXiv:2606.16562) has no locatable data release** despite
  the paper claiming one; cite for design only (consistent with
  RESEARCH.md), and note it as closely-overlapping prior art for the
  agentic_scenarios design. Consider contacting the authors.
- Supporting citation for biased_refusals on BOTH axes: "Omissive Bias
  in Religious Representation" (arXiv:2605.24319, 2026) reports refusal
  rates spiking for Judaism and Islam specifically.

## Follow-ups (open)

1. Count Muslim/Jewish rows in ProvoQ CSV and SocialStigmaQA
   `templates/stigmas.csv` before committing to those extractors.
2. Check `ResponsibleNLP` subdir license for HolisticBias descriptors
   (richest Jewish/Muslim descriptor vocabulary if usable).
3. Email MIRAGE authors re: promised data + harness.
4. Extractors implemented: BBQ, HateCheck, XSTest (this commit);
   next candidates: CLEAR-Bias (parquet), DiscrimEval stems,
   SocialStigmaQA patterns.

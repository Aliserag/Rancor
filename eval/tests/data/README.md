# Vendored upstream test samples

Real records quoted verbatim from licensed upstream datasets, vendored so
extraction-transform tests run without network. These are upstream INPUTS
(CC-BY-4.0 data), not fabricated model output — permitted under standing
rule 1.

- `bbq_religion_sample.jsonl` — first two lines of
  https://raw.githubusercontent.com/nyu-mll/BBQ/main/data/Religion.jsonl
  (BBQ, Parrish et al., ACL Findings 2022, CC-BY-4.0), fetched 2026-08-18.
- `hatecheck_sample.jsonl` — two rows of HateCheck's test_suite_cases.csv
  (Röttger et al., ACL 2021, CC-BY-4.0), as served by the Paul/hatecheck
  Hugging Face mirror (JSON row form), fetched 2026-08-18.

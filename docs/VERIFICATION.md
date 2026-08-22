# TBD-ledger verification addendum (2026-08-18)

Agent-verified findings for the human tasks in `docs/RESEARCH.md` §5.
Everything below is sourced and dated.

## 1. Runnymede Trust islamophobia reference: CONFIRMED, adopt

- 1997 "Islamophobia: A Challenge for Us All" (Commission on British
  Muslims and Islamophobia):
  https://www.runnymedetrust.org/publications/islamophobia-a-challenge-for-us-all
- 2017 "Islamophobia: Still a challenge for us all" (20th anniversary):
  https://www.runnymedetrust.org/publications/islamophobia-still-a-challenge-for-us-all
- Use the 1997 eight-pair "open vs closed views of Islam" framework as
  the trope taxonomy (pull exact pair wording from the 1997 PDF before
  quoting) and the 2017 "anti-Muslim racism" definition. No
  contested-geopolitics entanglement; 28-year citation history.

## 2. Source-URL reachability (checked 2026-08-18)

ajc.org returned 403 to our fetcher and some civil-rights-organisation
glossary deep links were redirect-unstable. Those sources concerned the removed second axis; no
shipped item cites ajc.org. Shipped items' source URLs resolve, with the
GNCI-supplied document disclosed per item as not independently resolvable.

## 3. Related-work claim (verified)

The claim wording, tied to what Rancor actually is:

> As of August 2026 we could not find a public leaderboard scoring frontier
> language models on how they *handle* anti-Muslim hate material (whether
> they refuse it, correct it, launder it or amplify it) against a frozen,
> publicly hashed prompt set, with every model response and every judge
> rationale published, and rerunnable on demand against new model snapshots.

The hedge is deliberate: "we could not find", not "none exists".

## 4. HateCheck target-group coverage: CONFIRMED with a nuance

English HateCheck's 7 groups exclude Jewish people (confirmed against
repo + paper). BUT Multilingual HateCheck (WOAH 2022, CC-BY-4.0,
github.com/rewire-online/multilingual-hatecheck) includes Jews in 5 of
10 languages (Arabic, German, Polish, Portuguese, Spanish), none in
English. Correct claim: "HateCheck provides no English-language
Jewish-target coverage." An unqualified "HateCheck does not cover
Jewish people" is false. (MHC is a future seed option if v1.0's
English-only scope ever expands.)


## 5. Related-work scan (, single-axis claim)

The earlier version of this scan defended the retired multi-axis claim and
padded its table with benchmarks that do not measure anti-Muslim hate at
all. Rebuilt here around the only two efforts that are genuinely comparable.

**The head-to-head is MIRAGE** (arXiv 2606.16562). Verified columns from the
earlier scan:

| | MIRAGE | Rancor |
|---|---|---|
| Axis | anti-Muslim only | anti-Muslim only |
| Open method | yes (paper) | yes (repo + spec) |
| Public prompt set | promised, not released at scan time | frozen, public, SHA-256 hashed |
| Per-response transcripts | no | every response, plus all three judge rationales |
| Construct | bias across reasoning and agentic conditions | whether a model resists, corrects, launders or amplifies hate material |

MIRAGE is the closest work: anti-Muslim, open in method, covering agentic
conditions. Our distinction is the artifact, not
the topic: MIRAGE reports a study of a moment, Rancor is a standing
instrument that can be re-run against a model released tomorrow and
publishes every response it scored.

**The other genuinely open effort is CEFE-AI AllFaith** (May 2026,
BYU/Baylor/Notre Dame/Yeshiva; GitHub + Kaggle + two arXiv papers): 14
faiths, public prompt set, partial transcripts. Different construct.
AllFaith measures conversion bias and omissive bias, meaning whether a model
is even-handed toward religions and whether it mentions them at all. Rancor
measures handling of hate material aimed at a group.

**Not comparators.** None of these measure anti-Muslim hate:

- **The largest comparable single-axis index** (Jan 2026): covers a
  different form of religious hate, not anti-Muslim hate.
- **MLCommons AILuminate**: hate is 1 of 12 undifferentiated hazards, prompt set withheld.
- **HELM Safety v1.0** (Nov 2024): broad safety suite, static snapshot.

They are context for why hate benchmarking is coarse today, not
comparators.

**Prior art on the finding, not on the instrument.** Abid, Farooqi & Zou
(AIES 2021, arXiv:2101.05783), whose completion anchors are in the prompt
set, and Hemmatian and Varshney (arXiv:2208.04417), which found the association
survives debiasing and resurfaces through Muslim names. We are not first to
notice the bias. We are first, as far as this scan could find, to make
measuring it standing, checkable and rerunnable.

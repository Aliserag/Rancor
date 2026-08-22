"""BBQ extraction transform, tested on vendored verbatim upstream records
(see tests/data/README.md) — no network."""

from __future__ import annotations

from rancor.axes import AxisConfig
from rancor.extract import bbq

from .conftest import load_jsonl

AXIS = AxisConfig(
    axis_id="test_axis",
    display_name="Test Axis",
    focal_group="Muslim",
    comparison_groups=[
        {"group": "Christian", "rationale": "t"},
        {"group": "Jewish", "rationale": "t"},
        {"group": "atheist", "rationale": "t"},
    ],
)

# Synthetic template-CSV row exercising the parser/transform only (the
# real CSV's schema was verified upstream; this is test input, not data).
SYNTH_CSV = (
    "needs_val,Q_id,Category,Ambiguous_Context,Disambiguating_Context,Lexical_diversity,"
    "Question_negative_stereotype,Question_non_negative,Answer_negative,Answer_non_negative,"
    "Relevant_social_values,Known_stereotyped_groups,Stated_gender_info,Notes\n"
    ',1,Religion ,"A {{NAME1}} person and {{NAME2}} person lost a {{WORD1}}.",'
    '"The {{NAME1}} person found it.","WORD1: [bag, case]",'
    "Who caused trouble?,Who helped?,The {{NAME1}} one,The {{NAME2}} one,"
    'violence,"[""Muslim""]",,https://example.invalid/citation\n'
)


def test_parse_templates_csv():
    (row,) = bbq.parse_templates_csv(SYNTH_CSV)
    assert row["qid"] == "1"
    assert row["category"] == "Religion"  # upstream trailing space stripped
    assert row["known_groups"] == ["Muslim"]
    assert row["notes"] == "https://example.invalid/citation"


def test_cleanup_surface_repairs_transform_artifacts():
    from rancor.extract.bbq import _cleanup_surface

    assert _cleanup_surface("TSA pulled over a another person") == "TSA pulled over another person"
    assert _cleanup_surface("The another man was released") == "The other man was released"
    assert (
        _cleanup_surface("loud house party, one another and one {group}.")
        == "loud house party, one of them {group}."
    )
    assert _cleanup_surface("making sure people people were safe") == (
        "making sure people were safe"
    )
    assert _cleanup_surface("with with another man") == "with another man"
    assert _cleanup_surface("my another friend and my {group} friend") == (
        "my other friend and my {group} friend"
    )
    assert _cleanup_surface(
        "Two politicians, one another man and the other a {group} man, were debating."
    ) == "Two politicians, one of them a {group} man, were debating."
    assert _cleanup_surface("a group of {group} men and another group of another men") == (
        "a group of {group} men and another group of men"
    )
    assert _cleanup_surface("shared by a person who's {group} and a person who's another.") == (
        "shared by a person who's {group} and another person."
    )
    # no false positives on clean text
    clean = "A {group} person and another person were both seen fleeing."
    assert _cleanup_surface(clean) == clean


def test_word_fills_first_option():
    fills = bbq.parse_word_fills("WORD1: [luggage, bag, baggage]; WORD2: [released, let go]")
    assert fills == {"WORD1": "luggage", "WORD2": "released"}


def test_template_candidates_transform():
    items = bbq.template_candidates(bbq.parse_templates_csv(SYNTH_CSV), AXIS)
    assert len(items) == 4  # 2 polarities x 2 context conditions
    by_id = {i.id: i for i in items}
    ambig = by_id["test_axis_ds_bbq_t1_neg_ambig"]
    assert ambig.template == "A {group} person and another person lost a bag. Who caused trouble?"
    assert ambig.groups == ["Muslim", "Christian", "Jewish", "atheist"]
    assert ambig.is_counterfactual
    assert "cannot be determined" in ambig.rubric_notes
    assert "CC-BY-4.0" in ambig.attribution
    disambig = by_id["test_axis_ds_bbq_t1_neg_disambig"]
    assert disambig.template == (
        "A {group} person and another person lost a bag. "
        "The {group} person found it. Who caused trouble?"
    )
    # non-focal template rows are skipped entirely
    other_axis = AXIS.model_copy(update={"focal_group": "Hindu"})
    assert bbq.template_candidates(bbq.parse_templates_csv(SYNTH_CSV), other_axis) == []


def test_row_stats_on_vendored_records():
    records = load_jsonl("bbq_religion_sample.jsonl")
    stats = bbq.row_stats(records, "Muslim")
    assert stats == {"total": 2, "by_template": 2, "by_answer": 2, "union": 2}
    assert bbq.row_stats(records, "Jewish")["by_template"] == 0  # answer option only
    assert bbq.row_stats(records, "Jewish")["by_answer"] == 2


def test_unknown_answer_invariant_on_vendored_records():
    """BBQ invariant (verified over all 1200 upstream rows): the unknown
    option is correct iff context_condition == ambig."""
    for record in load_jsonl("bbq_religion_sample.jsonl"):
        unknown = bbq.unknown_answer_index(record)
        if record["context_condition"] == "ambig":
            assert record["label"] == unknown
        else:
            assert record["label"] != unknown


def test_unknown_options_are_bbq_canonical_ten():
    assert len(bbq.UNKNOWN_OPTIONS) == 10
    assert "Cannot be determined" in bbq.UNKNOWN_OPTIONS

"""Validator: counterfactual hygiene, axis symmetry, planted bad data.

The two planted-rejection tests are explicit SPEC M1 acceptance checks.
"""

from __future__ import annotations

import yaml

from rancor.validate import validate_prompt_set, validate_symmetry

from .conftest import synthetic_item


def _append_item(prompts_root, axis_id: str, category: str, item: dict) -> None:
    path = prompts_root / "axes" / axis_id / f"{category}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw.setdefault("items", []).append(item)
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")


def _first_axis(prompts_root) -> str:
    return min(p.name for p in (prompts_root / "axes").iterdir() if p.is_dir())


def test_repo_prompt_set_is_valid(repo_prompts):
    assert validate_prompt_set(repo_prompts) == []


def test_planted_identity_token_outside_slot_rejected(prompts_copy):
    """SPEC M1: identity token outside the {group} slot must be rejected."""
    axis = _first_axis(prompts_copy)
    lexicon = yaml.safe_load(
        (prompts_copy / "axes" / axis / "identity_lexicon.yaml").read_text()
    )
    a_token = next(iter(lexicon["tokens"].values()))[0]
    _append_item(
        prompts_copy,
        axis,
        "dog_whistles",
        synthetic_item(
            "planted_bad_item",
            template=f"A statement about {a_token} people with a {{group}} slot",
        ),
    )
    errors = validate_prompt_set(prompts_copy)
    assert any("planted_bad_item" in e and "identity token" in e for e in errors)


def test_focal_group_must_lead_the_group_list(prompts_copy):
    """E2E finding N1: scoring treats groups[0] as the focal
    group; an item whose group list starts with another group silently
    scores the WRONG group as focal for that axis."""
    axis = _first_axis(prompts_copy)
    config = yaml.safe_load((prompts_copy / "axes" / axis / "axis.yaml").read_text())
    other = config["comparison_groups"][0]["group"]
    _append_item(
        prompts_copy,
        axis,
        "biased_refusals",
        synthetic_item(
            "planted_wrong_focal",
            groups=[other, config["focal_group"]],
        ),
    )
    errors = validate_prompt_set(prompts_copy)
    assert any("planted_wrong_focal" in e and "focal" in e for e in errors)


def test_planted_axis_special_case_rejected(prompts_copy):
    """SPEC M1: a bespoke per-axis config field must be rejected."""
    axis = _first_axis(prompts_copy)
    config_path = prompts_copy / "axes" / axis / "axis.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    raw["special_scoring_override"] = True  # planted special-case
    config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    errors = validate_prompt_set(prompts_copy)
    assert any("special_scoring_override" in e or "discovery failed" in e for e in errors)


def test_missing_category_file_breaks_symmetry(prompts_copy):
    axis = _first_axis(prompts_copy)
    (prompts_copy / "axes" / axis / "agentic_scenarios.yaml").unlink()
    errors = validate_symmetry(prompts_copy)
    assert any("missing category file" in e for e in errors)


def test_upstream_id_requires_attribution(prompts_copy):
    axis = _first_axis(prompts_copy)
    _append_item(
        prompts_copy,
        axis,
        "biased_refusals",
        synthetic_item("planted_unattributed", upstream_id="BBQ/Religion/999"),
    )
    errors = validate_prompt_set(prompts_copy)
    assert any("planted_unattributed" in e and "attribution" in e for e in errors)


def test_base_condition_required(prompts_copy):
    axis = _first_axis(prompts_copy)
    _append_item(
        prompts_copy,
        axis,
        "loaded_presuppositions",
        synthetic_item("planted_no_base", condition_variants=["cot"]),
    )
    errors = validate_prompt_set(prompts_copy)
    assert any("planted_no_base" in e and "base" in e for e in errors)


def test_unresolved_shared_trope_id(prompts_copy):
    axis = _first_axis(prompts_copy)
    _append_item(
        prompts_copy,
        axis,
        "stereotype_association",
        synthetic_item("planted_trope_ref", shared_trope_id="no_such_trope"),
    )
    errors = validate_prompt_set(prompts_copy)
    assert any("planted_trope_ref" in e and "no_such_trope" in e for e in errors)


def test_repo_prompt_set_passes_strict_release_gates(repo_prompts):
    """As of the 2026-08-18 promotions, every per-category floor is met on
    every axis and every shared trope is instantiated in >=2 axes."""
    assert validate_prompt_set(repo_prompts, strict=True) == []


def test_strict_mode_enforces_release_gates(tmp_path):
    """Strict mode flags below-floor categories and under-instantiated
    shared tropes (synthetic below-floor pack)."""
    import yaml as _yaml

    from .conftest import make_axis_pack

    prompts = tmp_path / "v1.0"
    make_axis_pack(
        prompts,
        "axis_x",
        items_by_category={
            "stereotype_association": [
                synthetic_item("only_item", shared_trope_id="trope_lonely")
            ]
        },
    )
    tropes_dir = prompts / "shared_tropes"
    tropes_dir.mkdir()
    (tropes_dir / "tropes.yaml").write_text(
        _yaml.safe_dump(
            {
                "tropes": [
                    {
                        "id": "trope_lonely",
                        "template": "A synthetic trope about {group}.",
                        "control": "A synthetic control.",
                        "source": "https://example.invalid",
                        "rationale": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert validate_prompt_set(prompts) == []  # development mode passes
    errors = validate_prompt_set(prompts, strict=True)
    assert any("hard floor" in e for e in errors)
    assert any("parity view needs >=2" in e for e in errors)

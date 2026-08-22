"""The MCP themes reference: axis-generic, cited, and honest when absent.

The themes file is data keyed by axis filename (standing rule 7: no axis is
special-cased in code); it lives outside the frozen prompt set, so shipping
or amending it never touches the hash.
"""

from pathlib import Path

import yaml

from rancor import mcp_server

REPO = Path(__file__).resolve().parents[2]


def test_themes_file_is_cited_and_well_formed() -> None:
    path = REPO / "themes" / "islamophobia.yaml"
    assert path.exists(), "themes/islamophobia.yaml should ship"
    data = yaml.safe_load(path.read_text())
    assert data["axis"] == "islamophobia"
    assert "not independently resolvable" in data["source_note"]
    themes = data["themes"]
    assert len(themes) >= 10
    ids = [t["id"] for t in themes]
    assert len(ids) == len(set(ids)), "duplicate theme ids"
    for t in themes:
        assert t["name"] and t["description"], t["id"]
        assert t["sources"], f"{t['id']} has no source"
        for src in t["sources"]:
            assert src["doc"] and src["pages"], f"{t['id']} source incomplete"


def test_list_themes_tool_serves_the_reference() -> None:
    out = mcp_server.list_themes("islamophobia")
    assert out["axis"] == "islamophobia"
    assert len(out["themes"]) >= 10
    assert "GNCI" in out["source_note"]


def test_list_themes_is_honest_about_a_missing_axis() -> None:
    out = mcp_server.list_themes("no-such-axis")
    assert "error" in out

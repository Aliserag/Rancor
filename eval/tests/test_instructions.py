"""The instruction files must be in the repository, and must be true.

CLAUDE.md was gitignored under "local working documents" while manifest.py,
export.py, judge.py and run.py all cite its rules by number. The rules the
code appeals to were not in the repository the code ships in, and its command
list had drifted to invocations that silently fail (`cd eval && pytest` misses
the root venv; running from eval/ makes load_dotenv see no .env).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE_GLOBS = ("eval/rancor/**/*.py", "site/tests/*.mjs", "eval/tests/*.py")


def tracked(rel: str) -> bool:
    return subprocess.run(
        ["git", "ls-files", "--error-unmatch", rel],
        cwd=REPO, capture_output=True, text=True, check=False,
    ).returncode == 0


def test_instruction_files_are_committed():
    for name in ("CLAUDE.md", "AGENTS.md", "SPEC.md"):
        assert (REPO / name).is_file(), f"{name} is missing"
        assert tracked(name), (
            f"{name} exists locally but is not committed — anyone cloning this "
            "repo, human or agent, works without it"
        )


def test_every_hard_rule_cited_in_source_exists():
    """Rule numbers are stable identifiers: append, never renumber."""
    claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    defined = {int(n) for n in re.findall(r"^(\d+)\. ", claude, flags=re.MULTILINE)}
    assert defined, "CLAUDE.md defines no numbered hard rules"

    cited: dict[int, str] = {}
    for pattern in SOURCE_GLOBS:
        for path in REPO.glob(pattern):
            for n in re.findall(r"hard rule (\d+)", path.read_text(encoding="utf-8")):
                cited[int(n)] = str(path.relative_to(REPO))

    missing = {n: where for n, where in cited.items() if n not in defined}
    assert not missing, (
        f"source cites hard rules that CLAUDE.md does not define: {missing}. "
        "Rules were renumbered; restore the numbering and append instead."
    )


def test_make_targets_claude_md_names_exist():
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    targets = set(re.findall(r"^([a-zA-Z][\w-]*):", makefile, flags=re.MULTILINE))
    claimed = set(re.findall(r"`make ([\w-]+)`", (REPO / "CLAUDE.md").read_text()))
    assert claimed, "CLAUDE.md names no make targets"
    assert claimed <= targets, f"CLAUDE.md names missing targets: {claimed - targets}"


def test_scripts_claude_md_names_exist():
    claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    for rel in re.findall(r"`?python3? (scripts/[\w./-]+)`?", claude):
        assert (REPO / rel).is_file(), f"CLAUDE.md names missing script {rel}"

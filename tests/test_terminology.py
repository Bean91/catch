"""Session 32: the word shown to people is "training issue". The stored fields keep their names (niggle_area, niggle_severity, the
niggle_flag_min_days setting) so no data moves — only words a person or the AI reads are checked here."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The word on its own, not as part of an identifier such as niggle_area / niggleArea / NIGGLE_AREAS.
WORD = re.compile(r"(?<![\w])niggles?(?![\w])", re.IGNORECASE)
USER_FACING_TEXT = [
    ROOT / "catch" / "coach" / "system_prompt.md",
    ROOT / "docs" / "legal" / "privacy-policy.md",
    ROOT / "docs" / "legal" / "ai-data-sharing.md",
]


def test_no_user_facing_document_or_prompt_says_niggle():
    offenders = [f"{p.relative_to(ROOT)}:{i}" for p in USER_FACING_TEXT for i, line in enumerate(p.read_text().splitlines(), 1) if WORD.search(line)]
    assert offenders == []


def test_no_string_literal_in_the_app_or_its_api_says_niggle():
    """String literals (what reaches a screen, an error message, the AI or an MCP client) in the web app and the backend — comments
    and identifiers are allowed to keep the old name."""
    literal = re.compile(r"""(["'`])((?:(?!\1).)*)\1""")
    offenders = []
    files = [*(ROOT / "web" / "src").rglob("*.tsx"), *(ROOT / "web" / "src").rglob("*.ts"), *(ROOT / "catch").rglob("*.py")]
    for path in files:
        if "static" in path.parts:
            continue
        for i, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0] if path.suffix == ".py" else re.sub(r"//.*$", "", line)
            for _, text in literal.findall(code):
                if WORD.search(text):
                    offenders.append(f"{path.relative_to(ROOT)}:{i}")
            if path.suffix == ".tsx" and re.search(r">[^<{]*\bniggle", code, re.IGNORECASE):
                offenders.append(f"{path.relative_to(ROOT)}:{i}")
    assert offenders == []


def test_the_mcp_tool_description_says_training_issue():
    text = (ROOT / "catch" / "mcp_server" / "server.py").read_text()
    assert "training-issue flag" in text and not WORD.search(text)

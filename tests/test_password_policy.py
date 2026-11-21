"""Session 32: one password policy, stated identically wherever it is set. The browser's checklist (web/src/lib/passwordPolicy.ts) is
compared with the same fixture by vitest; Supabase Auth enforces it from the dashboard settings these docs tell the operator to set."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "tests" / "fixtures" / "auth" / "password_policy.json").read_text())


def test_the_fixture_is_the_documented_supabase_setting():
    assert POLICY["min_length"] == POLICY["supabase"]["minimum_password_length"] == 8
    assert POLICY["supabase"]["password_requirements"] == "lower_upper_letters_digits_symbols"
    assert POLICY["rules"] == ["length", "lowercase", "uppercase", "digit", "symbol"]


def test_every_operator_doc_states_the_same_policy():
    req = POLICY["supabase"]["password_requirements"]
    for doc in ("docs/public-setup.md", "docs/supabase-setup.md", "docs/security.md"):
        text = (ROOT / doc).read_text()
        assert req in text or "lowercase, uppercase letters, digits and symbols" in text, doc
        assert "≥ 12" not in text, f"{doc} still asks for a different minimum"

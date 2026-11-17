"""Session 26: boards, eligibility, age categories, ranking and ties, validation, and the public serializer's allowlist."""

from datetime import date

import pytest

from catch.analytics import leaderboards as lb


def row(entry_id, athlete, value, verification="verified", public_id=None):
    return {"entry_id": entry_id, "athlete_key": athlete, "public_id": public_id or athlete, "value": value, "verification": verification, "tiebreak": lb.tiebreak_for(entry_id)}


# ---- eligibility: exact, never the test center's 2% tolerance

def test_a_2000m_must_be_exactly_2000m():
    ok = lb.eligible_board(distance_m=2000, duration_s=390.4, workout_type="FixedDistanceSplits", erg_type="rower")
    assert ok == ("2000m", 3904)
    assert lb.eligible_board(distance_m=1960, duration_s=390.4, workout_type="FixedDistanceSplits", erg_type="rower") is None
    assert lb.eligible_board(distance_m=2001, duration_s=390.4, workout_type="FixedDistanceSplits", erg_type="rower") is None


def test_a_just_row_or_interval_or_other_erg_is_never_ranked():
    base = dict(distance_m=2000, duration_s=400)
    assert lb.eligible_board(**base, workout_type="JustRow", erg_type="rower") is None
    assert lb.eligible_board(**base, workout_type="FixedDistanceInterval", erg_type="rower") is None
    assert lb.eligible_board(**base, workout_type="FixedDistanceSplits", erg_type="skierg") is None
    assert lb.eligible_board(**base, workout_type="FixedDistanceSplits", erg_type="rower", has_intervals=True) is None


def test_timed_boards_rank_distance_and_need_an_exact_duration():
    assert lb.eligible_board(distance_m=8123, duration_s=1800.0, workout_type="FixedTimeSplits", erg_type="rower") == ("30min", 8123)
    assert lb.eligible_board(distance_m=15000, duration_s=3600.0, workout_type="FixedTimeSplits", erg_type="rower") == ("60min", 15000)
    assert lb.eligible_board(distance_m=8123, duration_s=1795.0, workout_type="FixedTimeSplits", erg_type="rower") is None
    assert "30min_r20" not in lb.BOARDS


def test_a_typed_piece_has_no_workout_type_but_is_still_exact():
    assert lb.eligible_board(distance_m=2000, duration_s=420.1, is_piece=True) == ("2000m", 4201)
    assert lb.eligible_board(distance_m=1999, duration_s=420.1, is_piece=True) is None


# ---- ranking and ties

def test_standard_competition_ranking_with_a_tie():
    out = lb.rank_entries([row("a", "A", 4000), row("b", "B", 4100), row("c", "C", 4100), row("d", "D", 4200)], "2000m")
    assert [r["rank"] for r in out] == [1, 2, 2, 4]
    assert {r["athlete_key"] for r in out[1:3]} == {"B", "C"}


def test_a_timed_board_ranks_the_longest_distance_first():
    out = lb.rank_entries([row("a", "A", 8000), row("b", "B", 8200)], "30min")
    assert [(r["athlete_key"], r["rank"]) for r in out] == [("B", 1), ("A", 2)]


def test_one_best_entry_per_athlete_so_a_duplicate_submission_cannot_double_rank():
    out = lb.rank_entries([row("a1", "A", 4100), row("a2", "A", 4000), row("b", "B", 4050)], "2000m")
    assert [(r["athlete_key"], r["value"], r["rank"]) for r in out] == [("A", 4000, 1), ("B", 4050, 2)]


def test_a_tenth_of_a_second_separates_athletes_and_equal_tenths_tie():
    assert [r["rank"] for r in lb.rank_entries([row("a", "A", 3999), row("b", "B", 4000)], "2000m")] == [1, 2]
    assert [r["rank"] for r in lb.rank_entries([row("a", "A", 4000), row("b", "B", 4000)], "2000m")] == [1, 1]


def test_tie_order_is_a_hash_and_does_not_depend_on_input_order():
    rows = [row(f"e{i}", f"A{i}", 4000) for i in range(6)]
    assert [r["entry_id"] for r in lb.rank_entries(rows, "2000m")] == [r["entry_id"] for r in lb.rank_entries(list(reversed(rows)), "2000m")]


def test_unverified_rows_are_ranked_separately_and_never_displace_a_verified_one():
    rows = [row("v", "V", 4500), row("u", "U", 3000, "unverified"), row("l", "L", 3500, "provider_linked")]
    only = lb.rank_board(rows, "2000m", include_unverified=False)
    assert [r["entry_id"] for r in only["ranked"]] == ["v"] and only["unverified"] == []
    both = lb.rank_board(rows, "2000m", include_unverified=True)
    assert [r["entry_id"] for r in both["ranked"]] == ["v"]
    assert [(r["entry_id"], r["rank"]) for r in both["unverified"]] == [("u", 1), ("l", 2)]


def test_an_athlete_with_a_verified_entry_is_not_repeated_in_the_unverified_list():
    rows = [row("v", "V", 4500, public_id="p1"), row("u", "U", 3000, "unverified", public_id="p1")]
    assert lb.rank_board(rows, "2000m", True)["unverified"] == []


def test_the_athlete_key_counts_one_concept2_account_once_across_catch_accounts():
    assert lb.athlete_key("s", "concept2", "77", "alice") == lb.athlete_key("s", "concept2", "77", "bob")
    assert lb.athlete_key("s", None, None, "alice") != lb.athlete_key("s", None, None, "bob")


# ---- age categories

def test_age_on_handles_the_birthday_boundary():
    assert lb.age_on(date(2010, 6, 15), date(2026, 6, 14)) == 15
    assert lb.age_on(date(2010, 6, 15), date(2026, 6, 15)) == 16


def test_youth_boards_are_cumulative_under_boards():
    assert lb.memberships(14, None) == ["U15", "U16", "U17", "U18", "U19"]
    assert lb.memberships(15, None) == ["U16", "U17", "U18", "U19"]  # U16 = under 16
    assert lb.memberships(18, None) == ["U19"]
    assert lb.public_age_label(15, None) == "U16"


def test_adults_have_one_exclusive_band():
    assert lb.split_age(18) == (18, None)
    assert lb.split_age(19) == (None, "19-29")
    assert lb.split_age(29) == (None, "19-29") and lb.split_age(30) == (None, "30-39")
    assert lb.split_age(85) == (None, "80+")
    assert lb.memberships(None, "40-49") == ["40-49"]


def test_a_self_declared_under_band_never_lands_in_an_easier_band():
    years, band = lb.from_declared_label("U16")
    assert (years, band) == (15, None) and lb.memberships(years, band)[0] == "U16"
    assert lb.from_declared_label("50-59") == (None, "50-59")
    with pytest.raises(ValueError):
        lb.from_declared_label("U12")


def test_the_age_gate():
    def g(age, m=False, guardian=False):
        return lb.age_gate(age, has_min_age_attestation=m, has_guardian_attestation=guardian)

    assert g(12, True, True) == "below_minimum_age"
    assert g(None) == "age_attestation_required" and g(None, True) is None
    assert g(14, False) == "guardian_consent_required" and g(14, False, True) is None
    assert g(16) is None and g(40) is None


def test_minors_are_capped_to_year_precision():
    assert lb.effective_precision("day", True) == "year" and lb.effective_precision("month", True) == "year"
    assert lb.effective_precision("day", False) == "day" and lb.effective_precision("none", True) == "none"
    assert lb.is_minor(17, "concept2_profile") and not lb.is_minor(18, "concept2_profile")
    assert lb.is_minor(18, "self_declared")  # a declared "U19" could be 17
    assert lb.is_minor(None, None) is False


def test_dates_are_truncated_to_the_consented_precision():
    d = date(2026, 10, 14)
    assert lb.date_label(d, "none") is None
    assert lb.date_label(d, "year") == "2026" and lb.date_label(d, "month") == "2026-10" and lb.date_label(d, "day") == "2026-10-14"


# ---- validation

@pytest.mark.parametrize("bad", ["ab", "x" * 25, "Catch Admin", "concept2fan", "Moderator", "go to evil.com", "a@b.com", "http-rower", "bad!name"])
def test_bad_handles_are_refused(bad):
    with pytest.raises(ValueError):
        lb.validate_handle(bad)


def test_good_handles_are_normalised():
    assert lb.validate_handle("  River   Rower_9 ") == "River Rower_9"


def test_notes_are_short_and_link_free():
    assert lb.validate_note("  Felt good  ") == "Felt good" and lb.validate_note("   ") is None and lb.validate_note(None) is None
    with pytest.raises(ValueError):
        lb.validate_note("x" * 141)
    with pytest.raises(ValueError):
        lb.validate_note("see www.example.com")


# ---- the one serializer

def _entry(**kw):
    base = {"entry_id": "e1", "board_key": "2000m", "value": 3904, "verification": "verified", "age_label": None, "age_provenance": None, "weight_class": None, "date_label": None, "note": None}
    return {**base, **kw, "secret_internal": "must not appear", "provider_user_id": "77", "age_years": 14}


def test_the_serializer_emits_only_allowlisted_keys_whatever_it_is_handed():
    view = lb.public_entry_view(_entry(), {"public_id": "p1", "handle": "River", "display_mode": "handle", "owner_id": "alice", "dob": "2010-01-01"}, rank=1)
    assert set(view) <= set(lb.PUBLIC_RANKED_KEYS)
    assert "must not appear" not in str(view) and "2010" not in str(view) and "alice" not in str(view)
    assert view["result"] == "6:30.4" and view["split_500m"] == "1:37.6" and view["name"] == "River"


def test_anonymous_mode_hides_the_handle_and_labels_provenance():
    view = lb.public_entry_view(_entry(age_label="U16", age_provenance="self_declared"), {"public_id": "p1", "handle": "River", "display_mode": "anonymous"})
    assert view["name"] == lb.ANONYMOUS_NAME and "River" not in str(view)
    assert view["age_provenance"] == "self-declared"


def test_the_preview_hash_changes_when_anything_public_changes():
    a = lb.public_entry_view(_entry(), {"public_id": "p1", "handle": "River", "display_mode": "handle"})
    b = lb.public_entry_view(_entry(date_label="2026"), {"public_id": "p1", "handle": "River", "display_mode": "handle"})
    assert lb.preview_hash(a) == lb.preview_hash(dict(a)) and lb.preview_hash(a) != lb.preview_hash(b)

from __future__ import annotations

import json
from pathlib import Path

import pytest

from catch.analytics import planning as pl
from catch.analytics import workout_library as wl
from catch.analytics.erg_math import pace_from_watts

SEED = json.loads((Path(wl.__file__).resolve().parents[1] / "seed" / "workout_templates.json").read_text())


def _t(workout_type, structure, **kw):
    return {"name": "T", "workout_type": workout_type, "structure": structure, **kw}


def _paths(result):
    return {i["path"] for i in result["issues"]}


# --- validation per workout type ----------------------------------------------------------------


def test_every_type_has_a_valid_minimal_example():
    cases = {
        "erg_intervals": {"blocks": [{"reps": 4, "work_m": 500, "rest_s": 60}]},
        "steady_state": {"blocks": [{"reps": 1, "work_s": 3600}]},
        "rate_ladder": {"blocks": [{"reps": 1, "work_s": 240, "rate_min": 18, "rate_max": 18}, {"reps": 1, "work_s": 240, "rate_min": 20, "rate_max": 20}]},
        "distance_piece": {"blocks": [{"reps": 1, "work_m": 5000}]},
        "time_piece": {"blocks": [{"reps": 1, "work_s": 1800}]},
        "strength": {"strength_items": [{"exercise_id": 1, "target_sets": 3, "target_reps": 5}]},
        "on_water": {"blocks": [{"reps": 3, "work_s": 600, "rest_s": 180}]},
        "custom": {"blocks": [{"reps": 1, "work_s": 600}]},
    }
    assert set(cases) == set(wl.WORKOUT_TYPES)
    for wt, structure in cases.items():
        result = wl.validate_template(_t(wt, structure))
        assert result["ok"], (wt, result)


@pytest.mark.parametrize(
    "wt,structure,path",
    [
        ("erg_intervals", {"blocks": [{"reps": 1, "work_m": 500}]}, "structure.blocks"),
        ("steady_state", {"blocks": [{"reps": 2, "work_s": 600}]}, "structure.blocks"),
        ("steady_state", {"blocks": [{"reps": 1, "work_s": 600, "rest_s": 30}]}, "structure.blocks[0].rest_s"),
        ("rate_ladder", {"blocks": [{"reps": 1, "work_s": 240, "rate_min": 18}]}, "structure.blocks"),
        ("rate_ladder", {"blocks": [{"reps": 1, "work_s": 240}, {"reps": 1, "work_s": 240, "rate_min": 20}]}, "structure.blocks[0]"),
        ("distance_piece", {"blocks": [{"reps": 1, "work_s": 600}]}, "structure.blocks"),
        ("time_piece", {"blocks": [{"reps": 1, "work_m": 2000}]}, "structure.blocks"),
        ("strength", {"blocks": [{"reps": 1, "work_s": 60}], "strength_items": [{"exercise_id": 1}]}, "structure.blocks"),
        ("strength", {}, "structure.strength_items"),
        ("on_water", {}, "structure.blocks"),
        ("erg_intervals", {"strength_items": [{"exercise_id": 1}], "blocks": [{"reps": 2, "work_s": 60}]}, "structure.strength_items"),
    ],
)
def test_shape_rules_name_the_offending_path(wt, structure, path):
    result = wl.validate_template(_t(wt, structure))
    assert not result["ok"] and path in _paths(result)


@pytest.mark.parametrize(
    "block,path",
    [
        ({"reps": 0, "work_s": 60}, "structure.blocks[0].reps"),
        ({"reps": 101, "work_s": 60}, "structure.blocks[0].reps"),
        ({"reps": True, "work_s": 60}, "structure.blocks[0].reps"),
        ({"reps": 2}, "structure.blocks[0]"),
        ({"reps": 2, "work_s": 60, "work_m": 500}, "structure.blocks[0]"),
        ({"reps": 2, "work_s": -5}, "structure.blocks[0].work_s"),
        ({"reps": 2, "work_m": 200000}, "structure.blocks[0].work_m"),
        ({"reps": 2, "work_s": 60, "rest_s": -1}, "structure.blocks[0].rest_s"),
        ({"reps": 2, "work_s": 60, "rate_min": 5}, "structure.blocks[0].rate_min"),
        ({"reps": 2, "work_s": 60, "rate_min": 30, "rate_max": 20}, "structure.blocks[0].rate_min"),
        ({"reps": 2, "work_m": 500, "split_s": 20}, "structure.blocks[0].split_s"),
        ({"reps": 2, "work_m": 500, "watts": 5}, "structure.blocks[0].watts"),
        ({"reps": 2, "work_m": 500, "split_s": 100, "watts": 300}, "structure.blocks[0]"),
        ({"reps": 2, "work_s": 60, "zone": "ZZ"}, "structure.blocks[0].zone"),
        ({"reps": 2, "work_s": 60, "bogus": 1}, "structure.blocks[0].bogus"),
    ],
)
def test_block_rules(block, path):
    result = wl.validate_template(_t("custom", {"blocks": [block]}))
    assert path in _paths(result)


def test_top_level_field_rules():
    bad = {"name": "", "workout_type": "nope", "difficulty": "brutal", "target_zone": "XX", "tags": ["a"] * 11, "structure": {"x": 1}}
    paths = _paths(wl.validate_template(bad))
    assert {"name", "workout_type", "difficulty", "target_zone", "tags", "structure"} <= paths
    assert "session_type" in _paths(wl.validate_template(_t("strength", {"strength_items": [{"exercise_id": 1}]}, session_type="erg")))
    assert not wl.validate_template(_t("custom", {}, description=""))["ok"]
    assert wl.validate_template(_t("custom", {}, description="Free-form notes"))["ok"]


def test_validation_never_mutates_its_input():
    tpl = _t("erg_intervals", {"blocks": [{"reps": 4, "work_m": 500}]})
    before = json.dumps(tpl, sort_keys=True)
    wl.validate_template(tpl)
    wl.summarize_template(tpl["structure"])
    assert json.dumps(tpl, sort_keys=True) == before


def test_segment_rules():
    seg = {"warmup": {"duration_min": 10, "distance_m": 2000}, "cooldown": {"duration_min": -1}, "blocks": [{"reps": 2, "work_s": 60}]}
    paths = _paths(wl.validate_template(_t("custom", seg)))
    assert "structure.warmup" in paths and "structure.cooldown.duration_min" in paths


# --- interval arithmetic ---------------------------------------------------------------------------


def test_four_by_500_with_rest_has_three_rests():
    s = wl.summarize_template({"blocks": [{"reps": 4, "work_m": 500, "rest_s": 60}]})
    assert s["rest_duration_s"] == 180.0 and s["work_distance_m"] == 2000.0 and s["rep_count"] == 4
    assert s["total_duration_s"] is None and s["duration_basis"] == "unknown"


def test_timed_blocks_are_exact_and_zone_minutes_exclude_rest():
    s = wl.summarize_template({"blocks": [{"reps": 6, "work_s": 180, "rest_s": 120, "zone": "AT"}]})
    assert s["total_duration_s"] == 6 * 180 + 5 * 120 and s["duration_basis"] == "exact"
    assert s["zone_minutes"] == {"AT": 18.0}
    assert s["work_rest_ratio"] == pytest.approx(1080 / 600)


def test_ladder_keeps_rest_between_steps_but_not_after_the_last():
    blocks = [{"reps": 1, "work_s": 240, "rest_s": 60, "rate_min": r, "rate_max": r} for r in (18, 20, 22)]
    s = wl.summarize_template({"blocks": blocks})
    assert s["rest_duration_s"] == 120.0 and s["total_duration_s"] == 720 + 120


def test_multi_block_rest_drops_only_the_final_rep():
    s = wl.summarize_template({"blocks": [{"reps": 2, "work_s": 60, "rest_s": 30}, {"reps": 2, "work_s": 120, "rest_s": 90}]})
    assert s["rest_duration_s"] == 30 * 2 + 90 * 1


def test_warmup_and_cooldown_add_to_the_total_only_when_timed():
    s = wl.summarize_template({"warmup": {"duration_min": 10}, "blocks": [{"reps": 1, "work_s": 600}], "cooldown": {"duration_min": 5}})
    assert s["total_duration_s"] == 600 + 900 and s["warmup_duration_s"] == 600 and s["cooldown_duration_s"] == 300
    d = wl.summarize_template({"warmup": {"distance_m": 2000}, "blocks": [{"reps": 1, "work_s": 600}]})
    assert d["total_duration_s"] is None  # a distance warm-up has no honest duration


def test_split_or_watts_target_makes_a_distance_duration_an_estimate():
    s = wl.summarize_template({"blocks": [{"reps": 4, "work_m": 500, "rest_s": 60, "split_s": 110}]})
    assert s["duration_basis"] == "estimated" and s["total_duration_s"] == pytest.approx(4 * 110 + 180)
    w = wl.summarize_template({"blocks": [{"reps": 1, "work_m": 2000, "watts": 250}]})
    assert w["total_duration_s"] == pytest.approx(2000 / 500 * pace_from_watts(250))
    t = wl.summarize_template({"blocks": [{"reps": 1, "work_s": 600, "split_s": 120}]})
    assert t["duration_basis"] == "exact" and t["total_distance_m"] == pytest.approx(2500.0)
    assert t["distance_basis"] == "estimated"


def test_distance_unknown_for_a_timed_block_without_a_pace():
    s = wl.summarize_template({"blocks": [{"reps": 1, "work_s": 600}]})
    assert s["total_distance_m"] is None and s["distance_basis"] == "unknown"


def test_strength_and_empty_templates_have_no_totals():
    s = wl.summarize_template({"strength_items": [{"exercise_id": 1}]})
    assert s["total_duration_s"] is None and s["strength_exercise_count"] == 1
    assert wl.summarize_template({})["total_duration_s"] is None


def test_signature_matches_the_piece_interval_convention():
    from catch.analytics.piece_intervals import expand_repeat, interval_signature

    tpl = {"blocks": [{"reps": 4, "work_m": 500, "rest_s": 60}]}
    assert wl.template_signature(tpl) == interval_signature(expand_repeat(4, work_distance_m=500, rest_duration_s=60)) == "4x500m/r60"
    assert wl.template_signature({}) is None


# --- calendar conversion -----------------------------------------------------------------------------


def _planned_input(fields):
    return {"session_type": fields["session_type"], "duration_min": fields.get("duration_min"), "distance_m": fields.get("distance_m"),
            "target_zone": fields.get("target_zone"), "structure": fields.get("structure") or [], "status": "planned"}


@pytest.mark.parametrize("workout_type", wl.WORKOUT_TYPES)
def test_planned_structure_round_trips_planning_validation_for_every_type(workout_type):
    structures = {
        "erg_intervals": {"warmup": {"duration_min": 10}, "blocks": [{"reps": 4, "work_m": 500, "rest_s": 60, "split_s": 105}]},
        "steady_state": {"blocks": [{"reps": 1, "work_s": 3600, "zone": "UT2", "rate_min": 18, "rate_max": 20}]},
        "rate_ladder": {"blocks": [{"reps": 1, "work_s": 240, "rest_s": 60, "rate_min": 18}, {"reps": 1, "work_s": 240, "rate_min": 24}]},
        "distance_piece": {"blocks": [{"reps": 1, "work_m": 5000}]},
        "time_piece": {"blocks": [{"reps": 1, "work_s": 1800}]},
        "strength": {"strength_items": [{"exercise_id": 1}]},
        "on_water": {"blocks": [{"reps": 3, "work_s": 600, "rest_s": 180, "rate_min": 20, "rate_max": 22}]},
        "custom": {"blocks": [{"reps": 1, "work_s": 600}]},
    }
    st = wl.default_session_type(workout_type)
    tpl = {"name": "N", "workout_type": workout_type, "session_type": st, "structure": structures[workout_type], "description": "d"}
    assert wl.validate_template(tpl)["ok"]
    fields = wl.to_planned_fields(tpl)
    pl.validate_planned_fields(fields)
    if "structure" in fields:
        assert pl.validate_structure(fields["structure"])


@pytest.mark.parametrize("entry", SEED, ids=lambda e: e["external_id"])
def test_every_seeded_example_is_valid_and_labelled_as_an_example(entry):
    tpl = {**entry, "session_type": wl.default_session_type(entry["workout_type"])}
    assert wl.validate_template(tpl)["ok"], entry["external_id"]
    assert entry["external_id"].startswith("example-") and "example" in entry["tags"]
    assert entry["name"].startswith("Example")
    assert len({e["external_id"] for e in SEED}) == len(SEED)


@pytest.mark.parametrize("entry", SEED, ids=lambda e: e["external_id"])
def test_planner_totals_agree_with_the_template_summary(entry):
    structure = entry["structure"]
    tpl = {**entry, "session_type": wl.default_session_type(entry["workout_type"])}
    summary = wl.summarize_template(structure, entry.get("target_zone"))
    fields = wl.to_planned_fields(tpl)
    totals = pl.planned_totals([{**_planned_input(fields)}])
    if summary["total_duration_s"] is not None:
        assert totals["minutes"] == pytest.approx(summary["total_duration_s"] / 60.0)
    else:
        assert "duration_min" not in fields
    for zone, minutes in summary["zone_minutes"].items():
        assert totals["zone_minutes"][zone] == pytest.approx(minutes, abs=0.01)
    if summary["total_distance_m"] is not None:
        assert totals["distance_m"] == pytest.approx(summary["total_distance_m"])


def test_planned_fields_carry_targets_in_notes_and_only_known_numbers():
    tpl = {"name": "Ladder", "workout_type": "rate_ladder", "session_type": "erg", "purpose": "Rate control",
           "structure": {"blocks": [{"reps": 1, "work_s": 240, "rest_s": 60, "rate_min": 18, "rate_max": 20, "split_s": 125.5}, {"reps": 1, "work_s": 240, "watts": 200}]}}
    f = wl.to_planned_fields(tpl)
    assert f["structure"][0]["note"] == "18-20 spm; split 2:05.5"
    assert f["structure"][1]["note"] == "200 W" and f["intensity_note"] == "Rate control"
    assert f["duration_min"] == pytest.approx((480 + 60) / 60)
    no_duration = wl.to_planned_fields({"name": "x", "workout_type": "distance_piece", "session_type": "erg", "structure": {"blocks": [{"reps": 1, "work_m": 5000}]}})
    assert "duration_min" not in no_duration and no_duration["distance_m"] == 5000.0

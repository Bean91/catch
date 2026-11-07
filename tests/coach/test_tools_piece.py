from __future__ import annotations

from datetime import datetime, timezone

from catch.coach import tools
from catch.core.models import Activity, CanonicalActivity
from catch.sync.matching import run_matching
from catch.sync.samples import store_samples

T0 = datetime(2026, 7, 1, 7, tzinfo=timezone.utc)


def _seed_activity(session) -> Activity:
    a = Activity(source="garmin", external_id="g1", type="rowing_v2", start=T0, duration=3600.0, sport_family="rowing")
    session.add(a)
    session.commit()
    c = CanonicalActivity(sport_family="rowing")
    session.add(c)
    session.commit()
    a.canonical_id = c.id
    session.add(a)
    session.commit()
    store_samples(session, a.id, start=T0, hr=[130.0] * 3600, power=[None] * 3600, cadence=[20.0] * 3600)
    return a


def test_add_piece_previews_the_tasks_own_example_before_saving(session):
    activity = _seed_activity(session)
    text = "my 2k was 6:32.4, splits 1:36.8, 1:38.9, 1:39.0, 1:37.7"

    preview = tools.call_tool(session, "add_piece", {"piece_type": "2000m", "canonical_id": activity.canonical_id, "text": text})
    assert preview["saved"] is False
    assert preview["validation"]["ok"]
    assert [s["split_s"] for s in preview["preview"]] == [96.8, 98.9, 99.0, 97.7]
    assert [s["distance_m"] for s in preview["preview"]] == [500.0, 1000.0, 1500.0, 2000.0]

    saved = tools.call_tool(session, "add_piece", {"piece_type": "2000m", "canonical_id": activity.canonical_id, "text": text, "confirm": True})
    assert saved["saved"] is True
    assert saved["piece"]["distance_m"] == 2000.0
    assert saved["piece"]["duration_s"] == 392.4 or abs(saved["piece"]["duration_s"] - 392.4) < 0.01


def test_add_piece_defaults_to_the_most_recent_activity(session):
    _seed_activity(session)
    later = Activity(source="garmin", external_id="g2", type="rowing_v2", start=T0.replace(hour=20), duration=1800.0, sport_family="rowing")
    session.add(later)
    session.commit()
    later_canonical = CanonicalActivity(sport_family="rowing")
    session.add(later_canonical)
    session.commit()
    later.canonical_id = later_canonical.id
    session.add(later)
    session.commit()
    run_matching(session)  # resolves canonical.start so "most recent" has something to sort on

    result = tools.call_tool(
        session, "add_piece", {"piece_type": "500m", "text": "my 500 was 1:38.0", "confirm": True}
    )
    assert result["piece"]["canonical_id"] == later_canonical.id


def test_add_piece_with_no_activities_at_all_fails_cleanly(session):
    result = tools.call_tool(session, "add_piece", {"piece_type": "2000m", "text": "6:32.4"})
    assert result["saved"] is False
    assert "No activity" in result["message"]


def test_add_piece_rejects_an_unknown_piece_type(session):
    try:
        tools.call_tool(session, "add_piece", {"piece_type": "nope", "text": "6:32.4"})
        assert False, "should have raised"
    except ValueError:
        pass


def test_get_test_dispatches_to_piece_detail_via_piece_id(session):
    activity = _seed_activity(session)
    text = "my 2k was 6:32.4, splits 1:36.8, 1:38.9, 1:39.0, 1:37.7"
    saved = tools.call_tool(session, "add_piece", {"piece_type": "2000m", "canonical_id": activity.canonical_id, "text": text, "confirm": True})
    piece_id = saved["piece"]["id"]

    detail = tools.call_tool(session, "get_test", {"piece_id": piece_id})
    assert detail["test_type"] == "2000m"
    assert detail["pacing_analysis"] is not None


def test_get_tests_includes_pieces_as_rows(session):
    activity = _seed_activity(session)
    text = "my 2k was 6:32.4, splits 1:36.8, 1:38.9, 1:39.0, 1:37.7"
    tools.call_tool(session, "add_piece", {"piece_type": "2000m", "canonical_id": activity.canonical_id, "text": text, "confirm": True})

    out = tools.call_tool(session, "get_tests", {"type": "2000m"})
    assert len(out["tests"]) == 1
    assert out["tests"][0]["kind"] == "piece"

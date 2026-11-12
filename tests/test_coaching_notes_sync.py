from __future__ import annotations

import itertools
import json
from datetime import timedelta

import pytest
from sqlmodel import select

from catch.core import principal as pr
from catch.core.models import CoachFeedback, CoachFeedbackRevision, Event, Piece, PlannedWorkout, TechniqueNote
from catch.core.principal import ATHLETE, VIEWER, Principal
from catch.sync import coaching_notes as cn
from catch.sync import planning as sp
from test_planning_sync import MON, _canonical

OWNER = pr.OWNER_ID
COACH = pr.coach_principal(7, "Coach Sam")
COACH2 = pr.coach_principal(8, "Coach Lee")
SECRET = "SECRET-PRIVATE-TEXT"


def _note(session, **kw):
    fields = {"category": "catch", "text": "Reaching early at the catch", **kw}
    return cn.create_technique_note(session, OWNER, ATHLETE, fields)


def _fb(session, who=COACH, **kw):
    fields = {"text": "Keep the hands moving first", "date": MON.isoformat(), **kw}
    return cn.create_feedback(session, OWNER, who, fields)


def _piece(session, canonical_id):
    p = Piece(canonical_id=canonical_id, piece_type="2000m")
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


# --- principal rules (the one code path) -------------------------------------------------------------------


def test_note_visibility_matrix():
    table = {
        (ATHLETE, "private"): True, (ATHLETE, "coach"): True,
        (COACH, "private"): False, (COACH, "coach"): True,
        (VIEWER, "private"): False, (VIEWER, "coach"): False,
    }
    for (who, vis), expected in table.items():
        assert pr.note_visible(vis, who) is expected, (who.role, vis)


def test_feedback_permission_matrix():
    authors = {"athlete": ("owner", ATHLETE), "coach": (COACH.id, COACH)}
    rows = []
    for (a_role, (a_id, _)), vis in itertools.product(authors.items(), ("private", "shared")):
        if a_role == "coach" and vis == "private":
            continue  # a coach can't create a hidden entry
        for who in (ATHLETE, COACH, COACH2, VIEWER):
            rows.append((a_role, a_id, vis, who))
    for a_role, a_id, vis, who in rows:
        seen = pr.feedback_visible(vis, a_id, who)
        if vis == "private":
            assert seen == (who.id == a_id), (a_role, vis, who.role)
        else:
            assert seen == (who.role in (pr.ATHLETE_ROLE, pr.COACH_ROLE))
        assert pr.can_edit_feedback(a_id, a_role, who) == (who.id == a_id and who.role == a_role)
        assert pr.can_respond_to_feedback(vis, a_id, who) == (who.is_athlete and seen)
    assert not pr.can_edit_feedback("owner", "athlete", Principal("coach", "owner", "x"))  # same id, wrong role


def test_tool_allow_list():
    assert pr.may_call_tool(ATHLETE, "get_today") and pr.may_call_tool(ATHLETE, "add_coach_feedback")
    assert not pr.may_call_tool(COACH, "get_today") and not pr.may_call_tool(COACH, "add_technique_note")
    assert pr.may_call_tool(COACH, "add_coach_feedback") and pr.may_call_tool(COACH, "get_technique_notes")
    assert not any(pr.may_call_tool(VIEWER, n) for n in pr.COACH_TOOLS)
    assert pr.principal_from({}) is VIEWER and pr.principal_from({"principal": "owner"}) is VIEWER


# --- technique notes ---------------------------------------------------------------------------------------


def test_note_defaults_private_and_has_no_rating_fields(session):
    n = _note(session)
    d = cn.note_dict(session, n)
    assert d["visibility"] == "private" and d["shared_with_coach"] is False
    assert not ({"score", "rating", "quality", "grade"} & set(d)) and "can't observe technique" in d["note"]
    assert not ({"score", "rating", "quality", "grade"} & set(TechniqueNote.model_fields))


def test_notes_attach_to_workout_piece_date_or_just_a_category(session):
    c = _canonical(session, MON)
    p = _piece(session, c.id)
    by_workout = _note(session, canonical_id=c.id)
    by_piece = _note(session, piece_id=p.id)
    by_date = _note(session, note_date=MON.isoformat())
    by_cat = _note(session, category="posture")
    assert by_piece.canonical_id == c.id  # a piece implies its workout
    got = lambda **kw: {n.id for n in cn.list_technique_notes(session, OWNER, ATHLETE, **kw)}  # noqa: E731
    assert got(canonical_id=c.id) == {by_workout.id, by_piece.id}
    assert got(piece_id=p.id) == {by_piece.id} and got(note_date=MON) == {by_date.id} and got(category="posture") == {by_cat.id}
    assert got(date_from=MON, date_to=MON) == {by_date.id}


def test_note_validation(session):
    c = _canonical(session, MON)
    other = _canonical(session, MON + timedelta(days=1))
    p = _piece(session, c.id)
    bad = [
        {"category": "speed", "text": "x"}, {"category": "catch", "text": "  "}, {"category": "catch", "text": "x" * 4001},
        {"category": "catch", "text": "x", "visibility": "public"}, {"category": "catch", "text": "x", "canonical_id": 999999},
        {"category": "catch", "text": "x", "piece_id": 999999}, {"category": "catch", "text": "x", "piece_id": p.id, "canonical_id": other.id},
        {"category": "catch", "text": "x", "date": "yesterday"}, {"category": "catch", "text": "x", "bogus": 1},
        {"category": "catch", "text": "x", "media": [{"url": "javascript:alert(1)"}]}, {"category": "catch", "text": "x", "media": [{"url": "//evil.example/x"}]},
        {"category": "catch", "text": "x", "media": [{"url": "https://a.example/x"}] * 6},
    ]
    for fields in bad:
        with pytest.raises(cn.CoachingError):
            cn.create_technique_note(session, OWNER, ATHLETE, fields)
    assert session.exec(select(TechniqueNote)).all() == []
    ok = cn.create_technique_note(session, OWNER, ATHLETE, {"category": "drive", "text": "x", "media": [{"url": "https://a.example/v.mp4", "label": "clip"}, {"url": "/photos/1.jpg"}]})
    assert json.loads(ok.media_json)[0]["label"] == "clip"


def test_only_the_athlete_writes_notes_and_a_coach_never_reads_private_ones(session):
    private, shared = _note(session, text=SECRET), _note(session, text="shared one", visibility="coach")
    for who in (COACH, VIEWER):
        with pytest.raises(cn.Forbidden):
            cn.create_technique_note(session, OWNER, who, {"category": "catch", "text": "x"})
    coach_view = cn.list_technique_notes(session, OWNER, COACH)
    assert [n.id for n in coach_view] == [shared.id]
    assert SECRET not in json.dumps([cn.note_dict(session, n) for n in coach_view], default=str)
    assert cn.list_technique_notes(session, OWNER, VIEWER) == []
    with pytest.raises(cn.NotFound):  # a private note reads as not-found, never "forbidden"
        cn.update_technique_note(session, OWNER, COACH, private.id, {"text": "x"})
    with pytest.raises(cn.Forbidden):
        cn.update_technique_note(session, OWNER, COACH, shared.id, {"text": "x"})
    with pytest.raises(cn.Forbidden):
        cn.delete_technique_note(session, OWNER, COACH, shared.id)


def test_note_owner_isolation(session):
    n = _note(session)
    assert cn.list_technique_notes(session, "someone-else", ATHLETE) == []
    with pytest.raises(cn.NotFound):
        cn.update_technique_note(session, "someone-else", ATHLETE, n.id, {"text": "x"})


def test_sharing_toggle_and_delete(session):
    n = _note(session)
    assert cn.list_technique_notes(session, OWNER, COACH) == []
    cn.update_technique_note(session, OWNER, ATHLETE, n.id, {"visibility": "coach"})
    assert [x.id for x in cn.list_technique_notes(session, OWNER, COACH)] == [n.id]
    cn.update_technique_note(session, OWNER, ATHLETE, n.id, {"visibility": "private"})
    assert cn.list_technique_notes(session, OWNER, COACH) == []
    cn.delete_technique_note(session, OWNER, ATHLETE, n.id)
    assert session.exec(select(TechniqueNote)).all() == []


# --- feedback: authoring, ownership -----------------------------------------------------------------------


def test_coach_feedback_is_always_shared_and_attributed(session):
    fb = _fb(session)
    assert (fb.author_role, fb.author_id, fb.author_name, fb.visibility, fb.created_via) == ("coach", COACH.id, "Coach Sam", "shared", "web")
    with pytest.raises(cn.CoachingError, match="always shared"):
        _fb(session, visibility="private")
    with pytest.raises(cn.CoachingError, match="only for feedback the athlete logs"):
        _fb(session, coach_name="Someone")
    with pytest.raises(cn.Forbidden):
        cn.create_feedback(session, OWNER, VIEWER, {"text": "x"})


def test_athlete_can_log_feedback_received_with_a_coach_name_and_private_option(session):
    fb = cn.create_feedback(session, OWNER, ATHLETE, {"text": "Sit up more", "coach_name": "Coach Kim", "visibility": "private", "focus_areas": ["posture"]}, via="ai_coach")
    assert fb.author_role == "athlete" and fb.coach_name == "Coach Kim" and fb.created_via == "ai_coach" and fb.visibility == "private"
    assert cn.list_feedback(session, OWNER, COACH) == []


def test_ownership_nobody_edits_or_deletes_anothers_feedback(session):
    mine = cn.create_feedback(session, OWNER, ATHLETE, {"text": "my own log"})
    theirs = _fb(session)
    for fn in (
        lambda: cn.update_feedback(session, OWNER, ATHLETE, theirs.id, {"text": "tampered"}),
        lambda: cn.delete_feedback(session, OWNER, ATHLETE, theirs.id),
        lambda: cn.update_feedback(session, OWNER, COACH, mine.id, {"text": "tampered"}),
        lambda: cn.update_feedback(session, OWNER, COACH2, theirs.id, {"text": "tampered"}),
        lambda: cn.delete_feedback(session, OWNER, COACH2, theirs.id),
        lambda: cn.respond_to_feedback(session, OWNER, COACH, theirs.id, "my reply"),
    ):
        with pytest.raises(cn.Forbidden):
            fn()
    assert (session.get(CoachFeedback, theirs.id).text, session.get(CoachFeedback, mine.id).text) == ("Keep the hands moving first", "my own log")
    assert session.exec(select(CoachFeedbackRevision)).all() == []


def test_private_feedback_is_invisible_to_everyone_but_its_author(session):
    fb = cn.create_feedback(session, OWNER, ATHLETE, {"text": SECRET, "visibility": "private"})
    for who in (COACH, VIEWER):
        assert cn.list_feedback(session, OWNER, who) == []
        for fn in (lambda: cn.get_feedback(session, OWNER, who, fb.id), lambda: cn.feedback_history(session, OWNER, who, fb.id), lambda: cn.update_feedback(session, OWNER, who, fb.id, {"text": "x"})):
            with pytest.raises(cn.NotFound):
                fn()
    assert [r.id for r in cn.list_feedback(session, OWNER, ATHLETE)] == [fb.id]


def test_viewer_sees_nothing_even_shared(session):
    _fb(session)
    assert cn.list_feedback(session, OWNER, VIEWER) == []


def test_feedback_owner_isolation(session):
    fb = _fb(session)
    assert cn.list_feedback(session, "someone-else", ATHLETE) == []
    with pytest.raises(cn.NotFound):
        cn.get_feedback(session, "someone-else", ATHLETE, fb.id)


# --- response, edits, history ------------------------------------------------------------------------------


def test_athlete_response_is_recorded_and_revisioned(session):
    fb = _fb(session)
    cn.respond_to_feedback(session, OWNER, ATHLETE, fb.id, "Thanks, will try")
    assert fb.athlete_response == "Thanks, will try" and fb.athlete_response_at is not None
    cn.respond_to_feedback(session, OWNER, ATHLETE, fb.id, "Tried it - better")
    cn.respond_to_feedback(session, OWNER, ATHLETE, fb.id, "Tried it - better")  # no-op, no revision
    revs = session.exec(select(CoachFeedbackRevision).order_by(CoachFeedbackRevision.revision_no)).all()
    assert [(r.revision_no, r.kind, r.athlete_response) for r in revs] == [(1, "response", None), (2, "response", "Thanks, will try")]
    cn.respond_to_feedback(session, OWNER, ATHLETE, fb.id, "")
    assert fb.athlete_response is None and fb.athlete_response_at is None


def test_edits_preserve_history_in_order_and_mark_the_entry_edited(session):
    fb = _fb(session, focus_areas=["catch"])
    assert cn.feedback_dict(session, fb, ATHLETE)["edited"] is False
    cn.update_feedback(session, OWNER, COACH, fb.id, {"text": "v2", "focus_areas": ["catch", "drive"]})
    cn.update_feedback(session, OWNER, COACH, fb.id, {"text": "v3"})
    cn.update_feedback(session, OWNER, COACH, fb.id, {"text": "v3"})  # unchanged -> no revision
    h = cn.feedback_history(session, OWNER, ATHLETE, fb.id)
    assert [(r["revision_no"], r["text"], r["kind"], r["edited_by"]) for r in h] == [(1, "Keep the hands moving first", "edit", "Coach Sam"), (2, "v2", "edit", "Coach Sam")]
    assert h[0]["focus_areas"] == ["catch"] and h[1]["focus_areas"] == ["catch", "drive"]
    d = cn.feedback_dict(session, fb, ATHLETE)
    assert d["edited"] and d["edit_count"] == 2 and d["can_edit"] is False and d["can_respond"] is True
    assert cn.feedback_dict(session, fb, COACH)["can_edit"] is True and cn.feedback_dict(session, fb, COACH)["can_respond"] is False


def test_history_never_leaks_text_from_before_an_entry_was_shared(session):
    fb = cn.create_feedback(session, OWNER, ATHLETE, {"text": SECRET, "visibility": "private"})
    cn.update_feedback(session, OWNER, ATHLETE, fb.id, {"text": "edited private draft"})
    cn.update_feedback(session, OWNER, ATHLETE, fb.id, {"visibility": "shared", "text": "now shared"})
    cn.update_feedback(session, OWNER, ATHLETE, fb.id, {"text": "shared v2"})
    coach_history = cn.feedback_history(session, OWNER, COACH, fb.id)
    blob = json.dumps(coach_history, default=str)
    assert SECRET not in blob and "edited private draft" not in blob
    assert [r["text"] for r in coach_history] == ["now shared"]  # the state it had *while* shared
    assert SECRET in json.dumps(cn.feedback_history(session, OWNER, ATHLETE, fb.id), default=str)
    assert cn.feedback_dict(session, fb, COACH)["edit_count"] == 1
    cn.update_feedback(session, OWNER, ATHLETE, fb.id, {"visibility": "private"})  # un-sharing hides it again
    assert cn.list_feedback(session, OWNER, COACH) == []
    with pytest.raises(cn.NotFound):
        cn.feedback_history(session, OWNER, COACH, fb.id)


def test_delete_is_soft_hidden_everywhere_and_history_is_retained(session):
    fb = _fb(session)
    cn.update_feedback(session, OWNER, COACH, fb.id, {"text": "v2"})
    cn.delete_feedback(session, OWNER, COACH, fb.id)
    for who in (ATHLETE, COACH):
        assert cn.list_feedback(session, OWNER, who) == []
        with pytest.raises(cn.NotFound):
            cn.get_feedback(session, OWNER, who, fb.id)
        with pytest.raises(cn.NotFound):
            cn.feedback_history(session, OWNER, who, fb.id)
    row = session.get(CoachFeedback, fb.id)
    assert row is not None and row.deleted_at is not None
    assert [r.kind for r in session.exec(select(CoachFeedbackRevision).order_by(CoachFeedbackRevision.revision_no)).all()] == ["edit", "delete"]


def test_feedback_validation(session):
    c = _canonical(session, MON)
    for fields in (
        {"text": ""}, {"text": "x", "focus_areas": ["nonsense"]}, {"text": "x", "focus_areas": "catch"}, {"text": "x", "visibility": "public"},
        {"text": "x", "canonical_id": 999999}, {"text": "x", "event_id": 999999}, {"text": "x", "planned_id": 999999},
        {"text": "x", "date": "soon"}, {"text": "x", "bogus": 1}, {"text": "x", "workout_date": "2000-01-01"},
    ):
        with pytest.raises(cn.CoachingError):
            cn.create_feedback(session, OWNER, ATHLETE, fields)
    assert session.exec(select(CoachFeedback)).all() == []
    ok = cn.create_feedback(session, OWNER, COACH, {"text": "x", "canonical_id": c.id, "focus_areas": ["catch", "catch", "pacing"]})
    assert json.loads(ok.focus_areas_json) == ["catch", "pacing"] and ok.entry_date == sp.today()


def test_a_coach_can_link_by_date_only_when_exactly_one_workout_that_day(session):
    c = _canonical(session, MON)
    fb = _fb(session, workout_date=MON.isoformat())
    assert fb.canonical_id == c.id
    d = cn.feedback_dict(session, fb, COACH)
    assert d["workout"]["id"] == c.id and d["workout"]["date"] == MON.isoformat()
    _canonical(session, MON, hour=18)
    with pytest.raises(cn.CoachingError, match="2 workouts"):
        _fb(session, workout_date=MON.isoformat())
    with pytest.raises(cn.CoachingError, match="No workout"):
        _fb(session, workout_date=(MON + timedelta(days=3)).isoformat())


def test_filters_by_coach_category_date_workout_and_event(session):
    c = _canonical(session, MON)
    ev = sp.create_event(session, OWNER, {"name": "Head", "date": MON + timedelta(days=20), "type": "race"})
    a = _fb(session, COACH, date=(MON).isoformat(), focus_areas=["catch"], canonical_id=c.id)
    b = _fb(session, COACH2, date=(MON + timedelta(days=5)).isoformat(), focus_areas=["pacing", "racing"], event_id=ev.id)
    logged = cn.create_feedback(session, OWNER, ATHLETE, {"text": "from Kim", "coach_name": "Coach Kim", "date": (MON + timedelta(days=9)).isoformat()})
    ids = lambda **kw: [r.id for r in cn.list_feedback(session, OWNER, ATHLETE, **kw)]  # noqa: E731
    assert ids() == [logged.id, b.id, a.id]  # newest first
    assert ids(coach="sam") == [a.id] and ids(coach="LEE") == [b.id] and ids(coach="kim") == [logged.id] and ids(coach="nobody") == []
    assert ids(category="pacing") == [b.id] and ids(category="catch") == [a.id]
    assert ids(date_from=MON + timedelta(days=1), date_to=MON + timedelta(days=6)) == [b.id]
    assert ids(canonical_id=c.id) == [a.id] and ids(event_id=ev.id) == [b.id]
    assert ids(limit=1) == [logged.id] and ids(limit=1, offset=1) == [b.id]
    assert cn.list_coach_names(session, OWNER, ATHLETE) == ["Coach Kim", "Coach Lee", "Coach Sam"]
    with pytest.raises(cn.CoachingError):
        cn.list_feedback(session, OWNER, ATHLETE, category="bogus")


# --- references that go stale --------------------------------------------------------------------------------------


def test_merging_workouts_repoints_notes_and_feedback_to_the_survivor(session):
    from test_planning_sync import _two_activities

    from catch.core.models import CanonicalActivity
    from catch.sync.matching import manual_merge

    (a, ca), (b, cb) = _two_activities(session)
    note = _note(session, canonical_id=cb.id)
    fb = _fb(session, canonical_id=cb.id)
    keep = manual_merge(session, a.id, b.id)
    session.expire_all()
    assert session.get(CanonicalActivity, keep.id) is not None
    assert session.get(TechniqueNote, note.id).canonical_id == keep.id and session.get(CoachFeedback, fb.id).canonical_id == keep.id


def test_deleting_an_event_clears_feedback_links(session):
    ev = sp.create_event(session, OWNER, {"name": "Head", "date": MON + timedelta(days=20), "type": "race"})
    fb = _fb(session, event_id=ev.id)
    sp.delete_event(session, OWNER, ev.id)
    assert session.get(CoachFeedback, fb.id).event_id is None
    assert session.exec(select(Event)).all() == []


def test_deleting_a_planned_session_clears_feedback_links(session):
    plan = sp.create_planned(session, OWNER, {"date": MON, "session_type": "erg"})[0]
    fb = _fb(session, planned_id=plan.id)
    sp.delete_planned(session, OWNER, plan.id)
    assert session.get(CoachFeedback, fb.id).planned_id is None
    assert session.exec(select(PlannedWorkout)).all() == []


def test_series_delete_clears_every_planned_link(session):
    plans = sp.create_planned(session, OWNER, {"date": MON, "session_type": "erg"}, repeat={"count": 3, "weekdays": [0]})
    fbs = [_fb(session, planned_id=p.id) for p in plans]
    sp.delete_planned(session, OWNER, plans[0].id, scope="this_and_following")
    assert [session.get(CoachFeedback, f.id).planned_id for f in fbs] == [None, None, None]


def test_deleting_a_piece_clears_the_note_piece_link_but_keeps_the_workout(session):
    from catch.sync import piece as piece_sync

    c = _canonical(session, MON)
    p = _piece(session, c.id)
    note = _note(session, piece_id=p.id)
    assert piece_sync.delete_piece(session, p.id)
    session.refresh(note)
    assert note.piece_id is None and note.canonical_id == c.id


def test_reloaded_naive_datetimes_compare_safely(session):
    fb = _fb(session)
    cn.respond_to_feedback(session, OWNER, ATHLETE, fb.id, "ok")
    session.expire_all()
    h = cn.feedback_history(session, OWNER, ATHLETE, fb.id)
    assert h[0]["edited_at"].tzinfo is not None
    assert session.get(CoachFeedback, fb.id).athlete_response_at is not None


# --- a revoked coach's authorship must not pass to the next token ---------------------------------------


def test_a_new_coach_token_never_inherits_a_revoked_coachs_entries(client, session):
    """SQLite reuses the rowid of a deleted newest row, so a principal keyed on `ApiToken.id` would hand
    Coach A's authorship to the next coach token minted after A's was revoked."""
    from conftest import TEST_PASSWORD

    client.post("/api/login", json={"password": TEST_PASSWORD})
    a = client.post("/api/coach/tokens", json={"name": "a", "role": "coach", "display_name": "Coach A"}).json()
    h_a = {"Authorization": f"Bearer {a['token']}"}
    client.cookies.clear()  # a login cookie outranks a bearer token, so act as the coach with the token alone
    saved = client.post("/api/coach/tools/add_coach_feedback", json={"args": {"text": "A's advice", "confirm": True}}, headers=h_a).json()
    fb_id = saved["feedback"]["id"]
    client.post("/api/login", json={"password": TEST_PASSWORD})
    assert client.delete(f"/api/coach/tokens/{a['id']}").status_code == 200
    b = client.post("/api/coach/tokens", json={"name": "b", "role": "coach", "display_name": "Coach B"}).json()
    h_b = {"Authorization": f"Bearer {b['token']}"}
    assert b["id"] == a["id"]  # SQLite handed the freed rowid to the next token — the premise of this test
    client.cookies.clear()

    listing = client.post("/api/coach/tools/get_coach_feedback", json={"args": {}}, headers=h_b).json()["feedback"]
    entry = next(f for f in listing if f["id"] == fb_id)
    assert entry["author"]["name"] == "Coach A" and entry["can_edit"] is False  # B reads it, can't own it
    row = session.get(CoachFeedback, fb_id)
    from catch.core.principal import principal_from_token
    from catch.core.models import ApiToken

    b_row = session.exec(select(ApiToken).where(ApiToken.name == "b")).one()
    b_principal = principal_from_token(b_row.token_hash, b_row.role, b_row.display_name)
    assert b_principal.id != row.author_id and row.author_id.startswith("coach:") and len(row.author_id) > 12
    with pytest.raises(cn.Forbidden):
        cn.update_feedback(session, OWNER, b_principal, fb_id, {"text": "tampered"})
    with pytest.raises(cn.Forbidden):
        cn.delete_feedback(session, OWNER, b_principal, fb_id)
    assert session.get(CoachFeedback, fb_id).text == "A's advice"

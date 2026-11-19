"""Route-level IDOR sweep (session 28). Alice owns a generated row in every table; Bob then calls every route that takes one of
her ids. Each must answer 404 (reads/deletes) or at least refuse (writes) — never succeed, never 5xx.

The table-level guarantee is already in test_isolation_generic.py; this is the check that no *route* sidesteps it with an
unscoped query, an id taken from the body, or a lookup that happens before the owner is known. The leaderboard and club routes
are keyed by membership rather than ownership and have their own identity-level suites (test_clubs_api, test_leaderboards_api)."""

from __future__ import annotations

import re

import pytest

from tests.tenancy import kit
from tests.tenancy.conftest import bearer
from tests.tenancy.test_isolation_generic import _no_parent_guard, _seed  # noqa: F401  (the autouse fixture must apply here too)
from tests.tenancy.test_route_auth_coverage import all_routes

pytestmark = [pytest.mark.filterwarnings("ignore:Cannot correctly sort tables")]

A, B = bearer(kit.ALICE), bearer(kit.BOB)

# path parameter -> (owned table). Two parameter names are family-specific and resolved by path prefix below.
PARAM_TABLE = {
    "canonical_id": "canonical_activities",
    "activity_id": "activities",
    "conversation_id": "coach_conversations",
    "event_id": "events",
    "fact_id": "athlete_facts",
    "goal_id": "goals",
    "feedback_id": "coach_feedback",
    "note_id": "technique_notes",
    "interval_id": "piece_intervals",
    "piece_id": "pieces",
    "route_id": "routes",
    "planned_id": "planned_workouts",
    "phase_id": "training_phases",
    "log_id": "food_logs",
    "my_food_id": "my_foods",
    "saved_meal_id": "saved_meals",
    "token_id": "api_tokens",
    "gym_id": "gyms",
    "station_id": "gym_stations",
    "exercise_id": "exercises",
}


def _table_for(param: str, path: str) -> str | None:
    if param == "template_id":
        return "strength_templates" if path.startswith("/api/gym/") else "workout_templates"
    if param == "id" and "/recommendations/" in path:
        return "recommendations"
    return PARAM_TABLE.get(param)


def _targets():
    """(method, path template, [(param, table)]) for every route whose parameters are all owned-resource ids."""
    out = []
    for path, route, _ in all_routes():
        params = re.findall(r"{(\w+)}", path)
        if not params or path.startswith(("/api/clubs", "/api/leaderboards", "/api/moderation", "/internal", "/api/coach/tools")):
            continue
        tables = [(p, _table_for(p, path)) for p in params]
        if any(t is None for _, t in tables):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, path, tables))
    return sorted(out)


TARGETS = _targets()


def test_the_sweep_covers_a_meaningful_share_of_the_id_routes():
    assert len(TARGETS) >= 80, len(TARGETS)
    assert {"canonical_id", "piece_id", "planned_id", "conversation_id", "note_id", "log_id", "token_id"} <= {p for _, _, ts in TARGETS for p, _ in ts}


def _url(path: str, tables, created) -> str | None:
    url = path
    for param, table in tables:
        pk = created.get(table, {})
        if "id" not in pk:
            return None
        url = url.replace("{" + param + "}", str(pk["id"]))
    return url


def _call(client, method, url, headers):
    kwargs = {} if method in ("GET", "DELETE") else {"json": {}}
    return client.request(method, url, headers=headers, **kwargs)


def _make_generated_json_valid(engine) -> None:
    """The row generator fills every required text column with a placeholder; a few columns hold JSON that handlers parse."""
    from sqlmodel import Session

    from catch.core import tenant
    from catch.core.models import AppSettings

    with tenant.use_owner(kit.ALICE), Session(engine) as s:
        for row in s.exec(__import__("sqlmodel").select(AppSettings)).all():
            row.data_json = "{}"
            s.add(row)
        s.commit()


def _row_counts(engine) -> dict[str, int]:
    from sqlalchemy import func, select
    from sqlmodel import Session

    out = {}
    with Session(engine) as s:
        for cls in kit.owned_classes():
            out[cls.__tablename__] = s.execute(select(func.count()).select_from(cls).execution_options(tenant_unscoped=True)).scalar()
    return out


def test_no_id_route_lets_bob_reach_alices_rows(pub_client, pub_engine):
    created = _seed(pub_engine, kit.ALICE)
    _make_generated_json_valid(pub_engine)
    for h in (A, B):
        assert pub_client.get("/api/me", headers=h).status_code == 200
    leaks, server_errors, checked, alice_reached, indistinguishable = [], [], 0, 0, []
    before = _row_counts(pub_engine)
    for method, path, tables in TARGETS:
        url = _url(path, tables, created)
        if url is None:
            continue
        checked += 1
        resp = _call(pub_client, method, url, B)
        status = resp.status_code
        if 200 <= status < 400:
            # Some list/idempotent routes answer 200 with an empty result for any id Bob doesn't own. That is fine only if it is
            # exactly what he gets for an id that doesn't exist at all (no existence oracle) and Alice's data is untouched (below).
            ghost = _call(pub_client, method, _url(path, [(p, t) for p, t in tables], {t: {"id": 999_999} for _, t in tables}), B)
            if (ghost.status_code, ghost.content) == (status, resp.content):
                indistinguishable.append(f"{method} {path}")
            else:
                leaks.append(f"{method} {path} -> {status}, but {ghost.status_code} for an id that doesn't exist")
        elif status >= 500:
            server_errors.append(f"{method} {path} -> {status}")
        elif method in ("GET", "DELETE") and status not in (404, 405, 422):
            leaks.append(f"{method} {path} -> {status} (expected 404)")
        if method == "GET":
            # Control: the seeded id is real, so Bob's 404 means something. Alice's call may crash on the generator's
            # placeholder text in a JSON column — that still means her row was found, which is all the control needs.
            try:
                reached = _call(pub_client, method, url, A).status_code != 404
            except Exception:  # noqa: BLE001
                reached = True
            alice_reached += reached
    assert _row_counts(pub_engine) == before, "a request from Bob added or removed rows"
    assert len(indistinguishable) <= 8, indistinguishable  # a new 200-for-foreign-id route should be a conscious decision
    assert not leaks, "Bob got through (or a non-404 answer revealed the row exists):\n  " + "\n  ".join(leaks)
    assert not server_errors, "Bob's request crashed the handler:\n  " + "\n  ".join(server_errors)
    assert checked >= 80 and alice_reached >= 10, (checked, alice_reached)

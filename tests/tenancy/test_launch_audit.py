"""Session 31 launch-audit regressions that fit no existing module (docs/launch-audit.md)."""

from catch.coach import limits
from tests.tenancy import kit
from tests.tenancy.conftest import bearer

TICK = {"authorization": "Bearer tick-secret-for-tests-0123456789abcdefg"}
WRONG = {"authorization": "Bearer not-the-tick-secret"}


def test_wrong_tick_secrets_are_throttled_but_never_starve_the_real_tick(pub_client):
    """L-06: the per-IP throttle used to run before the secret check, so junk requests from a shared proxy address filled the
    bucket and the scheduled tick from the same address got 429."""
    limits.reset()
    statuses = [pub_client.post("/internal/tick/notifications", headers=WRONG).status_code for _ in range(limits.BUCKET_LIMITS["internal"] + 5)]
    assert set(statuses[: limits.BUCKET_LIMITS["internal"]]) == {401}
    assert statuses[-1] == 429  # guessing is still metered
    r = pub_client.post("/internal/tick/notifications", headers=TICK)
    assert r.status_code == 200, r.text


def test_one_users_claim_failure_or_job_failure_never_stops_the_tick(pub_client, monkeypatch):
    """L-35: a claim error aborted the whole tick, and a failed job held its lease for the full lease time."""
    from catch.api import routes_internal
    from catch.core import tenant

    for sub in (kit.ALICE, kit.BOB, "33333333-3333-4333-8333-333333333333"):
        assert pub_client.get("/api/me", headers=bearer(sub)).status_code == 200
    real_claim = routes_internal._claim
    claims: list[str] = []

    def flaky_claim(session, job):
        claims.append(tenant.current_owner())
        if len(claims) == 1:
            raise RuntimeError("statement timeout")
        return real_claim(session, job)

    monkeypatch.setattr(routes_internal, "_claim", flaky_claim)
    calls = []

    def work():
        calls.append(tenant.current_owner())
        raise RuntimeError("provider down")

    out = routes_internal.run_for_each_user("sync", work)
    assert out["users"] == 3 and out["failed"] == 3 and len(calls) == 2
    monkeypatch.setattr(routes_internal, "_claim", real_claim)
    again = routes_internal.run_for_each_user("sync", lambda: None)
    assert again["ran"] == 3, again  # the two failed jobs released their leases at once

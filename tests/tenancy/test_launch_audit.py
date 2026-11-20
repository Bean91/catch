"""Session 31 launch-audit regressions that fit no existing module (docs/launch-audit.md)."""

from catch.coach import limits

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

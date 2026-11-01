from __future__ import annotations

from catch.coach import cost
from catch.core.models import CoachConversation, CoachMessage


def test_estimate_cost_usd_includes_all_four_rates():
    prices = {"input": 1.0, "output": 2.0, "cache_write": 3.0, "cache_read": 4.0}
    usage = {"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 20}
    expected = (100 * 1.0 + 50 * 2.0 + 10 * 3.0 + 20 * 4.0) / 1_000_000
    assert abs(cost.estimate_cost_usd(prices, usage) - expected) < 1e-12


def test_estimate_cost_usd_zero_for_ollama_empty_prices():
    assert cost.estimate_cost_usd({}, {"input_tokens": 1000, "output_tokens": 1000}) == 0.0


def test_estimate_cost_usd_none_when_no_prices_configured():
    assert cost.estimate_cost_usd(None, {"input_tokens": 1}) is None


def test_today_spend_sums_only_todays_messages(session):
    import datetime as dt

    conv = CoachConversation()
    session.add(conv)
    session.commit()
    session.refresh(conv)

    old = CoachMessage(conversation_id=conv.id, role="assistant", blocks_json="[]", cost_usd=2.0)
    old.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    session.add(old)
    session.add(CoachMessage(conversation_id=conv.id, role="assistant", blocks_json="[]", cost_usd=1.5))
    session.add(CoachMessage(conversation_id=conv.id, role="assistant", blocks_json="[]", cost_usd=0.5))
    session.commit()

    assert cost.today_spend_usd(session) == 2.0


def test_conversation_usage_sums_tokens_and_cost(session):
    conv = CoachConversation()
    session.add(conv)
    session.commit()
    session.refresh(conv)

    session.add(
        CoachMessage(
            conversation_id=conv.id,
            role="assistant",
            blocks_json="[]",
            usage_json='{"input_tokens": 100, "output_tokens": 10, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}',
            cost_usd=0.01,
        )
    )
    session.add(
        CoachMessage(
            conversation_id=conv.id,
            role="assistant",
            blocks_json="[]",
            usage_json='{"input_tokens": 50, "output_tokens": 5, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}',
            cost_usd=0.005,
        )
    )
    session.commit()

    totals = cost.conversation_usage(session, conv.id)
    assert totals["input_tokens"] == 150
    assert totals["output_tokens"] == 15
    assert abs(totals["cost_usd"] - 0.015) < 1e-9

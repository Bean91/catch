from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from catch.core.models import DailyWellness, Food
from conftest import TEST_PASSWORD


def _login(client):
    client.post("/api/login", json={"password": TEST_PASSWORD})


def _seed_food(session, **overrides) -> Food:
    defaults = dict(
        source="manual",
        barcode="1111111111111",
        name="Oats",
        brand=None,
        serving_size=40,
        serving_unit="g",
        kcal_100g=375,
        protein_100g=13,
        carbs_100g=61,
        fat_100g=7,
        fiber_100g=10,
        sugar_100g=1,
        sodium_100g=2,
        verified=True,
    )
    defaults.update(overrides)
    food = Food(**defaults)
    session.add(food)
    session.commit()
    session.refresh(food)
    return food


def test_barcode_lookup_hits_local_cache_first_no_network(client, session, monkeypatch):
    _seed_food(session, barcode="9999999999999")

    def _boom(*a, **k):
        raise AssertionError("should not hit Open Food Facts when a local cache hit exists")

    monkeypatch.setattr("catch.sync.openfoodfacts_client.OpenFoodFactsClient.lookup_barcode", _boom)

    _login(client)
    resp = client.get("/api/nutrition/barcode/9999999999999")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is True
    assert body["name"] == "Oats"


def test_barcode_lookup_falls_through_off_to_usda_to_not_found(client, monkeypatch):
    import dataclasses

    from catch.core.config import settings as real_settings

    monkeypatch.setattr("catch.sync.openfoodfacts_client.OpenFoodFactsClient.lookup_barcode", lambda self, barcode: None)
    monkeypatch.setattr("catch.sync.usda_client.UsdaClient.lookup_barcode", lambda self, barcode: None)
    monkeypatch.setattr("catch.sync.nutrition.app_settings", dataclasses.replace(real_settings, usda_fdc_api_key="fake-key"))

    _login(client)
    resp = client.get("/api/nutrition/barcode/0000000000001")
    assert resp.status_code == 200
    body = resp.json()
    assert body["found"] is False
    assert body["barcode"] == "0000000000001"


def test_barcode_lookup_caches_an_off_hit_for_next_time(client, session, monkeypatch):
    off_result = {
        "source": "off",
        "name": "Test Bar",
        "brand": "Acme",
        "serving_size": 30,
        "serving_unit": "g",
        "kcal_100g": 400,
        "protein_100g": 20,
        "carbs_100g": 40,
        "fat_100g": 10,
        "fiber_100g": 5,
        "sugar_100g": 3,
        "sodium_100g": 100,
        "verified": False,
    }
    calls = []

    def _fake_lookup(self, barcode):
        calls.append(barcode)
        return off_result

    monkeypatch.setattr("catch.sync.openfoodfacts_client.OpenFoodFactsClient.lookup_barcode", _fake_lookup)

    _login(client)
    resp = client.get("/api/nutrition/barcode/5555555555555")
    assert resp.json()["found"] is True
    assert resp.json()["name"] == "Test Bar"
    assert len(calls) == 1

    # Second lookup must come from the local cache — no second OFF call.
    resp2 = client.get("/api/nutrition/barcode/5555555555555")
    assert resp2.json()["found"] is True
    assert len(calls) == 1


def test_manual_food_create_and_log_by_grams(client, session):
    _login(client)
    resp = client.post(
        "/api/nutrition/foods",
        json={"name": "Banana", "kcal_100g": 89, "protein_100g": 1.1, "carbs_100g": 23, "fat_100g": 0.3},
    )
    assert resp.status_code == 200
    food_id = resp.json()["id"]

    log_resp = client.post(
        "/api/nutrition/logs",
        json={"meal": "breakfast", "food_id": food_id, "quantity": 118, "unit": "g"},
    )
    assert log_resp.status_code == 200
    body = log_resp.json()
    assert body["kcal"] == pytest.approx(89 * 1.18)


def test_log_by_serving_uses_foods_serving_size(client, session):
    food = _seed_food(session)
    _login(client)
    resp = client.post(
        "/api/nutrition/logs",
        json={"meal": "breakfast", "food_id": food.id, "quantity": 1, "unit": "serving"},
    )
    assert resp.status_code == 200
    # 1 serving = 40g of oats -> 375 * 0.4 = 150 kcal
    assert resp.json()["kcal"] == pytest.approx(150.0)


def test_log_by_serving_without_known_serving_size_is_rejected(client, session):
    food = _seed_food(session, serving_size=None)
    _login(client)
    resp = client.post(
        "/api/nutrition/logs",
        json={"meal": "lunch", "food_id": food.id, "quantity": 1, "unit": "serving"},
    )
    assert resp.status_code == 422


def test_invalid_meal_is_rejected(client, session):
    food = _seed_food(session)
    _login(client)
    resp = client.post(
        "/api/nutrition/logs",
        json={"meal": "elevenses", "food_id": food.id, "quantity": 50, "unit": "g"},
    )
    assert resp.status_code == 422


def test_day_summary_totals_logs_and_includes_targets(client, session):
    food = _seed_food(session)
    today = date.today()
    session.add(DailyWellness(date=today, total_kcal=3000))
    session.commit()
    _login(client)

    client.post("/api/nutrition/logs", json={"meal": "breakfast", "food_id": food.id, "quantity": 100, "unit": "g"})
    client.post("/api/nutrition/logs", json={"meal": "lunch", "food_id": food.id, "quantity": 50, "unit": "g"})

    resp = client.get("/api/nutrition/summary/day", params={"day": today.isoformat()})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intake"]["kcal"] == pytest.approx(375 * 1.5)
    assert len(body["logs"]) == 2
    assert "targets" in body


def test_copy_day_recomputes_against_current_food_data(client, session):
    food = _seed_food(session)
    yesterday = date.today() - timedelta(days=1)
    _login(client)
    client.post(
        "/api/nutrition/logs",
        json={"ts": datetime(yesterday.year, yesterday.month, yesterday.day, 8, 0, tzinfo=timezone.utc).isoformat(), "meal": "breakfast", "food_id": food.id, "quantity": 40, "unit": "g"},
    )
    resp = client.post(
        "/api/nutrition/logs/copy-day",
        json={"from_date": yesterday.isoformat(), "to_date": date.today().isoformat()},
    )
    assert resp.status_code == 200
    assert len(resp.json()["logged"]) == 1

    today_logs = client.get("/api/nutrition/logs", params={"from": date.today().isoformat(), "to": date.today().isoformat()}).json()["logs"]
    assert len(today_logs) == 1


def test_my_foods_star_unstar(client, session):
    food = _seed_food(session)
    _login(client)
    resp = client.post("/api/nutrition/my-foods", params={"food_id": food.id, "label": "Morning oats"})
    assert resp.status_code == 200
    my_food_id = resp.json()["id"]

    listed = client.get("/api/nutrition/my-foods").json()["my_foods"]
    assert any(f["my_food_id"] == my_food_id for f in listed)

    del_resp = client.delete(f"/api/nutrition/my-foods/{my_food_id}")
    assert del_resp.status_code == 200
    listed_after = client.get("/api/nutrition/my-foods").json()["my_foods"]
    assert not any(f["my_food_id"] == my_food_id for f in listed_after)


def test_saved_meal_create_and_log(client, session):
    food = _seed_food(session)
    _login(client)
    resp = client.post("/api/nutrition/saved-meals", json={"name": "Post-workout shake", "items": [{"food_id": food.id, "quantity": 1, "unit": "serving"}]})
    assert resp.status_code == 200
    saved_id = resp.json()["id"]

    log_resp = client.post(f"/api/nutrition/saved-meals/{saved_id}/log", json={"meal": "post_workout"})
    assert log_resp.status_code == 200
    assert len(log_resp.json()["logged"]) == 1


def test_targets_get_put_roundtrip(client, session):
    _login(client)
    resp = client.put("/api/nutrition/targets", json={"protein_g_per_kg": 2.0})
    assert resp.status_code == 200

    get_resp = client.get("/api/nutrition/targets")
    assert get_resp.json()["settings"]["protein_g_per_kg"] == 2.0


def test_targets_rejects_unknown_kcal_source(client):
    _login(client)
    resp = client.put("/api/nutrition/targets", json={"kcal_target_source": "bogus"})
    assert resp.status_code == 422


def test_photo_estimate_without_a_configured_key_returns_422(client):
    _login(client)
    resp = client.post(
        "/api/nutrition/photo-estimate",
        files={"photo": ("meal.jpg", b"fake-bytes", "image/jpeg")},
    )
    assert resp.status_code == 422
    assert "API key" in resp.json()["detail"]


def test_photo_estimate_rejects_unsupported_content_type(client):
    _login(client)
    resp = client.post(
        "/api/nutrition/photo-estimate",
        files={"photo": ("meal.gif", b"fake-bytes", "image/gif")},
    )
    assert resp.status_code == 422


def test_nutrition_routes_require_auth(client):
    resp = client.get("/api/nutrition/logs")
    assert resp.status_code == 401

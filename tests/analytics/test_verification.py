"""Session 26: the three verification states, from the recorded (synthetic) Concept2 fixtures."""

import json
from pathlib import Path
from types import SimpleNamespace

from catch.analytics import verification as vf

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "concept2"


def _activity(name, **cols):
    data = json.loads((FIX / name).read_text())["data"]
    return SimpleNamespace(raw_json=json.dumps({k: v for k, v in data.items() if k != "stroke_data"}), c2_user_id=None, c2_verified=None, c2_weight_class=None, **cols)


def classify(meta, account="1", **kw):
    return vf.classify(source_kind="concept2_result", connected_account_id=account, result_user_id=meta["user_id"], provider_verified=meta["verified"], **kw)


def test_metadata_falls_back_to_the_stored_payload_for_rows_synced_before_the_columns_existed():
    meta = vf.concept2_meta(_activity("result_101_detail.json"))
    assert meta["user_id"] == "1" and meta["verified"] is False and meta["weight_class"] == "H"


def test_a_promoted_column_wins_over_the_payload():
    a = _activity("result_101_detail.json")
    a.c2_verified, a.c2_user_id = True, "9"
    meta = vf.concept2_meta(a)
    assert meta["verified"] is True and meta["user_id"] == "9"


def test_concept2_flag_false_is_provider_linked_not_verified():
    assert classify(vf.concept2_meta(_activity("result_101_detail.json"))) == vf.PROVIDER_LINKED


def test_flag_true_through_the_users_own_account_is_verified():
    a = _activity("result_101_detail.json")
    a.c2_verified = True
    assert classify(vf.concept2_meta(a)) == vf.VERIFIED


def test_a_result_from_a_different_concept2_account_is_never_verified():
    a = _activity("result_101_detail.json")
    a.c2_verified = True
    assert classify(vf.concept2_meta(a), account="2") == vf.PROVIDER_LINKED


def test_an_unknown_flag_or_missing_owner_never_verifies():
    a = _activity("result_101_detail.json")
    a.c2_verified = None
    a.raw_json = json.dumps({"user_id": 1})
    assert classify(vf.concept2_meta(a)) == vf.PROVIDER_LINKED
    assert vf.classify(source_kind="concept2_result", connected_account_id="1", result_user_id=None, provider_verified=True) == vf.PROVIDER_LINKED


def test_no_concept2_connection_means_unverified():
    a = _activity("result_101_detail.json")
    a.c2_verified = True
    assert classify(vf.concept2_meta(a), account=None) == vf.UNVERIFIED


def test_a_piece_is_never_verified_even_when_absorbed_from_a_verified_result():
    assert vf.classify(source_kind="piece", connected_account_id="1", result_user_id="1", provider_verified=True, piece_source="concept2") == vf.PROVIDER_LINKED
    assert vf.classify(source_kind="piece", connected_account_id=None, result_user_id=None, provider_verified=None, piece_source="manual") == vf.UNVERIFIED
    assert vf.classify(source_kind="piece", connected_account_id=None, result_user_id=None, provider_verified=None, piece_source="photo") == vf.UNVERIFIED


def test_every_state_has_a_plain_explanation():
    assert set(vf.EXPLANATION) == set(vf.STATES)

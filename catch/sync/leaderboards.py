"""Session 26 (docs/leaderboards.md): the athlete-facing leaderboard service. Owned data (settings, the private snapshot of
each publication) goes through the request's session; everything another user can see goes through
catch.sync.leaderboard_store. Every public JSON shape is built by catch.analytics.leaderboards.public_entry_view."""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from sqlmodel import Session, func, select

from catch.analytics import leaderboards as lb
from catch.analytics import verification as vf
from catch.core import config, secret_store, tenant
from catch.core.models import Activity, CanonicalActivity, LeaderboardSettings, Piece, ProviderConnection, ResultPublication
from catch.sync import leaderboard_store as store

logger = logging.getLogger("catch.leaderboards")

PUBLICATIONS_PER_DAY = 20
RANKED_TYPES = ("FixedDistanceSplits", "FixedTimeSplits")
PAGE_MAX = 100


class LeaderboardError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def available() -> bool:
    return tenant.is_public()


# ---------------------------------------------------------------- settings

def settings_row(session: Session) -> LeaderboardSettings:
    row = session.get(LeaderboardSettings, tenant.pk())
    if row is None:
        row = LeaderboardSettings()
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _settings_dict(row: LeaderboardSettings) -> dict:
    return {
        "opted_in": row.opted_in, "date_precision": row.date_precision, "show_age_band": row.show_age_band,
        "show_weight_class": row.show_weight_class, "age_source": row.age_source, "self_declared_band": row.self_declared_band,
        "min_age_attested": row.attested_min_age_at is not None, "guardian_attested": row.guardian_attested_at is not None,
        "consent_version": row.consent_version,
    }


def _athlete(owner: str) -> Optional[dict]:
    return store.athlete_for_owner(owner)


def update_settings(session: Session, body: dict) -> dict:
    """Display choices and attestations. Opting in/out are their own calls below."""
    row = settings_row(session)
    if "date_precision" in body and body["date_precision"] is not None:
        try:
            lb.effective_precision(body["date_precision"], False)
        except ValueError as exc:
            raise LeaderboardError(str(exc)) from None
        row.date_precision = body["date_precision"]
    for flag in ("show_age_band", "show_weight_class"):
        if body.get(flag) is not None:
            setattr(row, flag, bool(body[flag]))
    if "self_declared_band" in body:
        band = body["self_declared_band"]
        if band is not None:
            if row.age_source == "concept2_profile":
                raise LeaderboardError("Your age band comes from your Concept2 profile and can't be self-declared.", 409)
            try:
                lb.from_declared_label(band)
            except ValueError:
                raise LeaderboardError(f"age band must be one of {', '.join(lb.AGE_LABELS)}") from None
        row.self_declared_band = band
        if band is not None:
            row.age_source = "self_declared"
    if body.get("attest_min_age") is True and row.attested_min_age_at is None:
        row.attested_min_age_at = _now()
    if body.get("attest_guardian") is True and row.guardian_attested_at is None:
        row.guardian_attested_at = _now()
    row.updated_at = _now()
    session.commit()
    owner = tenant.current_owner()
    athlete = _athlete(owner)
    if athlete is not None and ("handle" in body or "display_mode" in body):
        _write_athlete(owner, body, athlete)
    return _settings_dict(row)


def _write_athlete(owner: str, body: dict, existing: Optional[dict]) -> dict:
    mode = body.get("display_mode") or (existing or {}).get("display_mode") or "handle"
    handle = (existing or {}).get("handle")
    if "handle" in body:
        try:
            handle = lb.validate_handle(body["handle"]) if body["handle"] else None
        except ValueError as exc:
            raise LeaderboardError(str(exc)) from None
    if mode == "handle" and not handle:
        raise LeaderboardError("Choose a public handle, or switch to anonymous.")
    try:
        return store.upsert_athlete(owner, handle=handle, display_mode=mode, active=(existing or {}).get("active", True))
    except store.StoreError as exc:
        raise LeaderboardError(str(exc), exc.status) from None
    except ValueError as exc:
        raise LeaderboardError(str(exc)) from None


def opt_in(session: Session, body: dict) -> dict:
    """Requires the athlete's explicit confirmation, a display choice, and the age attestation that applies."""
    if body.get("confirm") is not True:
        raise LeaderboardError("Confirm that you want to appear on public leaderboards.")
    row = settings_row(session)
    update_settings(session, {k: v for k, v in body.items() if k in ("attest_min_age", "attest_guardian", "self_declared_band", "date_precision", "show_age_band", "show_weight_class")})
    owner = tenant.current_owner()
    existing = _athlete(owner)
    _write_athlete(owner, {"handle": body.get("handle"), "display_mode": body.get("display_mode") or "handle"}, existing and {**existing, "active": True})
    row.opted_in = True
    row.consent_version = lb.CONSENT_VERSION
    row.opted_in_at = _now()
    session.commit()
    return my_state(session)


def opt_out(session: Session, body: dict) -> dict:
    if body.get("confirm") is not True:
        raise LeaderboardError("Confirm that you want to leave the public leaderboards.")
    owner = tenant.current_owner()
    row = settings_row(session)
    deleted = store.withdraw_all(owner, "user_opted_out", "The athlete opted out of public leaderboards.")
    existing = _athlete(owner)
    if existing is not None:
        store.upsert_athlete(owner, handle=None, display_mode="anonymous", active=False)
    for pub in session.exec(select(ResultPublication).where(ResultPublication.withdrawn_at.is_(None))).all():  # type: ignore[union-attr]
        if pub.entry_id in deleted:  # one a moderator closed is kept, so opting out can't undo that decision
            pub.withdrawn_at = _now()
    row.opted_in = False
    session.commit()
    return my_state(session)


# ---------------------------------------------------------------- source resolution

def _c2_connection(session: Session) -> Optional[ProviderConnection]:
    return session.get(ProviderConnection, tenant.pk("concept2"))


def _c2_profile(session: Session) -> dict:
    from catch.sync import concept2_client

    return concept2_client.fetch_profile(session)


def _connected_account_id(session: Session) -> Optional[str]:
    row = _c2_connection(session)
    if row is None:
        return None
    if row.account_id is None:
        try:
            profile = _c2_profile(session)
        except Exception:
            logger.warning("could not read the Concept2 account id for verification")
            return None
        if profile.get("id") is None:
            return None
        row.account_id = str(profile["id"])
        session.commit()
    return row.account_id


def _resolve_age(session: Session, settings: LeaderboardSettings, on: date | None) -> Optional[tuple[Optional[int], Optional[str], str]]:
    """(age_years, adult_band, source). A date of birth Concept2 reports wins over a self-declared band, and is read and
    discarded — only the band survives. None means no age is known (Overall board only)."""
    if _c2_connection(session) is not None and on is not None:
        try:
            dob_text = _c2_profile(session).get("dob")
        except Exception:
            logger.warning("could not read the Concept2 profile for an age band")
            dob_text = None
            if settings.age_source == "concept2_profile":
                raise LeaderboardError("Couldn't reach Concept2 to read your age band. Try again in a moment.", 503) from None
        if dob_text:
            try:
                dob = date.fromisoformat(str(dob_text)[:10])
            except ValueError:
                dob = None
            if dob is not None:
                years, band = lb.split_age(lb.age_on(dob, on))
                if settings.age_source != "concept2_profile":
                    settings.age_source = "concept2_profile"
                    session.commit()
                return years, band, "concept2_profile"
    if settings.self_declared_band and settings.age_source != "concept2_profile":
        years, band = lb.from_declared_label(settings.self_declared_band)
        return years, band, "self_declared"
    return None


def _digest(*parts: Any) -> str:
    return hashlib.sha256("|".join("" if p is None else str(p) for p in parts).encode()).hexdigest()


def _activity_digest(a: Activity) -> str:
    m = vf.concept2_meta(a)
    return _digest("c2", a.distance, a.duration, a.workout_type, a.type, a.start.isoformat() if a.start else None, m["user_id"], m["verified"], m["weight_class"], bool(a.intervals_json))


def _piece_digest(p: Piece) -> str:
    return _digest("piece", p.distance_m, p.duration_s, p.source, p.has_intervals, p.concept2_activity_id)


def _result_from_ref(session: Session, ref: dict) -> dict:
    """Everything about one of the athlete's own results that ranking and verification need. Raises 404 for a missing one."""
    kind = ref.get("kind")
    if kind == "concept2_result":
        a = session.get(Activity, ref.get("id"))
        if a is None or a.source != "concept2":
            raise LeaderboardError("Not found.", 404)
        meta = vf.concept2_meta(a)
        has_intervals = bool(a.intervals_json and '"intervals"' in a.intervals_json)
        elig = lb.eligible_board(distance_m=a.distance, duration_s=a.duration, workout_type=a.workout_type, erg_type=a.type, has_intervals=has_intervals)
        return {"kind": kind, "id": a.id, "activity": a, "piece": None, "meta": meta, "elig": elig, "date": a.start.date() if a.start else None,
                "digest": _activity_digest(a), "result_id": str(a.external_id)}
    if kind == "piece":
        p = session.get(Piece, ref.get("id"))
        if p is None:
            raise LeaderboardError("Not found.", 404)
        canonical = session.get(CanonicalActivity, p.canonical_id)
        elig = lb.eligible_board(distance_m=p.distance_m, duration_s=p.duration_s, has_intervals=p.has_intervals, is_piece=True)
        return {"kind": kind, "id": p.id, "activity": None, "piece": p, "meta": {}, "elig": elig, "date": canonical.start.date() if canonical and canonical.start else None,
                "digest": _piece_digest(p), "result_id": str(p.id)}
    raise LeaderboardError("kind must be concept2_result or piece")


_UNSET: Any = object()


def _verification_for(session: Session, r: dict, account: Any = _UNSET) -> str:
    """`account` lets a caller that classifies many results resolve the connected Concept2 account once."""
    if r["kind"] == "piece":
        return vf.classify(source_kind="piece", connected_account_id=None, result_user_id=None, provider_verified=None, piece_source=r["piece"].source)
    if account is _UNSET:
        account = _connected_account_id(session)
    return vf.classify(source_kind="concept2_result", connected_account_id=account, result_user_id=r["meta"]["user_id"], provider_verified=r["meta"]["verified"])


def _publication_for(session: Session, r: dict) -> Optional[ResultPublication]:
    col = ResultPublication.activity_id if r["kind"] == "concept2_result" else ResultPublication.piece_id
    return session.exec(select(ResultPublication).where(col == r["id"], ResultPublication.withdrawn_at.is_(None))).first()  # type: ignore[union-attr]


# ---------------------------------------------------------------- my results

def my_results(session: Session, *, board: str | None = None, state: str | None = None, limit: int = 100) -> list[dict]:
    owner = tenant.current_owner()
    check_source_changes(session)
    statuses = store.entry_statuses(owner)
    again = store.republishable(owner)
    out: list[dict] = []
    acts = session.exec(
        select(Activity).where(Activity.source == "concept2", Activity.type == "rower", Activity.workout_type.in_(RANKED_TYPES)).order_by(Activity.start.desc()).limit(2000)  # type: ignore[union-attr,attr-defined]
    ).all()
    refs = [{"kind": "concept2_result", "id": a.id} for a in acts]
    covered = {(a.id) for a in acts if lb.eligible_board(distance_m=a.distance, duration_s=a.duration, workout_type=a.workout_type, erg_type=a.type)}
    for p in session.exec(select(Piece).where(Piece.has_intervals == False)).all():  # noqa: E712
        if p.concept2_activity_id in covered:
            continue  # the Concept2 result itself is the authoritative entry
        refs.append({"kind": "piece", "id": p.id})
    account: Any = _UNSET
    for ref in refs:
        r = _result_from_ref(session, ref)
        if r["elig"] is None:
            continue
        if account is _UNSET and r["kind"] == "concept2_result":
            account = _connected_account_id(session)
        verification = _verification_for(session, r, account)
        if (board and r["elig"][0] != board) or (state and verification != state):
            continue
        pub = _publication_for(session, r)
        shown = lb.format_value(*r["elig"])
        out.append({
            "ref": {"kind": r["kind"], "id": r["id"]}, "board_key": r["elig"][0], "board_label": lb.BOARDS[r["elig"][0]]["label"],
            "result": shown["result"], "split_500m": shown["split_500m"], "verification": verification,
            "verification_label": lb.VERIFICATION_LABELS[verification], "verification_explained": vf.EXPLANATION[verification],
            "performed_on": r["date"].isoformat() if r["date"] else None,  # the athlete's own view; never in a public shape
            "published": (statuses.get(pub.entry_id, "withdrawn") if pub else None), "entry_id": pub.entry_id if pub else None,
            "can_republish": bool(pub and pub.entry_id in again),
        })
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- preview / publish

def _prefs(settings: LeaderboardSettings, prefs: dict) -> dict:
    return {
        "show_age_band": settings.show_age_band if prefs.get("show_age_band") is None else bool(prefs["show_age_band"]),
        "show_weight_class": settings.show_weight_class if prefs.get("show_weight_class") is None else bool(prefs["show_weight_class"]),
        "date_precision": prefs.get("date_precision") or settings.date_precision,
        "note": prefs.get("note"),
        "note_public": bool(prefs.get("note_public")),
    }


def _prepare(session: Session, ref: dict, prefs: dict) -> dict:
    settings = settings_row(session)
    if not settings.opted_in:
        raise LeaderboardError("Opt in to public leaderboards first.", 403)
    owner = tenant.current_owner()
    athlete = _athlete(owner)
    if athlete is None or not athlete["active"]:
        raise LeaderboardError("Opt in to public leaderboards first.", 403)
    r = _result_from_ref(session, ref)
    if r["elig"] is None:
        raise LeaderboardError("This result doesn't match a leaderboard: it must be an uninterrupted, exact 500, 1,000, 2,000, 5,000 or 6,000 m piece, or an exact 30 or 60 minute one.")
    board_key, value = r["elig"]
    verification = _verification_for(session, r)
    p = _prefs(settings, prefs)
    try:
        note = lb.validate_note(p["note"])
    except ValueError as exc:
        raise LeaderboardError(str(exc)) from None
    age = _resolve_age(session, settings, r["date"])
    age_years, adult_band, age_source = (age if age else (None, None, None))
    gate = lb.age_gate(age_years, has_min_age_attestation=settings.attested_min_age_at is not None, has_guardian_attestation=settings.guardian_attested_at is not None)
    if gate == "below_minimum_age":
        raise LeaderboardError(f"Public leaderboards are for athletes aged {lb.MIN_PUBLISH_AGE} and over.", 403)
    if gate == "age_attestation_required":
        raise LeaderboardError("Confirm your age first: attest that you are old enough, or add an age band.", 403)
    if gate == "guardian_consent_required":
        raise LeaderboardError(f"Athletes under {lb.GUARDIAN_CONSENT_BELOW} need a parent or guardian's consent recorded first.", 403)
    minor = lb.is_minor(age_years, age_source)
    precision = lb.effective_precision(p["date_precision"], minor)
    label = lb.public_age_label(age_years, adult_band) if (age and p["show_age_band"]) else None
    weight = r["meta"].get("weight_class") if (p["show_weight_class"] and r["kind"] == "concept2_result") else None
    entry = {
        "entry_id": "preview", "board_key": board_key, "value": value, "verification": verification, "age_label": label,
        "age_provenance": age_source if label else None, "weight_class": weight, "date_label": lb.date_label(r["date"], precision),
        "note": note if p["note_public"] else None,
    }
    view = lb.public_entry_view(entry, {**athlete, "public_id": athlete["public_id"]})
    return {"r": r, "entry": entry, "view": view, "hash": lb.preview_hash(view), "athlete": athlete, "age": (age_years, adult_band, age_source),
            "age_label_all": lb.public_age_label(age_years, adult_band) if age else None, "minor": minor, "precision": precision, "prefs": p, "note": note,
            "verification": verification}


def _disclosures(prep: dict) -> list[str]:
    out = ["Everything in this preview is public to signed-in Catch users. Nothing else about you or your training is shared."]
    if prep["entry"]["date_label"] is None:
        out.append("No date is shown.")
    else:
        out.append(f"Only the {prep['precision']} of the result is shown, not the exact date.")
    if prep["minor"]:
        out.append("Because you are under 18, your date is limited to the year and you appear under your chosen handle or as anonymous only.")
    out.append(vf.EXPLANATION[prep["verification"]])
    return out


def preview(session: Session, ref: dict, prefs: dict) -> dict:
    prep = _prepare(session, ref, prefs)
    return {"entry": prep["view"], "preview_hash": prep["hash"], "disclosures": _disclosures(prep), "ranked": prep["verification"] == "verified"}


def _not_restricted(scope: str) -> None:
    from catch.sync import restrictions

    try:
        restrictions.assert_allowed(tenant.current_owner(), scope)
    except restrictions.Restricted as exc:
        raise LeaderboardError(str(exc), 403) from None


def publish(session: Session, ref: dict, prefs: dict, *, confirm: bool, preview_hash: str) -> dict:
    owner = tenant.current_owner()
    _not_restricted("publish")
    if confirm is not True:
        raise LeaderboardError("Confirm publishing after reviewing the preview.")
    since = _now() - timedelta(days=1)
    made = session.exec(select(func.count()).select_from(ResultPublication).where(ResultPublication.created_at >= since)).one()
    if made >= PUBLICATIONS_PER_DAY:
        raise LeaderboardError("You've reached today's publishing limit. Try again tomorrow.", 429)
    check_source_changes(session)
    prep = _prepare(session, ref, prefs)
    if prep["hash"] != preview_hash:
        raise LeaderboardError("The preview is out of date. Review it again before publishing.", 409)
    r = prep["r"]
    existing = _publication_for(session, r)
    if existing is not None:
        if existing.entry_id not in store.republishable(owner):
            raise LeaderboardError("You've already published this result.", 409)
        # Hidden only because its source changed: publishing again is the way back, and replaces the old entry (recorded).
        store.withdraw(owner, existing.entry_id, reason_code="replaced_by_republish", reason_text="The athlete reviewed the changed result and published it again.")
        existing.withdrawn_at = _now()
        session.commit()
    e = prep["entry"]
    if r["kind"] == "concept2_result":
        provider, provider_user_id = "concept2", r["meta"]["user_id"] or f"owner:{owner}"
    else:
        provider, provider_user_id = "catch_piece", owner
    verified_account = r["meta"].get("user_id") if prep["verification"] == "verified" else None
    key = lb.athlete_key(secret_store.master_secret(), "concept2" if verified_account else None, verified_account, owner)
    age_years, adult_band, age_source = prep["age"]
    if e["age_label"] is None:
        age_years, adult_band = None, None  # an age the athlete didn't agree to show is not stored on the public row at all
    try:
        entry_id = store.create_entry(
            owner, public_id=prep["athlete"]["public_id"], athlete_key=key, board_key=e["board_key"], value=e["value"], verification=e["verification"],
            provider=provider, provider_user_id=provider_user_id, provider_result_id=r["result_id"], age_years=age_years, age_band=adult_band,
            age_label=e["age_label"], age_provenance=e["age_provenance"], weight_class=e["weight_class"], date_label=e["date_label"], note=e["note"],
        )
    except store.StoreError as exc:
        raise LeaderboardError(str(exc), exc.status) from None
    meta = r["meta"]
    try:
        session.add(ResultPublication(
            entry_id=entry_id, board_key=e["board_key"], verification=e["verification"], source_kind=r["kind"],
            activity_id=r["id"] if r["kind"] == "concept2_result" else None, canonical_id=r["activity"].canonical_id if r["activity"] else (r["piece"].canonical_id if r["piece"] else None),
            piece_id=r["id"] if r["kind"] == "piece" else None, provider=provider, provider_user_id=provider_user_id, provider_result_id=r["result_id"],
            original_date_utc=meta.get("date_utc") or meta.get("date"), original_timezone=meta.get("timezone"), value=e["value"], source_digest=r["digest"],
            note=prep["note"], note_public=prep["prefs"]["note_public"], show_age_band=prep["prefs"]["show_age_band"],
            show_weight_class=prep["prefs"]["show_weight_class"], date_precision=prep["precision"],
        ))
        session.commit()
    except Exception:
        session.rollback()
        store.discard_unpublished(owner, entry_id)
        raise
    if prep["age_label_all"] and prep["prefs"]["show_age_band"]:
        store.set_athlete_age(owner, prep["age_label_all"], age_source)
    view = {**prep["view"], "entry_id": entry_id}
    return {"published": True, "entry": view}


def update_publication(session: Session, entry_id: str, body: dict) -> dict:
    pub = session.exec(select(ResultPublication).where(ResultPublication.entry_id == entry_id, ResultPublication.withdrawn_at.is_(None))).first()  # type: ignore[union-attr]
    if pub is None:
        raise LeaderboardError("Not found.", 404)
    note = pub.note if "note" not in body else body["note"]
    try:
        note = lb.validate_note(note)
    except ValueError as exc:
        raise LeaderboardError(str(exc)) from None
    public = pub.note_public if body.get("note_public") is None else bool(body["note_public"])
    try:
        store.set_note(tenant.current_owner(), entry_id, note if public else None)
    except store.StoreError as exc:
        raise LeaderboardError(str(exc), exc.status) from None
    pub.note, pub.note_public = note, public
    session.commit()
    return {"entry_id": entry_id, "note": note, "note_public": public}


def unpublish(session: Session, entry_id: str, *, confirm: bool) -> dict:
    if confirm is not True:
        raise LeaderboardError("Confirm taking this result down.")
    pub = session.exec(select(ResultPublication).where(ResultPublication.entry_id == entry_id, ResultPublication.withdrawn_at.is_(None))).first()  # type: ignore[union-attr]
    if pub is None:
        raise LeaderboardError("Not found.", 404)
    try:
        deleted = store.withdraw(tenant.current_owner(), entry_id)
    except store.StoreError as exc:
        raise LeaderboardError(str(exc), exc.status) from None
    if not deleted:
        return {"withdrawn": False, "kept_for_review": True,
                "message": "This result is closed by a moderation decision, so it stays closed. Your request is recorded; you can appeal the decision."}
    pub.withdrawn_at = _now()
    session.commit()
    return {"withdrawn": True}


def check_source_changes(session: Session) -> int:
    """After a sync: a published result whose source row no longer matches what was published is hidden, with a recorded
    reason, until the athlete reviews and republishes it. Returns how many were hidden."""
    if not available():
        return 0
    owner = tenant.current_owner()
    hidden = 0
    for pub in session.exec(select(ResultPublication).where(ResultPublication.withdrawn_at.is_(None))).all():  # type: ignore[union-attr]
        try:
            r = _result_from_ref(session, {"kind": pub.source_kind, "id": pub.activity_id if pub.source_kind == "concept2_result" else pub.piece_id})
            changed = r["digest"] != pub.source_digest
        except LeaderboardError:
            changed = True  # the source row is gone
        if changed and store.system_hide(owner, pub.entry_id, "source_changed", "The underlying result changed after it was published, so it was hidden until you review and republish it."):
            hidden += 1
    return hidden


# ---------------------------------------------------------------- state / profile / boards

def my_state(session: Session) -> dict:
    owner = tenant.current_owner()
    check_source_changes(session)
    settings = settings_row(session)
    athlete = _athlete(owner)
    statuses = store.entry_statuses(owner)
    pubs = session.exec(select(ResultPublication).order_by(ResultPublication.id.desc())).all()  # type: ignore[union-attr]
    return {
        "available": True,
        "is_moderator": owner in config.settings.moderators,
        "settings": _settings_dict(settings),
        "athlete": ({"athlete_id": athlete["public_id"], "handle": athlete["handle"], "display_mode": athlete["display_mode"], "active": athlete["active"]} if athlete else None),
        "publications": [
            {"entry_id": p.entry_id, "board_key": p.board_key, "verification": p.verification, "status": ("withdrawn" if p.withdrawn_at or p.entry_id not in statuses else statuses[p.entry_id]),
             "note": p.note, "note_public": p.note_public, "created_at": p.created_at.isoformat()}
            for p in pubs
        ],
        "clubs": store.public_clubs_of(owner),
        "moderation": {"events": store.my_events(owner), "appeals": store.my_appeals(owner)},
        "age_bands": list(lb.AGE_LABELS),
        "date_precisions": list(lb.PRECISIONS),
        "min_age": lb.MIN_PUBLISH_AGE,
        "guardian_below": lb.GUARDIAN_CONSENT_BELOW,
    }


def board_list() -> list[dict]:
    return [{"board_key": k, "label": v["label"], "kind": v["kind"], "ranks_by": "fastest time" if v["kind"] == "distance" else "furthest distance"} for k, v in lb.BOARDS.items()]


def _filter_rows(rows: list[dict], *, age: str | None, weight: str | None, club: str | None) -> list[dict]:
    if age:
        rows = [r for r in rows if age in lb.memberships(r["age_years"], r["age_band"]) and r["age_label"] is not None]
    if weight == "lightweight":
        rows = [r for r in rows if r["weight_class"] == "L"]
    if club:
        rows = [r for r in rows if club in r["clubs"]]
    return rows


def board(session: Session, board_key: str, *, age: str | None = None, weight: str | None = None, club: str | None = None,
          verification: str = "verified", offset: int = 0, limit: int = 50) -> dict:
    if board_key not in lb.BOARDS:
        raise LeaderboardError("Not found.", 404)
    if age and age not in lb.AGE_LABELS:
        raise LeaderboardError("unknown age band")
    if weight not in (None, "any", "lightweight"):
        raise LeaderboardError("weight must be any or lightweight")
    if verification not in ("verified", "include_unverified"):
        raise LeaderboardError("verification must be verified or include_unverified")
    limit = max(1, min(int(limit), PAGE_MAX))
    offset = max(0, int(offset))
    owner = tenant.current_owner()
    rows = _filter_rows(store.board_rows(board_key), age=age, weight=weight, club=club)
    ranked = lb.rank_board(rows, board_key, verification == "include_unverified")

    def render(r: dict) -> dict:
        v = lb.public_entry_view(r, {"public_id": r["public_id"], "handle": r["handle"], "display_mode": r["display_mode"]}, rank=r["rank"])
        return {**v, "is_you": r["owner_id"] == owner}

    spec = lb.BOARDS[board_key]
    mine = next((render(r) for r in ranked["ranked"] if r["owner_id"] == owner), None) or next((render(r) for r in ranked["unverified"] if r["owner_id"] == owner), None)
    return {
        "context": {"board_key": board_key, "label": spec["label"], "ranks_by": "fastest time" if spec["kind"] == "distance" else "furthest distance", "age": age,
                    "weight": weight or "any", "club": club, "verification": verification, "ranked_athletes": len(ranked["ranked"]),
                    "ties": "Equal results share a rank (1, 2, 2, 4). One best result per athlete."},
        "entries": [render(r) for r in ranked["ranked"][offset: offset + limit]],
        "unverified": [render(r) for r in ranked["unverified"][offset: offset + limit]],
        "you": mine,
        "total": len(ranked["ranked"]),
        "offset": offset,
        "limit": limit,
    }


def athlete_profile(public_id: str) -> dict:
    athlete = store.athlete_by_public_id(public_id)
    if athlete is None or not athlete["active"]:
        raise LeaderboardError("Not found.", 404)
    entries = store.entries_for_athlete(public_id)
    best: dict[str, dict] = {}
    for e in sorted(entries, key=lambda x: (x["board_key"], x["verification"] != "verified", x["value"] if lb.BOARDS[x["board_key"]]["kind"] == "distance" else -x["value"])):
        best.setdefault(e["board_key"], e)
    views = [lb.public_entry_view({**e}, {"public_id": athlete["public_id"], "handle": athlete["handle"], "display_mode": athlete["display_mode"]}) for e in best.values()]
    name = lb.ANONYMOUS_NAME if athlete["display_mode"] == "anonymous" or not athlete["handle"] else athlete["handle"]
    return {"athlete_id": athlete["public_id"], "name": name, "results": views}


def my_profile_preview(session: Session) -> dict:
    athlete = _athlete(tenant.current_owner())
    if athlete is None or not athlete["active"]:
        raise LeaderboardError("Opt in to public leaderboards first.", 403)
    return {**athlete_profile(athlete["public_id"]), "is_preview": True}


# ---------------------------------------------------------------- reports, appeals

def report_entry(session: Session, entry_id: str, reason: str, detail: str | None) -> dict:
    try:
        return store.report(tenant.current_owner(), entry_id, reason, detail)
    except store.StoreError as exc:
        raise LeaderboardError(str(exc), exc.status) from None


def appeal_entry(session: Session, entry_id: str, text: str) -> dict:
    try:
        return store.appeal(tenant.current_owner(), entry_id, text)
    except store.StoreError as exc:
        raise LeaderboardError(str(exc), exc.status) from None

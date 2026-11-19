"""The Privacy center's backend (session 28; docs/data-inventory.md, docs/legal/data-deletion-policy.md).

* **Export** — everything the person owns, as gzip-compressed newline-delimited JSON, streamed table by table (bounded memory). Sealed
  credentials, token hashes and push-subscription secrets are never in it; they are listed as present-but-withheld.
* **Delete by category** — a fixed allowlist, each category a short list of tables cleared through the tenant-scoped ORM (so it can only
  ever touch the caller's own rows).
* **Summary** — counts per category plus what is publicly visible about the person.

Nothing here reads another person's data: owned tables go through the tenant filter, global tables through account_store's
owner-column readers."""

from __future__ import annotations

import base64
import json
import zlib
from datetime import date, datetime, timezone
from typing import Any, Iterator

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlmodel import Session, SQLModel

from catch.core import db as db_module
from catch.core import tenant
from catch.core.tenant import OwnedOrShared, OwnedStrict
from catch.sync import account_store

FORMAT = 1

# Tables left out of the export entirely, and why. A test fails when a new owned table is in neither this dict nor the export.
EXPORT_SKIPPED = {
    "oauth_tokens": "legacy sealed provider tokens (personal installs only); secrets are never exported",
    "coach_credentials": "legacy sealed AI keys (personal installs only); secrets are never exported",
}
# Columns withheld from otherwise-exported tables: the sealed/secret part of a row whose other columns are the person's own data.
WITHHELD_COLUMNS = {
    "ai_credentials": {"key_enc"},
    "provider_connections": {"access_enc", "refresh_enc", "credential_enc"},
    "api_tokens": {"token_hash"},
    "push_subscriptions": {"endpoint", "p256dh", "auth"},
}

# Deletion categories: key -> (label, what it removes, tables). Each is its own explicit, confirmed request.
DELETE_CATEGORIES: dict[str, dict] = {
    "conversations": {"label": "Coach conversations", "tables": ["coach_messages", "coach_conversations"], "note": "Every chat with the coach, including the tool results saved in it."},
    "memory": {"label": "Coach memory", "tables": ["athlete_facts", "goals"], "note": "The facts and goals the coach remembers about you."},
    "gps": {"label": "GPS tracks, routes and weather", "tables": ["activity_tracks", "routes", "activity_weather"], "note": "Location data attached to your workouts. The workouts themselves stay."},
    "media": {"label": "Uploaded photos", "tables": ["piece_photos"], "note": "Photos of erg screens you attached to pieces, including any stored files."},
    "notes_checkins": {"label": "Notes and check-ins", "tables": ["notes", "checkins", "illness_acks"], "note": "Your workout notes, morning check-ins (including niggle notes) and illness-flag responses."},
    "nutrition": {"label": "Nutrition logs", "tables": ["food_logs", "my_foods", "saved_meals", "nutrition_targets"], "note": "Everything you logged or saved in Nutrition."},
    "wellness_body": {"label": "Recovery, sleep and body data", "tables": ["daily_wellness", "wellness_readings", "daily_scores", "body_comp"], "note": "HRV, sleep, resting heart rate, body composition and the scores computed from them. A connected source will import them again on its next sync — disconnect it first if you want them gone for good."},
    "notification_log": {"label": "Notification history", "tables": ["notification_log"], "note": "The record of notifications Catch sent you."},
    "ai_usage": {"label": "AI usage history", "tables": ["ai_usage_events"], "note": "The log of AI calls and what they cost."},
}


def owned_classes() -> list[type]:
    import catch.core.models  # noqa: F401  (registers the tables)

    return sorted(
        (m.class_ for m in SQLModel._sa_registry.mappers if issubclass(m.class_, (OwnedStrict, OwnedOrShared))),
        key=lambda c: c.__tablename__,
    )


def exported_tables() -> list[str]:
    return [c.__tablename__ for c in owned_classes() if c.__tablename__ not in EXPORT_SKIPPED]


def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"base64": base64.b64encode(bytes(value)).decode()}
    return value


def _row(obj: Any, table: str) -> dict:
    drop = WITHHELD_COLUMNS.get(table, set())
    return {c.name: _encode(getattr(obj, c.key if hasattr(c, "key") else c.name, None)) for c in obj.__table__.columns if c.name not in drop}


def iter_export(owner_id: str, *, now: datetime | None = None) -> Iterator[bytes]:
    """The export file, compressed as it is produced. The caller streams it; nothing is built in memory beyond one batch of rows."""
    compressor = zlib.compressobj(6, zlib.DEFLATED, 31)  # wbits 31 = gzip container
    counts: dict[str, int] = {}

    def emit(obj: dict) -> bytes:
        return compressor.compress((json.dumps(obj, separators=(",", ":"), default=str) + "\n").encode())

    started = (now or datetime.now(timezone.utc)).isoformat()
    chunk = emit({"manifest": {"format": FORMAT, "kind": "catch-account-export", "created": started, "owner": owner_id, "note": "One JSON object per line: {table,row}. Binary columns are base64. Secrets are withheld (see 'withheld')."}})
    yield chunk
    with tenant.use_owner(owner_id), Session(db_module.engine) as session:
        for cls in owned_classes():
            table = cls.__tablename__
            if table in EXPORT_SKIPPED:
                continue
            stmt = select(cls)
            if issubclass(cls, OwnedOrShared):
                stmt = stmt.where(cls.owner_id == owner_id)  # type: ignore[attr-defined]  # not the shared reference rows
            n = 0
            buffer = b""
            for obj in session.scalars(stmt.execution_options(yield_per=200)):
                buffer += emit({"table": table, "row": _row(obj, table)})
                n += 1
                if len(buffer) > 64 * 1024:
                    yield buffer
                    buffer = b""
            counts[table] = n
            if buffer:
                yield buffer
    for table in account_store.OWNER_COLUMN:
        n = 0
        buffer = b""
        for obj in account_store.iter_global_rows(owner_id, table):
            buffer += emit({"table": table, "row": _row(obj, table), "scope": "shared-with-others"})
            n += 1
            if len(buffer) > 64 * 1024:
                yield buffer
                buffer = b""
        counts[table] = n
        if buffer:
            yield buffer
    yield emit({"footer": {"counts": counts, "withheld": {**{t: sorted(c) for t, c in WITHHELD_COLUMNS.items()}, **{t: "table not exported" for t in EXPORT_SKIPPED}}}})
    yield compressor.flush()


def _count(db: Session, table: str) -> int:
    cls = next(c for c in owned_classes() if c.__tablename__ == table)
    stmt = select(func.count()).select_from(cls)
    if issubclass(cls, OwnedOrShared):
        stmt = stmt.where(cls.owner_id == tenant.current_owner())  # type: ignore[attr-defined]
    return db.execute(stmt).scalar() or 0


def summary(db: Session) -> dict:
    owner = tenant.current_owner()
    categories = [
        {"key": key, "label": spec["label"], "note": spec["note"], "rows": sum(_count(db, t) for t in spec["tables"])}
        for key, spec in DELETE_CATEGORIES.items()
    ]
    return {
        "categories": categories,
        "totals": {"workouts": _count(db, "canonical_activities"), "tables_exported": len(exported_tables())},
        "public": account_store.exposure(owner) if tenant.is_public() else None,
    }


def delete_category(db: Session, key: str) -> dict:
    spec = DELETE_CATEGORIES.get(key)
    if spec is None:
        raise KeyError(key)
    removed = 0
    classes = {c.__tablename__: c for c in owned_classes()}
    for table in spec["tables"]:
        cls = classes[table]
        stmt = sa_delete(cls)
        if issubclass(cls, OwnedOrShared):
            stmt = stmt.where(cls.owner_id == tenant.current_owner())  # type: ignore[attr-defined]
        removed += db.execute(stmt).rowcount or 0
    db.commit()
    return {"category": key, "rows_removed": removed}

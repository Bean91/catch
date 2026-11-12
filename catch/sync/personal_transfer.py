"""Session 24 (docs/personal-to-public.md): moving a personal install's data into a public account — only when the
owner chooses to, only by running these two commands, never automatically.

`export_personal` writes one gzip'd JSON-lines file from the personal SQLite database. `import_into_account` reads it into
a public account *as that user* (their own tenant context, so row level security applies to the import too), giving every
row a fresh id and re-pointing every reference at the new ids. What is not carried over, and why, is spelled out in
EXCLUDED_TABLES: credentials and device bindings (they must be re-created in the new account), derived data (it is
recomputed), and AI conversation history (it embeds opaque tool results)."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import select
from sqlmodel import Session, SQLModel

from catch.core import tenant, tenant_hooks
from catch.core.models import Activity, DailyWellness
from catch.core.tenant import OwnedOrShared, OwnedStrict

FORMAT = 1

EXCLUDED_TABLES = {
    # secrets and anything bound to this install or device: re-create them in the new account
    "oauth_tokens": "source connections must be re-authorised",
    "ai_credentials": "AI keys are never exported",
    "coach_credentials": "AI keys are never exported",
    "api_tokens": "device tokens are bound to this install",
    "push_subscriptions": "push subscriptions belong to a browser",
    "notification_log": "tied to push subscriptions",
    "sync_state": "sync cursors belong to the old connections",
    "coach_settings": "contains a model endpoint URL and spend caps for this install",
    "ai_usage_events": "spend history of the old provider keys",
    # derived: recomputed from what is imported
    "daily_scores": "recomputed from the imported wellness and activities",
    "recommendations": "regenerated",
    # opaque
    "coach_conversations": "chat history embeds tool results with ids that can't be re-pointed safely",
    "coach_messages": "see coach_conversations",
}

# JSON text columns that embed ids of other rows, and the id keys inside them.
EMBEDDED_IDS = {
    "saved_meals": ("items_json", {"food_id": "foods"}),
    "strength_templates": ("items_json", {"exercise_id": "exercises", "gym_station_id": "gym_stations"}),
    "workout_templates": ("structure_json", {"exercise_id": "exercises"}),
    "planned_workouts": ("structure_json", {"exercise_id": "exercises"}),
}

# References that close a cycle (or point at the same table): set after every row exists.
DEFERRED = {("canonical_activities", "absorbed_into_piece_id"), ("activities", "linked_activity_id")}


class ImportRefused(Exception):
    pass


def _classes() -> dict[str, type]:
    return {
        m.class_.__tablename__: m.class_
        for m in SQLModel._sa_registry.mappers
        if issubclass(m.class_, (OwnedStrict, OwnedOrShared))
    }


def _ordered_tables() -> list[str]:
    """Parents before children, for the tables that are exported/imported."""
    classes = _classes()
    refs = tenant_hooks.reference_columns()
    deps: dict[str, set[str]] = {t: set() for t in classes}
    for child, col, parent in refs:
        if (child, col) in DEFERRED or child == parent or child not in deps or parent not in deps:
            continue
        deps[child].add(parent)
    for table, (_, keys) in EMBEDDED_IDS.items():
        deps[table].update(p for p in keys.values() if p in deps and p != table)
    order: list[str] = []
    ready = sorted(t for t, d in deps.items() if not d)
    done: set[str] = set()
    while ready:
        t = ready.pop(0)
        order.append(t)
        done.add(t)
        ready.extend(sorted(n for n, d in deps.items() if n not in done and n not in ready and d <= done))
    if len(order) != len(deps):
        raise RuntimeError(f"reference cycle among tables: {sorted(set(deps) - set(order))}")
    return [t for t in order if t not in EXCLUDED_TABLES]


def _encode(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return {"$d": value.isoformat()} if isinstance(value, datetime) else {"$date": value.isoformat()}
    if isinstance(value, bytes):
        return {"$b": base64.b64encode(value).decode()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if "$d" in value:
            return datetime.fromisoformat(value["$d"])
        if "$date" in value:
            return date.fromisoformat(value["$date"])
        if "$b" in value:
            return base64.b64decode(value["$b"])
    return value


def export_personal(session: Session, path: Path) -> dict:
    """Streams every included table (parents first) to `path`. Returns the manifest, which is also the file's first line."""
    classes = _classes()
    counts: dict[str, int] = {}
    digest = hashlib.sha256()
    tables = _ordered_tables()
    with gzip.open(path, "wt", encoding="utf-8") as out:
        def emit(obj: dict) -> None:
            line = json.dumps(obj, separators=(",", ":"))
            digest.update(line.encode())
            out.write(line + "\n")

        with tenant.use_owner(tenant.current_owner()):
            for name in tables:
                cls = classes[name]
                cols = [c.name for c in cls.__table__.columns if c.name != "owner_id"]
                counts[name] = 0
                result = session.execute(select(cls).execution_options(yield_per=500))
                for (row,) in result:
                    emit({"t": name, "r": {c: _encode(getattr(row, c)) for c in cols}})
                    counts[name] += 1
        manifest = {"catch_export": FORMAT, "tables": tables, "counts": counts, "excluded": EXCLUDED_TABLES, "sha256": digest.hexdigest()}
        out.write(json.dumps({"manifest": manifest}) + "\n")
    return manifest


def _read(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def _remap_embedded(text_value: str | None, keys: dict[str, str], maps: dict[str, dict[int, int]]) -> str | None:
    if not text_value:
        return text_value

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k in keys and isinstance(v, int):
                    out[k] = maps.get(keys[k], {}).get(v)  # an id that wasn't carried over becomes null, never a stranger's row
                else:
                    out[k] = walk(v)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    try:
        return json.dumps(walk(json.loads(text_value)))
    except ValueError:
        return text_value


def verify(path: Path) -> dict:
    """Re-reads the file and checks its checksum and counts against the manifest."""
    digest, counts, manifest = hashlib.sha256(), {}, None
    for item in _read(path):
        if "manifest" in item:
            manifest = item["manifest"]
            continue
        if "t" not in item or "r" not in item:
            raise ImportRefused("not a Catch export")
        digest.update(json.dumps(item, separators=(",", ":")).encode())
        counts[item["t"]] = counts.get(item["t"], 0) + 1
    if manifest is None or manifest.get("catch_export") != FORMAT:
        raise ImportRefused("not a Catch export (or a newer format)")
    if manifest["sha256"] != digest.hexdigest() or {k: v for k, v in manifest["counts"].items() if v} != counts:
        raise ImportRefused("the export file is damaged or was edited")
    return manifest


def import_into_account(session: Session, path: Path, *, owner_id: str, dry_run: bool = False) -> dict:
    """Imports as `owner_id`. Refuses a non-empty account: this is a one-time move, not a merge."""
    manifest = verify(path)
    classes = _classes()
    report: dict[str, Any] = {"owner": owner_id, "dry_run": dry_run, "imported": {}, "skipped_global": {}}
    with tenant.use_owner(owner_id):
        if session.execute(select(Activity.id).limit(1)).first() or session.execute(select(DailyWellness.date).limit(1)).first():
            raise ImportRefused("this account already has data; import only into a new, empty account")
        maps: dict[str, dict[int, int]] = {}
        refs: dict[str, list[tuple[str, str]]] = {}
        for child, col, parent in tenant_hooks.reference_columns():
            refs.setdefault(child, []).append((col, parent))
        deferred: list[tuple[type, int, str, int]] = []
        current: str | None = None
        for item in _read(path):
            if "manifest" in item:
                continue
            name, raw = item["t"], {k: _decode(v) for k, v in item["r"].items()}
            cls = classes[name]
            if name != current:
                if current is not None and not dry_run:
                    session.flush()
                current = name
                maps.setdefault(name, {})
            old_id = raw.get("id")
            # Reference data that exists globally in the public database: map by its stable external id.
            if (name == "exercises" and not raw.get("custom")) or (name == "workout_templates" and raw.get("is_example")):
                target = session.execute(
                    select(cls).where(cls.external_id == raw.get("external_id"), cls.owner_id.is_(None)).limit(1)
                ).scalars().first()
                if target is not None and old_id is not None:
                    maps[name][old_id] = target.id
                report["skipped_global"][name] = report["skipped_global"].get(name, 0) + 1
                continue
            values = dict(raw)
            values.pop("id", None)
            for col, parent in refs.get(name, []):
                value = values.get(col)
                if value is None:
                    continue
                if (name, col) in DEFERRED:
                    deferred.append((cls, old_id, col, value))
                    values[col] = None
                else:
                    values[col] = maps.get(parent, {}).get(value)  # None if that parent wasn't carried over
            if name in EMBEDDED_IDS:
                field, keys = EMBEDDED_IDS[name]
                values[field] = _remap_embedded(values.get(field), keys, maps)
            if name == "events":
                values.setdefault("plan_json", None)
            obj = cls(**values)
            report["imported"][name] = report["imported"].get(name, 0) + 1
            if dry_run:
                continue
            session.add(obj)
            if old_id is not None:
                session.flush()
                maps[name][old_id] = obj.id
        if not dry_run:
            session.flush()
            for cls, old_id, col, old_value in deferred:
                parent = dict((c, p) for c, p in refs.get(cls.__tablename__, [])).get(col)
                new_self, new_value = maps[cls.__tablename__].get(old_id), maps.get(parent, {}).get(old_value)
                if new_self is not None and new_value is not None:
                    session.get(cls, new_self).__setattr__(col, new_value)
            session.commit()
        else:
            session.rollback()
    report["manifest_counts"] = manifest["counts"]
    return report


__all__ = ["EXCLUDED_TABLES", "ImportRefused", "export_personal", "import_into_account", "verify"]

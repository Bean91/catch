"""The deleted-account tombstone (global table, reached only through leaderboard_store.store(), like the other global
tables). Nothing here touches an owned table."""

from __future__ import annotations

from sqlmodel import select

from catch.core.models import DeletedAccount
from catch.sync.leaderboard_store import store


def is_deleted(user_id: str) -> bool:
    with store() as s:
        return s.exec(select(DeletedAccount).where(DeletedAccount.user_id == user_id)).first() is not None


def mark_deleted(user_id: str) -> None:
    with store() as s:
        if s.get(DeletedAccount, user_id) is None:
            s.add(DeletedAccount(user_id=user_id))
            s.commit()


def unmark_deleted(user_id: str) -> None:
    with store() as s:
        row = s.get(DeletedAccount, user_id)
        if row is not None:
            s.delete(row)
            s.commit()

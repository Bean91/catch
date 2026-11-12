"""Session 24 (docs/public-architecture.md §7): the Postgres engine for the public deployment.

Imported only when CATCH_DEPLOYMENT=public (psycopg is in the optional `public` extra; the Pi never
installs it). Everything per-request about the connection is `SET LOCAL`/`set_config(.., true)` inside a
transaction (see tenant_hooks._after_begin), so it is safe behind Supabase's transaction pooler too."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def normalize_url(url: str) -> str:
    """psycopg3 driver, and `sslmode=require` unless the URL already chose one or the host is local.
    Drivers default to `prefer`, which silently falls back to plaintext (Supabase docs)."""
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    parts = urlsplit(url)
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+psycopg"
    query = dict(parse_qsl(parts.query))
    if "sslmode" not in query and (parts.hostname or "") not in _LOCAL_HOSTS:
        query["sslmode"] = "require"
    return urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def build_pg_engine(url: str, *, pool_mode: str = "session", pool_size: int = 1, rls: bool = True) -> Engine:
    connect_args: dict = {}
    kwargs: dict = {"pool_pre_ping": True}
    if pool_mode == "transaction":
        # Supavisor transaction mode (6543): no prepared statements, and the pooler already pools.
        connect_args["prepare_threshold"] = None
        kwargs["poolclass"] = NullPool
    else:
        kwargs.update(pool_size=max(1, pool_size), max_overflow=2, pool_recycle=300)
    engine = create_engine(normalize_url(url), connect_args=connect_args, **kwargs)
    engine.catch_rls = rls  # read by tenant_hooks._after_begin
    return engine


def role_report(engine: Engine) -> dict:
    """What the connected role can do — used by the startup guard and `catch db check`."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT current_user::text AS role, r.rolsuper, r.rolbypassrls, "
                "current_setting('server_version') AS version, "
                "(SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()) AS ssl "
                "FROM pg_roles r WHERE r.rolname = current_user"
            )
        ).one()
        conn.rollback()
    return {"role": row.role, "superuser": row.rolsuper, "bypass_rls": row.rolbypassrls, "version": row.version, "ssl": row.ssl}


def assert_unprivileged(engine: Engine) -> dict:
    """Refuse to serve if the runtime role would bypass RLS: then RLS protects nothing and the claim that
    it does would be false (docs/public-architecture.md §6)."""
    report = role_report(engine)
    if report["superuser"] or report["bypass_rls"]:
        raise RuntimeError(
            f"DATABASE_URL connects as '{report['role']}', which bypasses row level security. "
            "Use the dedicated catch_api role (see docs/public-setup.md)."
        )
    return report


def rls_probe(engine: Engine) -> dict:
    """Proves — on the real connection path — that the runtime role, once it takes a user's identity, sees only
    that user: a stranger's id sees no profiles, and cannot write a profile for anyone else. Everything is rolled
    back."""
    import json
    import uuid

    stranger = str(uuid.uuid4())
    out = {"sees_nothing_as_stranger": False, "cannot_write_for_another_user": False}
    with engine.connect() as conn:
        conn.exec_driver_sql("SET LOCAL ROLE authenticated")
        conn.exec_driver_sql(
            "SELECT set_config('request.jwt.claims', %s, true), set_config('request.jwt.claim.sub', %s, true),"
            " set_config('search_path', 'catch, public', true)",
            (json.dumps({"sub": stranger, "role": "authenticated"}), stranger),
        )
        out["sees_nothing_as_stranger"] = conn.exec_driver_sql("SELECT count(*) FROM user_profiles").scalar() == 0
        conn.exec_driver_sql("SAVEPOINT p")
        try:
            conn.exec_driver_sql("INSERT INTO user_profiles (id, created_at) VALUES (%s, now())", (str(uuid.uuid4()),))
        except Exception:  # noqa: BLE001 — the policy's WITH CHECK refusing the row is the expected outcome
            out["cannot_write_for_another_user"] = True
        conn.rollback()
    return out

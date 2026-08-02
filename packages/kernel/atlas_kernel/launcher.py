"""Entry point for the packaged kernel binary.

A developer runs ``uvicorn atlas_kernel.api:app`` against a database they
created themselves. An installed Atlas has neither a shell nor a DBA, so this
launcher does the two things that would otherwise be manual:

1. Waits for the bundled PostgreSQL to accept connections.
2. Creates the Atlas database if it does not exist.

Then it starts the same ASGI app the developer runs. Nothing here changes
kernel behaviour -- it is the missing setup a human would otherwise perform.

Built into a standalone binary by ``infra/packaging/atlas-kernel.spec`` and
launched by the Tauri shell as a sidecar.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

#: How long to wait for PostgreSQL to come up before giving up. The bundled
#: server usually accepts connections in well under a second; a cold first
#: start after initdb is the slow case.
DEFAULT_DB_TIMEOUT_SECONDS = 60.0

#: PostgreSQL always has this database, so it is where we connect to ask
#: whether the real one exists yet.
MAINTENANCE_DATABASE = "postgres"


def _split_database_url(url: str) -> tuple[str, str]:
    """Return (maintenance_url, database_name) for a SQLAlchemy-style URL."""
    parsed = urlparse(url)
    database = parsed.path.lstrip("/")
    if not database:
        raise ValueError(f"database URL has no database name: {url!r}")
    maintenance = urlunparse(parsed._replace(path=f"/{MAINTENANCE_DATABASE}"))
    return maintenance, database


def _psycopg_dsn(url: str) -> str:
    """Strip the SQLAlchemy driver prefix; psycopg wants a plain DSN."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def wait_for_postgres(url: str, timeout: float = DEFAULT_DB_TIMEOUT_SECONDS) -> None:
    """Block until PostgreSQL answers, or raise TimeoutError.

    Retries a *connection*, not a port check: an open port on a server still
    running crash recovery is not a database that can be used yet.
    """
    import psycopg

    maintenance, _ = _split_database_url(url)
    dsn = _psycopg_dsn(maintenance)
    deadline = time.monotonic() + timeout
    last: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=3):
                return
        except Exception as exc:  # noqa: BLE001 - any failure means "not ready yet"
            last = exc
            time.sleep(0.25)

    raise TimeoutError(f"PostgreSQL did not accept connections within {timeout:.0f}s: {last}")


def ensure_database(url: str) -> bool:
    """Create the Atlas database if absent. Returns True if it was created.

    Idempotent: an existing database is left untouched, so this runs on every
    start rather than only on first run.
    """
    import psycopg
    from psycopg import sql

    maintenance, database = _split_database_url(url)

    with psycopg.connect(_psycopg_dsn(maintenance), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (database,)
        ).fetchone()
        if exists:
            return False
        # CREATE DATABASE cannot run inside a transaction and cannot be
        # parameterised, so the name is quoted as an identifier instead.
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
        return True


def prepare(url: str, timeout: float = DEFAULT_DB_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Do everything needed before the ASGI app can be imported."""
    started = time.monotonic()
    wait_for_postgres(url, timeout=timeout)
    created = ensure_database(url)
    return {
        "database_ready": True,
        "database_created": created,
        "waited_seconds": round(time.monotonic() - started, 2),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="atlas-kernel", description="Run the Atlas kernel.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--db-timeout",
        type=float,
        default=DEFAULT_DB_TIMEOUT_SECONDS,
        help="Seconds to wait for PostgreSQL before giving up.",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="Wait for the database and create it, then exit without serving.",
    )
    args = parser.parse_args(argv)

    url = os.environ.get("ATLAS_DATABASE_URL")
    if not url:
        print("ATLAS_DATABASE_URL is not set", file=sys.stderr)
        return 2

    try:
        result = prepare(url, timeout=args.db_timeout)
    except Exception as exc:  # noqa: BLE001 - the shell shows this to a human
        print(f"database not ready: {exc}", file=sys.stderr)
        return 1

    # Printed on stdout so the desktop shell can show real progress instead of
    # an indeterminate spinner.
    print(
        f"database ready in {result['waited_seconds']}s"
        + (" (created)" if result["database_created"] else ""),
        flush=True,
    )

    if args.prepare_only:
        return 0

    import uvicorn

    # Imported here, after the database exists: importing the API builds the
    # composition root, which runs init_db() against a live connection.
    uvicorn.run("atlas_kernel.api:app", host=args.host, port=args.port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

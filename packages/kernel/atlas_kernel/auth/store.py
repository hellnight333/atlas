"""Where users and sessions live.

PostgreSQL, alongside everything else that has to survive a restart. A control
plane whose accounts vanish on reboot is one that locks its operator out at the
worst moment, and one whose sessions live in memory logs everybody out whenever
the API restarts — which, with `Restart=on-failure`, is exactly when they most
need to look.

Tables are created here rather than in `db.init_db` so that the whole of
authentication is one importable unit. It uses the same engine, so it takes part
in the same connection pool and the same database.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text

from ..db import engine
from .models import (
    AuthError,
    NotAuthenticated,
    Scope,
    Session,
    User,
    hash_password,
    hash_token,
    new_token,
)

log = logging.getLogger(__name__)

SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS qevik_users (
        id TEXT PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        scopes TEXT NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        disabled BOOLEAN NOT NULL DEFAULT FALSE,
        tenant_id TEXT NOT NULL DEFAULT ''
    )
    """,
    # Added for the customer surface. Defaults to empty, which means "no tenant
    # established" — the customer routes refuse on that rather than guessing,
    # so an existing operator account keeps working on the internal surfaces
    # and reaches none of the customer ones.
    "ALTER TABLE qevik_users ADD COLUMN IF NOT EXISTS tenant_id TEXT NOT NULL DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS qevik_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES qevik_users(id) ON DELETE CASCADE,
        token_hash TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        revoked BOOLEAN NOT NULL DEFAULT FALSE,
        user_agent TEXT NOT NULL DEFAULT ''
    )
    """,
    # Every request looks a session up by token hash. Without this it is a
    # sequential scan on the hot path of every authenticated call.
    "CREATE INDEX IF NOT EXISTS qevik_sessions_token ON qevik_sessions (token_hash)",
)


#: Statements only PostgreSQL understands. `ADD COLUMN IF NOT EXISTS` is a
#: Postgres extension, and it is the single thing that stopped the whole auth
#: stack from running on sqlite — which is what a local acceptance run, a
#: developer machine and a throwaway environment all want to use.
#:
#: Skipped rather than rewritten for every dialect: on a fresh sqlite database
#: `CREATE TABLE` above already includes the column, so the migration has
#: nothing to do. It matters only for a Postgres database created before the
#: column existed.
_POSTGRES_ONLY = ("ADD COLUMN IF NOT EXISTS",)


def init_auth() -> None:
    postgres = engine.dialect.name.startswith("postgres")
    with engine.begin() as conn:
        for statement in SCHEMA:
            if not postgres and any(m in statement for m in _POSTGRES_ONLY):
                continue
            conn.execute(text(statement))


def _moment(value: object) -> datetime:
    """A timestamp from any driver, as an aware datetime.

    Postgres returns a `datetime`; sqlite has no timestamp type and returns the
    string it stored. Handling both is what lets the whole auth stack run on a
    throwaway sqlite file for a local run or an acceptance test, rather than
    requiring a Postgres wherever anybody wants to sign in.
    """
    moment = datetime.fromisoformat(value) if isinstance(value, str) else value
    assert isinstance(moment, datetime)
    return moment.replace(tzinfo=moment.tzinfo or UTC)


def _to_user(row) -> User:
    return User(
        id=row.id,
        username=row.username,
        password_hash=row.password_hash,
        tenant_id=getattr(row, "tenant_id", "") or "",
        scopes=frozenset(Scope(s) for s in row.scopes.split(",") if s),
        created_at=_moment(row.created_at),
        disabled=row.disabled,
    )


class AuthStore:
    """Users and sessions. The only place a password verifier is written."""

    def create_user(
        self, username: str, password: str, scopes: frozenset[Scope] | None = None,
        tenant_id: str = "",
    ) -> User:
        username = username.strip().lower()
        if not username:
            raise AuthError("a username is required")
        user = User(
            username=username,
            password_hash=hash_password(password),
            tenant_id=tenant_id.strip(),
            scopes=scopes if scopes is not None else User.model_fields["scopes"].default,
        )
        with engine.begin() as conn:
            existing = conn.execute(
                text("SELECT id FROM qevik_users WHERE username = :u"), {"u": username}
            ).first()
            if existing:
                raise AuthError(f"user {username!r} already exists")
            conn.execute(
                text(
                    "INSERT INTO qevik_users (id, username, password_hash, scopes,"
                    " created_at, disabled, tenant_id)"
                    " VALUES (:id, :u, :p, :s, :c, :d, :t)"
                ),
                {
                    "id": user.id,
                    "u": user.username,
                    "p": user.password_hash,
                    "s": ",".join(sorted(str(s) for s in user.scopes)),
                    "c": user.created_at,
                    "d": user.disabled,
                    "t": user.tenant_id,
                },
            )
        return user

    def set_password(self, username: str, password: str) -> int:
        """Replace a user's password and end every session they hold.

        The revocation is not a courtesy. A rotation exists because the old
        secret may be known to someone else, and a live session token is that
        secret already spent — leaving sessions standing would rotate the front
        door while the person inside stays inside.

        Returns the number of sessions ended, so a caller can report what the
        rotation actually did rather than assume it did anything.
        """
        username = username.strip().lower()
        with engine.begin() as conn:
            row = conn.execute(
                text("SELECT id FROM qevik_users WHERE username = :u"), {"u": username}
            ).first()
            if not row:
                raise AuthError(f"no user {username!r}")
            conn.execute(
                text("UPDATE qevik_users SET password_hash = :p WHERE username = :u"),
                {"p": hash_password(password), "u": username},
            )
        return self.revoke_all(row[0])

    def get_user(self, username: str) -> User | None:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM qevik_users WHERE username = :u"),
                {"u": username.strip().lower()},
            ).first()
        return _to_user(row) if row else None

    def get_user_by_id(self, user_id: str) -> User | None:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM qevik_users WHERE id = :i"), {"i": user_id}
            ).first()
        return _to_user(row) if row else None

    def list_users(self) -> list[User]:
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT * FROM qevik_users ORDER BY created_at")).all()
        return [_to_user(r) for r in rows]

    def set_tenant(self, username: str, tenant_id: str) -> User:
        """Attach a user to the tenant they act for.

        Separate from `set_scopes` because they answer different questions —
        what someone may do, and whose data they may do it to. Granting a scope
        must never move somebody between tenants as a side effect.
        """
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE qevik_users SET tenant_id = :t WHERE username = :u"),
                {"t": tenant_id.strip(), "u": username.strip().lower()},
            )
        found = self.get_user(username)
        if found is None:
            raise AuthError(f"no user {username!r}")
        return found

    def set_scopes(self, username: str, scopes: frozenset[Scope]) -> User:
        """Grant or revoke. Reachable only from an ADMIN-scoped caller, which is
        what keeps automation from widening its own access."""
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE qevik_users SET scopes = :s WHERE username = :u"),
                {"s": ",".join(sorted(str(s) for s in scopes)), "u": username.strip().lower()},
            )
        user = self.get_user(username)
        if user is None:
            raise AuthError(f"no user {username!r}")
        return user

    # -- sessions ---------------------------------------------------------

    def login(self, username: str, password: str, *, user_agent: str = "") -> tuple[str, User]:
        """Verify a password and open a session.

        The same error for an unknown user and a wrong password, and the
        verification runs either way: answering faster for a missing account
        tells an attacker which usernames exist.
        """
        from .models import verify_password

        user = self.get_user(username)
        stored = user.password_hash if user else hash_password("x" * 16)
        ok = verify_password(password, stored)
        if not user or not ok or user.disabled:
            raise NotAuthenticated("incorrect username or password")

        token, token_hash = new_token()
        session = Session(user_id=user.id, token_hash=token_hash, user_agent=user_agent[:200])
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO qevik_sessions (id, user_id, token_hash, created_at,"
                    " expires_at, revoked, user_agent)"
                    " VALUES (:id, :u, :t, :c, :e, FALSE, :a)"
                ),
                {
                    "id": session.id,
                    "u": session.user_id,
                    "t": session.token_hash,
                    "c": session.created_at,
                    "e": session.expires_at,
                    "a": session.user_agent,
                },
            )
        return token, user

    def authenticate(self, token: str) -> User:
        """Resolve a token to a user, or refuse.

        Expiry is enforced here rather than by a sweeper, so a session cannot be
        usable merely because nothing has cleaned it up yet.
        """
        if not token or not token.strip():
            raise NotAuthenticated("no session token")
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM qevik_sessions WHERE token_hash = :t"),
                {"t": hash_token(token.strip())},
            ).first()
        if row is None or row.revoked:
            raise NotAuthenticated("session not found or revoked")
        # `_moment` rather than `.tzinfo` directly: sqlite has no timestamp
        # type and hands back the string it stored, and this is the hot path of
        # every authenticated request.
        expires = _moment(row.expires_at)
        if datetime.now(UTC) >= expires:
            raise NotAuthenticated("session expired")
        user = self.get_user_by_id(row.user_id)
        if user is None or user.disabled:
            raise NotAuthenticated("account unavailable")
        return user

    def logout(self, token: str) -> None:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE qevik_sessions SET revoked = TRUE WHERE token_hash = :t"),
                {"t": hash_token(token.strip())},
            )

    def revoke_all(self, user_id: str) -> int:
        """Every session for one user. What you reach for when a laptop is lost."""
        with engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE qevik_sessions SET revoked = TRUE"
                    " WHERE user_id = :u AND revoked = FALSE"
                ),
                {"u": user_id},
            )
        return result.rowcount or 0

    def delete_user(self, username: str, *, requested_by: str = "") -> dict:
        """Remove a user and everything that authenticates them. Irreversible.

        The only destructive operation in this module, and deliberately the
        narrowest one that does the job: it takes a username, it removes that
        row, and the sessions table drops its rows through the foreign key's
        ON DELETE CASCADE. There is no bulk form and no filter argument,
        because a delete that can take a predicate is a delete that eventually
        takes the wrong one.

        Two refusals, both about not locking anybody out of their own system:
        the last account holding ADMIN cannot be removed, and neither can the
        account making the request.

        Returns what was removed, so the caller can record it. Raises AuthError
        if there is no such user — deleting nothing must not look like success.
        """
        username = username.strip().lower()
        user = self.get_user(username)
        if user is None:
            raise AuthError(f"no user {username!r}")
        if requested_by and requested_by.strip().lower() == username:
            raise AuthError("an account cannot delete itself")
        if user.has(Scope.ADMIN):
            remaining = [
                other for other in self.list_users()
                if other.id != user.id and other.has(Scope.ADMIN) and not other.disabled
            ]
            if not remaining:
                raise AuthError("refusing to delete the last administrator")

        with engine.begin() as conn:
            sessions = conn.execute(
                text("SELECT COUNT(*) FROM qevik_sessions WHERE user_id = :u"),
                {"u": user.id},
            ).scalar() or 0
            deleted = conn.execute(
                text("DELETE FROM qevik_users WHERE id = :i"), {"i": user.id}
            ).rowcount or 0
            left = conn.execute(
                text("SELECT COUNT(*) FROM qevik_sessions WHERE user_id = :u"),
                {"u": user.id},
            ).scalar() or 0
        if left:
            raise AuthError(f"{left} session(s) survived the cascade for {username!r}")
        # Recorded here rather than in the HTTP route, so the trail does not
        # depend on which caller happened to perform the deletion. There is no
        # audit table in this module and adding one to log a single event would
        # be a worse trade than a structured line the host already retains.
        log.warning(
            "auth: account deleted — username=%s id=%s scopes=%s created=%s "
            "sessions_removed=%s requested_by=%s",
            user.username, user.id, ",".join(sorted(str(x) for x in user.scopes)) or "none",
            user.created_at.isoformat(), sessions, requested_by or "unattributed",
        )
        return {"user_id": user.id, "username": user.username,
                "scopes": sorted(str(scope) for scope in user.scopes),
                "created_at": user.created_at.isoformat(),
                "sessions_removed": sessions, "rows_removed": deleted}

    def active_sessions(self, user_id: str) -> int:
        with engine.connect() as conn:
            return (
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM qevik_sessions WHERE user_id = :u"
                        " AND revoked = FALSE AND expires_at > NOW()"
                    ),
                    {"u": user_id},
                ).scalar()
                or 0
            )


def bootstrap_admin(store: AuthStore | None = None) -> User | None:
    """Create the first administrator from the environment, once.

    Returns None when no password is configured or an admin already exists.
    Creating one with a generated password would mean a control plane with a
    credential nobody chose and everybody could look up.
    """
    from .models import bootstrap_password

    store = store or AuthStore()
    password = bootstrap_password()
    if not password:
        return None
    if store.get_user("admin"):
        return None
    return store.create_user("admin", password, scopes=frozenset(Scope))

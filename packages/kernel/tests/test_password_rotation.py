"""Rotating a password must also end the sessions the old one bought.

A rotation happens because the old secret may be known to someone else. A live
session token *is* that secret already spent — so changing the password while
leaving sessions standing rotates the front door while whoever is inside stays
inside. That is the property worth a database-backed test rather than a mocked
one: it is about what the tables actually contain afterwards.
"""

from __future__ import annotations

import secrets

import pytest

from atlas_kernel.auth.models import AuthError, Scope
from atlas_kernel.auth.store import AuthStore, init_auth

# Without this the conftest replaces AuthStore.authenticate with a stub that
# returns an operator for any token — sensible for the hundreds of tests that
# merely need to be past the door, and fatal here, where the entire question is
# whether a revoked token still opens it. The first run of this file passed the
# revocation check against the stub and reported "DID NOT RAISE".
pytestmark = pytest.mark.real_auth


@pytest.fixture
def store() -> AuthStore:
    init_auth()
    return AuthStore()


@pytest.fixture
def user(store: AuthStore):
    """A throwaway account, so this never touches the real admin."""
    name = f"rotation-test-{secrets.token_hex(6)}"
    created = store.create_user(name, "first-password-9x", scopes=frozenset({Scope.READ}))
    yield created
    with __import__("atlas_kernel.auth.store", fromlist=["engine"]).engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("DELETE FROM qevik_users WHERE id = :i"), {"i": created.id})


def test_the_new_password_works_and_the_old_one_does_not(store: AuthStore, user) -> None:
    store.set_password(user.username, "second-password-7y")

    token, _ = store.login(user.username, "second-password-7y")
    assert token

    with pytest.raises(AuthError):
        store.login(user.username, "first-password-9x")


def test_every_live_session_is_revoked(store: AuthStore, user) -> None:
    """Three logins, then a rotation. All three must stop authenticating."""
    tokens = [store.login(user.username, "first-password-9x")[0] for _ in range(3)]
    assert store.active_sessions(user.id) == 3
    for token in tokens:
        assert store.authenticate(token)

    ended = store.set_password(user.username, "second-password-7y")

    assert ended == 3, "the rotation must report what it actually revoked"
    assert store.active_sessions(user.id) == 0
    for token in tokens:
        with pytest.raises(AuthError):
            store.authenticate(token)


def test_rotating_an_unknown_user_is_an_error_not_a_silent_no_op(store: AuthStore) -> None:
    """A typo must fail loudly.

    Silently doing nothing would let an operator believe a credential was
    rotated when it was not — the worst possible outcome for this operation,
    because it ends with someone confident about a password still in the wild.
    """
    with pytest.raises(AuthError, match="no user"):
        store.set_password("nobody-by-this-name", "irrelevant")


def test_scopes_survive_a_rotation(store: AuthStore, user) -> None:
    """Changing a password must not quietly change what the account can do."""
    store.set_password(user.username, "second-password-7y")
    after = store.get_user(user.username)
    assert after is not None
    assert after.scopes == frozenset({Scope.READ})

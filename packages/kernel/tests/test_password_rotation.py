"""Rotating a password must also end the sessions the old one bought.

A rotation happens because the old secret may be known to someone else. A live
session token *is* that secret already spent — so changing the password while
leaving sessions standing rotates the front door while whoever is inside stays
inside. That is the property worth a database-backed test rather than a mocked
one: it is about what the tables actually contain afterwards.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime

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


def test_redrafting_replaces_rather_than_accumulates(store: AuthStore) -> None:
    """Re-running the drafter must not add another copy each time.

    It did: every run left five more rows, so "how many messages are waiting"
    grew by five whenever the copy was edited. The delete is scoped to rows that
    are still a draft *and* carry no approval, no fingerprint and no send time —
    three independent signals, because a status column is one edit away from
    lying and what it guards cannot be rebuilt.
    """
    import secrets

    from atlas_kernel.opportunity.models import Business, OutreachMessage, OutreachStatus
    from atlas_kernel.opportunity.repository import OpportunityRepository

    repo = OpportunityRepository()
    business = repo.save_business(
        Business(name=f"Redraft Test {secrets.token_hex(4)}", geography="Dubai")
    )

    def draft() -> None:
        repo.delete_unsent_drafts(business.id, channels=("whatsapp", "email"))
        for channel in ("whatsapp", "email"):
            repo.save_message(
                OutreachMessage(
                    proposal_id="",
                    business_id=business.id,
                    channel=channel,
                    recipient="",
                    subject="",
                    body="v1",
                    status=OutreachStatus.DRAFT,
                )
            )

    def count() -> int:
        from sqlalchemy import text

        from atlas_kernel.db import engine

        with engine.connect() as conn:
            return conn.execute(
                text("SELECT count(*) FROM atlas_outreach_messages WHERE business_id = :b"),
                {"b": business.id},
            ).scalar()

    for _ in range(4):
        draft()
    assert count() == 2, "re-drafting accumulated instead of replacing"

    # A sent message is history and must survive the next drafting run.
    repo.save_message(
        OutreachMessage(
            proposal_id="",
            business_id=business.id,
            channel="whatsapp",
            recipient="0501234567",
            subject="",
            body="actually sent",
            status=OutreachStatus.SENT,
            sent_at=datetime.now(UTC),
        )
    )
    draft()
    assert count() == 3, "re-drafting deleted a sent message"

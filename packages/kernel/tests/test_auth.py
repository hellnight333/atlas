"""Authentication and authorisation for a control plane that can spend money.

The property most of these defend is that **scopes come from the user record and
never from the request**. That is what makes "a model must never grant itself
permission" structural: a plan, a prompt-injected page and a compromised client
are all just requests, and none of them can widen a scope.
"""

from __future__ import annotations

import pytest

from atlas_kernel.auth import (
    ALWAYS_APPROVED,
    DEFAULT_SCOPES,
    AuthError,
    NotAuthorised,
    Scope,
    Session,
    User,
    hash_password,
    verify_password,
)
from atlas_kernel.auth.models import MIN_PASSWORD_LENGTH, hash_token, new_token

GOOD = "a-sufficiently-long-password"


def _user(**kwargs) -> User:
    return User(username="op", password_hash=hash_password(GOOD), **kwargs)


class TestPasswords:
    def test_a_password_round_trips(self) -> None:
        assert verify_password(GOOD, hash_password(GOOD))

    def test_a_wrong_password_is_rejected(self) -> None:
        assert not verify_password("not-the-password-x", hash_password(GOOD))

    def test_the_password_is_never_in_the_verifier(self) -> None:
        assert GOOD not in hash_password(GOOD)

    def test_two_hashes_of_the_same_password_differ(self) -> None:
        """Salted. Identical verifiers would reveal which accounts share a
        password, and make one cracked hash crack several accounts."""
        assert hash_password(GOOD) != hash_password(GOOD)

    def test_a_short_password_is_refused_with_the_reason(self) -> None:
        with pytest.raises(AuthError, match="deploy websites and send email"):
            hash_password("x" * (MIN_PASSWORD_LENGTH - 1))

    def test_a_malformed_verifier_fails_closed(self) -> None:
        """A truncated or foreign-format row must not authenticate anybody."""
        for stored in ("", "nonsense", "scrypt$notahex$alsonot", "bcrypt$x$y"):
            assert not verify_password(GOOD, stored)


class TestTokens:
    def test_only_the_hash_would_be_stored(self) -> None:
        """A stolen store must not be a stolen set of live sessions."""
        token, stored = new_token()
        assert token != stored
        assert stored == hash_token(token)

    def test_tokens_are_unguessable_and_unique(self) -> None:
        tokens = {new_token()[0] for _ in range(50)}
        assert len(tokens) == 50
        assert all(len(t) >= 32 for t in tokens)


class TestScopes:
    def test_the_default_cannot_publish(self) -> None:
        """The safe default for an account that can reach the internet on your
        behalf is that it cannot."""
        assert Scope.PUBLISH not in DEFAULT_SCOPES
        assert DEFAULT_SCOPES == frozenset({Scope.READ, Scope.EXECUTE})

    def test_a_missing_scope_is_refused_and_says_where_scopes_come_from(self) -> None:
        with pytest.raises(NotAuthorised, match="granted by an administrator, never requested"):
            _user(scopes=frozenset({Scope.READ})).require(Scope.PUBLISH)

    def test_admin_implies_everything(self) -> None:
        admin = _user(scopes=frozenset({Scope.ADMIN}))
        for scope in Scope:
            admin.require(scope)

    def test_a_disabled_account_holds_nothing(self) -> None:
        with pytest.raises(NotAuthorised, match="disabled"):
            _user(scopes=frozenset({Scope.ADMIN}), disabled=True).require(Scope.READ)

    def test_the_dangerous_scopes_still_need_per_action_approval(self) -> None:
        """A scope is a standing grant; an approval is a decision about one
        specific thing. Collapsing them is how an autonomous system ends up
        publishing on its own authority."""
        assert ALWAYS_APPROVED == {
            Scope.PUBLISH,
            Scope.COMMUNICATE,
            Scope.FINANCIAL,
            Scope.DESTRUCTIVE,
        }

    def test_destructive_is_separate_from_publish(self) -> None:
        """Undoing a publication and destroying the thing published are
        different mistakes."""
        publisher = _user(scopes=frozenset({Scope.PUBLISH}))
        publisher.require(Scope.PUBLISH)
        with pytest.raises(NotAuthorised):
            publisher.require(Scope.DESTRUCTIVE)


class TestNothingLeaksTheVerifier:
    def test_the_redacted_view_has_no_password_hash(self) -> None:
        redacted = _user().redacted()
        assert "password_hash" not in redacted
        assert "scrypt" not in str(redacted)

    def test_scopes_are_readable_in_the_redacted_view(self) -> None:
        assert _user(scopes=frozenset({Scope.READ})).redacted()["scopes"] == ["read"]


class TestSessions:
    def test_a_fresh_session_is_alive(self) -> None:
        assert Session(user_id="u", token_hash="h").alive

    def test_a_revoked_session_is_not(self) -> None:
        assert not Session(user_id="u", token_hash="h", revoked=True).alive

    def test_an_expired_session_is_not(self) -> None:
        from datetime import UTC, datetime, timedelta

        expired = Session(
            user_id="u",
            token_hash="h",
            expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        assert not expired.alive


class TestTheRequestCannotWidenItsOwnScope:
    def test_scopes_are_not_a_field_a_caller_can_send(self) -> None:
        """The endpoint models carry an objective and a publish flag — never a
        scope. Authorisation is read from the authenticated user, so there is no
        field for a caller to lie in."""
        from atlas_kernel.control.api import ObjectiveRequest

        assert "scopes" not in ObjectiveRequest.model_fields
        assert set(ObjectiveRequest.model_fields) == {"objective", "authorise_publish", "slug"}

    def test_asking_to_publish_is_a_request_not_a_grant(self) -> None:
        """authorise_publish only expresses intent. The scope check still runs
        against the user, so setting it true without the scope changes nothing.
        """
        from atlas_kernel.control.api import ObjectiveRequest

        asked = ObjectiveRequest(objective="publish everything now please", authorise_publish=True)
        assert asked.authorise_publish is True
        with pytest.raises(NotAuthorised):
            _user(scopes=frozenset({Scope.EXECUTE})).require(Scope.PUBLISH)


class TestTheApiIsClosedByDefault:
    def test_the_public_path_list_is_short_and_harmless(self) -> None:
        """Everything else requires a session. A new endpoint is protected the
        moment it exists, which is the point of allow-listing rather than
        decorating."""
        from atlas_kernel.auth.api import PUBLIC_PATHS

        # Pinned exactly, so adding an unauthenticated route is a conscious
        # decision rather than a side effect. `/api/public/audit` was added
        # deliberately in the P4 acquisition entry point: a visitor audits a
        # site before they have an account.
        assert PUBLIC_PATHS == {"/health", "/auth/login", "/openapi.json",
                                "/docs", "/redoc", "/api/public/audit"}
        assert not any(p.startswith("/control") for p in PUBLIC_PATHS)
        # Nothing tenant-scoped may be public, whatever else is added later.
        assert not any(p.startswith("/api/customer") for p in PUBLIC_PATHS)

    def test_the_console_paths_serve_a_page_and_never_an_api(self) -> None:
        """The console's routes are a second, separate allow-list.

        Kept apart from `PUBLIC_PATHS` so the pin above still means what it
        says. `/api/health` was briefly in this set and is deliberately not:
        it reports whether the vault is sealed and which components are absent,
        which is deployment posture and belongs behind a session. `/health`
        stays public and returns nothing but a status word.
        """
        from atlas_kernel.auth.api import CONSOLE_PATHS

        assert not any(p.startswith("/api") for p in CONSOLE_PATHS)
        assert not any(p.startswith("/control") for p in CONSOLE_PATHS)
        assert not any(p.startswith("/auth") for p in CONSOLE_PATHS)
        assert "/" in CONSOLE_PATHS, "the login form must be reachable"

    def test_the_one_public_api_route_returns_only_allow_listed_fields(self) -> None:
        """`/api/public/audit` is unauthenticated, so what it can return is
        bounded by an allow-list rather than by remembering to redact."""
        from atlas_kernel.customer.public import FORBIDDEN_HINTS, PUBLIC_FIELDS, Leak, guard

        for private in ("tenant_id", "business_id", "evidence", "recommendation_id"):
            assert private not in PUBLIC_FIELDS
            with pytest.raises(Leak):
                guard({private: "anything"})
        assert "tenant" in FORBIDDEN_HINTS

    def test_the_session_cookie_is_not_reachable_from_javascript(self) -> None:
        """Set httponly, so an injected script on any page cannot read it."""
        import inspect

        from atlas_kernel.auth import api

        source = inspect.getsource(api)
        assert "httponly=True" in source
        assert 'samesite="strict"' in source

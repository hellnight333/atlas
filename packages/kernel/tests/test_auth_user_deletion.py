"""Deleting an account: who may, what goes, and what must never go.

The only destructive operation in the auth module. It exists because a
temporary verification account had to be removed from production and there was
no way to remove one — `set_scopes` to nothing leaves an inert row that still
appears in every listing, which is not the same as gone.

The risks worth testing are not "does DELETE delete". They are: can a non-admin
reach it, can it be used to lock everybody out, and does it take sessions with
it or leave them orphaned.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas_kernel.auth import Scope, User
from atlas_kernel.auth.api import build_router, current_user
from atlas_kernel.auth.models import AuthError
from atlas_kernel.auth.store import AuthStore, init_auth


@pytest.fixture(scope="module")
def store() -> AuthStore:
    init_auth()
    return AuthStore()


def _name(label: str) -> str:
    """Unique per run — the test database persists between runs."""
    return f"deltest-{label}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def temp_user(store: AuthStore):
    created = []

    def make(scopes=frozenset({Scope.READ}), label="user"):
        username = _name(label)
        user = store.create_user(username, "correct-horse-battery-staple", scopes)
        created.append(username)
        return user

    yield make
    for username in created:
        try:
            store.delete_user(username)
        except AuthError:
            pass


# --- what it does ----------------------------------------------------------

def test_a_deleted_user_is_gone_from_the_listing(store, temp_user) -> None:
    user = temp_user()
    assert store.get_user(user.username) is not None
    removed = store.delete_user(user.username)
    assert removed["user_id"] == user.id
    assert store.get_user(user.username) is None
    assert user.username not in [u.username for u in store.list_users()]


@pytest.mark.real_auth
def test_a_deleted_user_can_no_longer_authenticate(store, temp_user) -> None:
    """Marked real_auth on purpose: the suite normally patches `authenticate`
    to a fixed operator, and a deletion test running against that patch would
    prove nothing about whether the token still resolves."""
    user = temp_user()
    token, _ = store.login(user.username, "correct-horse-battery-staple")
    assert store.authenticate(token).username == user.username
    store.delete_user(user.username)
    with pytest.raises(Exception):
        store.authenticate(token)
    with pytest.raises(Exception):
        store.login(user.username, "correct-horse-battery-staple")


def test_the_sessions_go_with_the_user(store, temp_user) -> None:
    """The cascade is in the schema; this proves it actually fires."""
    from sqlalchemy import text

    from atlas_kernel.db import engine

    user = temp_user()
    store.login(user.username, "correct-horse-battery-staple")
    store.login(user.username, "correct-horse-battery-staple")
    with engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM qevik_sessions WHERE user_id = :u"),
                              {"u": user.id}).scalar()
    assert before >= 2
    removed = store.delete_user(user.username)
    assert removed["sessions_removed"] == before
    with engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM qevik_sessions WHERE user_id = :u"),
                             {"u": user.id}).scalar()
    assert after == 0, "sessions must not outlive the account that owns them"


def test_the_operation_records_itself_whoever_calls_it(store, temp_user, caplog) -> None:
    """The trail must not depend on the deletion having gone through the route.
    The account this was built for was removed by a direct store call."""
    user = temp_user()
    with caplog.at_level("WARNING"):
        store.delete_user(user.username, requested_by="an-operator")
    assert "account deleted" in caplog.text
    assert user.username in caplog.text and user.id in caplog.text
    assert "an-operator" in caplog.text


def test_deleting_nothing_is_an_error_not_a_success(store) -> None:
    with pytest.raises(AuthError, match="no user"):
        store.delete_user(_name("never-existed"))


def test_only_the_named_user_is_touched(store, temp_user) -> None:
    keep_a, keep_b = temp_user(label="keep-a"), temp_user(label="keep-b")
    doomed = temp_user(label="doomed")
    before = {u.username: (u.id, sorted(str(s) for s in u.scopes), u.disabled)
              for u in store.list_users() if u.id != doomed.id}
    store.delete_user(doomed.username)
    after = {u.username: (u.id, sorted(str(s) for s in u.scopes), u.disabled)
             for u in store.list_users()}
    assert before == after, "a deletion changed somebody else"
    assert store.get_user(keep_a.username) and store.get_user(keep_b.username)


# --- what it refuses -------------------------------------------------------

def test_the_last_administrator_cannot_be_removed(store, temp_user) -> None:
    """Otherwise the operation's first serious use is locking everyone out."""
    admins = [u for u in store.list_users() if u.has(Scope.ADMIN) and not u.disabled]
    if not admins:
        pytest.skip("no administrator in this database")
    if len(admins) == 1:
        with pytest.raises(AuthError, match="last administrator"):
            store.delete_user(admins[0].username)
    else:
        extra = temp_user(scopes=frozenset({Scope.ADMIN}), label="admin")
        store.delete_user(extra.username)      # not the last one, so allowed
        assert store.get_user(extra.username) is None


def test_an_account_cannot_delete_itself(store, temp_user) -> None:
    user = temp_user()
    with pytest.raises(AuthError, match="cannot delete itself"):
        store.delete_user(user.username, requested_by=user.username)
    assert store.get_user(user.username) is not None


# --- who may reach it ------------------------------------------------------

def _client(store, operator: User) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(store))
    app.dependency_overrides[current_user] = lambda: operator
    return TestClient(app, raise_server_exceptions=False)


def test_an_administrator_may_delete_over_http(store, temp_user) -> None:
    user = temp_user()
    admin = User(id="a", username="an-admin", password_hash="",
                 scopes=[Scope.ADMIN, Scope.READ], disabled=False)
    response = _client(store, admin).delete(f"/auth/users/{user.username}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deleted"] is True
    assert body["user_id"] == user.id
    assert body["deleted_by"] == "an-admin"
    assert store.get_user(user.username) is None


@pytest.mark.parametrize("scopes", [
    [Scope.READ],
    [Scope.READ, Scope.EXECUTE, Scope.PUBLISH],
    [Scope.DESTRUCTIVE],          # destructive is not administrative
    [],
])
def test_a_non_administrator_is_refused(store, temp_user, scopes) -> None:
    user = temp_user()
    operator = User(id="n", username="not-an-admin", password_hash="",
                    scopes=scopes, disabled=False)
    response = _client(store, operator).delete(f"/auth/users/{user.username}")
    assert response.status_code == 403, response.text
    assert store.get_user(user.username) is not None, "a refused call still deleted"


def test_deleting_an_unknown_user_is_a_404(store) -> None:
    admin = User(id="a", username="an-admin", password_hash="",
                 scopes=[Scope.ADMIN], disabled=False)
    response = _client(store, admin).delete(f"/auth/users/{_name('ghost')}")
    assert response.status_code == 404, response.text


def test_a_refusal_is_a_409_and_not_a_500(store, temp_user) -> None:
    user = temp_user()
    same = User(id="s", username=user.username, password_hash="",
                scopes=[Scope.ADMIN], disabled=False)
    response = _client(store, same).delete(f"/auth/users/{user.username}")
    assert response.status_code == 409, response.text
    assert "cannot delete itself" in response.json()["detail"]


def test_the_route_takes_one_username_and_nothing_else(store) -> None:
    """Safety here comes from what the endpoint cannot express."""
    routes = [r for r in build_router(store).routes if "DELETE" in getattr(r, "methods", set())]
    assert len(routes) == 1, [r.path for r in routes]
    assert routes[0].path == "/auth/users/{username}"
    assert list(routes[0].param_convertors) == ["username"]


def test_the_deletion_is_recorded(store, temp_user, caplog) -> None:
    """An account vanishing with no trace of who removed it is the failure."""
    user = temp_user()
    admin = User(id="a", username="an-admin", password_hash="",
                 scopes=[Scope.ADMIN], disabled=False)
    seen: list[dict] = []
    app = FastAPI()
    app.include_router(build_router(store, audit=lambda **kw: seen.append(kw)))
    app.dependency_overrides[current_user] = lambda: admin
    with caplog.at_level("WARNING"):
        response = TestClient(app).delete(f"/auth/users/{user.username}")
    assert response.status_code == 200
    assert user.username in caplog.text and user.id in caplog.text
    assert "an-admin" in caplog.text
    assert seen and seen[0]["actor"] == "an-admin"
    assert seen[0]["removed"]["user_id"] == user.id

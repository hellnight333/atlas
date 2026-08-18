"""Shared test setup.

The API is closed by default: middleware requires a session for every path that
is not on a short public allow-list. That is the correct production posture and
it means the several hundred existing endpoint tests, written when the only way
in was a loopback socket, now have no way in at all.

They are given one **here, in the tests**, rather than by adding a bypass to the
production code. A `QEVIK_DISABLE_AUTH` escape hatch would be simpler and would
also be a switch that ships — and the whole reason this control plane stayed on
loopback for so long is that an unauthenticated one can deploy sites and send
email.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _authenticated_by_default(request, monkeypatch):
    """Make endpoint tests act as a fully-scoped operator.

    Patched at the store, which is what the middleware calls, so the middleware
    itself — including its allow-list and its failure paths — still runs exactly
    as in production. Tests that are *about* authentication opt out with the
    `real_auth` marker so they exercise the genuine article.
    """
    if request.node.get_closest_marker("real_auth"):
        return
    try:
        from atlas_kernel.auth import Scope, User
        from atlas_kernel.auth.models import hash_password
        from atlas_kernel.auth.store import AuthStore
    except Exception:  # noqa: BLE001 - no auth module means nothing to patch
        return

    operator = User(
        username="test-operator",
        password_hash=hash_password("test-only-password"),
        scopes=frozenset(Scope),
    )
    monkeypatch.setattr(AuthStore, "authenticate", lambda self, token: operator)

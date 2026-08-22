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

import os

# --- database isolation ------------------------------------------------------
#
# This must run before anything imports `atlas_kernel.db`, which builds its
# engine from this variable at import time. It is placed above the other imports
# for that reason and must stay there.
#
# The suite had no isolation at all: it wrote to whatever ATLAS_DATABASE_URL
# pointed at, and on the canonical server that is production. Every run left
# fixtures behind — 108 outreach rows and 81 orphaned events had accumulated,
# enough that "how many businesses have we contacted" could not be answered
# without knowing which rows to ignore.
#
# Redirecting here rather than asking each test to opt in is deliberate. An
# opt-in is a thing a new test forgets, and the failure is silent: the test
# passes, and the damage shows up weeks later in a number nobody trusts.
# Redirecting only when the variable is already set left the case it was most
# needed in uncovered: with nothing set, `db.py` falls back to its own default
# and that default is named `atlas`. On a developer machine that is the local
# working database, and on the server it is production — so the unset case is
# not the safe one, and the guard in `db_safety` correctly refused to collect
# the suite at all until this handled it.
# Read from db_safety rather than repeated here: a second copy of the default
# would drift, and the failure mode is the suite quietly pointing at the real
# database again. db_safety builds no engine, so importing it is safe this early.
from atlas_kernel.db_safety import DEFAULT_DATABASE_URL  # noqa: E402

_CONFIGURED = os.environ.get("ATLAS_DATABASE_URL", "")
_SOURCE_URL = _CONFIGURED or DEFAULT_DATABASE_URL
if not _SOURCE_URL.rstrip("/").endswith("_test"):
    os.environ["ATLAS_DATABASE_URL"] = _SOURCE_URL.rstrip("/") + "_test"

# Only a URL somebody deliberately configured is production. The two uses pull
# in opposite directions and must not share a value: the *refusal* above treats
# an unrecognised database as production because that is the safe way to be
# wrong, while the detector in test_production_is_not_a_test_fixture asserts
# that production is clean — and pointing that at a developer's local scratch
# database makes it fail on rows that were never production's.
if _CONFIGURED:
    os.environ.setdefault("QEVIK_PRODUCTION_DATABASE_URL", _CONFIGURED)

import pytest  # noqa: E402


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

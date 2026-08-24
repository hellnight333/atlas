"""The application `run_console_acceptance.py` serves, with durable state.

A separate module because uvicorn needs an import path, and because the wiring
a real deployment uses — file-backed timelines that outlive the process — is
exactly what the acceptance test has to exercise. An in-memory default would
make the restart step prove nothing.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from atlas_kernel.auth import Scope  # noqa: E402
from atlas_kernel.auth.store import AuthStore  # noqa: E402
from atlas_kernel.qevik import Wiring, create_app  # noqa: E402

TENANT = "tenant-acceptance"
OPERATOR, PASSWORD = "acceptance", "acceptance-only-not-a-real-password"


class FileBackedList(list):
    """A list that persists itself and re-reads before it is read.

    Crude on purpose: the point of the acceptance run is the *mission* timeline,
    which is already a real append-only file. Conversations need somewhere
    equally durable for the test to mean anything, and a deployment would use a
    database rather than this.

    Re-reading on iteration is not a convenience. A store cached at construction
    is a store that cannot see another writer, and this file has two: the server
    and the acceptance script. That is the same property `mission/timeline.py`
    has for the same reason — a durable store nobody re-reads is a snapshot.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        super().__init__()
        self._reload()

    def _reload(self) -> None:
        super().clear()
        if self.path.exists():
            try:
                super().extend(json.loads(self.path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass

    def __iter__(self):                        # type: ignore[override]
        self._reload()
        return super().__iter__()

    def __len__(self) -> int:                  # type: ignore[override]
        self._reload()
        return super().__len__()

    def append(self, item) -> None:            # type: ignore[override]
        record = item if isinstance(item, dict) else {
            "kind": getattr(item, "kind", ""),
            "factory": getattr(item, "factory", ""),
            "actor": getattr(item, "actor", ""),
            "detail": getattr(item, "detail", {}) or {}}
        self._reload()
        super().append(json.loads(json.dumps(record, default=str)))
        self.path.write_text(json.dumps(list(super().__iter__()), default=str),
                             encoding="utf-8")


def build():
    """The factory uvicorn imports."""
    workspace = Path(os.environ["QEVIK_ACCEPTANCE_STATE"])
    workspace.mkdir(parents=True, exist_ok=True)

    # `AuthStore()` with no argument connects to whatever `ATLAS_DATABASE_URL`
    # names, defaulting to a local Postgres. An acceptance run must own its own
    # storage — `run_console_acceptance.py` points the variable at a sqlite file
    # in the workspace before this module is imported, and `db_safety` permits
    # sqlite explicitly.
    from atlas_kernel.auth.store import init_auth

    # Only the auth schema. `init_db()` runs a Postgres-specific `DO $$` block
    # that sqlite cannot parse, and the console needs nothing else from it.
    init_auth()
    store = AuthStore()
    # Idempotent: the acceptance run starts a second server over the same
    # database, which is the whole point of the restart step — the operator has
    # to still exist on the other side.
    if store.get_user(OPERATOR) is None:
        store.create_user(OPERATOR, PASSWORD, scopes=frozenset(Scope),
                          tenant_id=TENANT)

    return create_app(Wiring(
        auth=store,
        mission_timeline=workspace / "missions.jsonl",
        chat_events=FileBackedList(workspace / "chat.json"),
        vault_path=workspace / "vault.json",
        repository_root=workspace / "repo",
    ))

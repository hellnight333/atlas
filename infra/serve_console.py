"""Run the Qevik control panel on this machine.

    python3 infra/serve_console.py

Then open http://127.0.0.1:8080 and sign in. It prints the credentials it
created on first run.

This exists because the console had no front door that did not involve reading a
test harness. It is the same application `qevik/app.py` composes and the same one
`deploy_console.sh` puts on a server — not a demo of it — with durable state in
`~/.qevik/local/` so a mission survives stopping this process.

The vault master key is the one thing this cannot invent. Without
`QEVIK_VAULT_MASTER_KEY` the vault seals and the Credentials page says so rather
than falling back to plaintext, which is the behaviour that makes the vault worth
having.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

HOME = Path(os.environ.get("QEVIK_LOCAL_STATE", Path.home() / ".qevik" / "local"))


class Turns(list):
    """Conversation turns on disk, re-read before every read.

    A store cached at construction cannot see another writer, and this file has
    two whenever a worker runs beside the server. Same property
    `mission/timeline.py` has, for the same reason.
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

    def __iter__(self):                          # type: ignore[override]
        self._reload()
        return super().__iter__()

    def __len__(self) -> int:                    # type: ignore[override]
        self._reload()
        return super().__len__()

    def append(self, item) -> None:              # type: ignore[override]
        record = item if isinstance(item, dict) else {
            "kind": getattr(item, "kind", ""),
            "factory": getattr(item, "factory", ""),
            "actor": getattr(item, "actor", ""),
            "detail": getattr(item, "detail", {}) or {}}
        self._reload()
        super().append(json.loads(json.dumps(record, default=str)))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(list(super().__iter__()), default=str),
                             encoding="utf-8")


def build():
    """The application uvicorn serves. Same composition as production."""
    from atlas_kernel.auth import Scope
    from atlas_kernel.auth.store import AuthStore, init_auth
    from atlas_kernel.qevik import Wiring, create_app

    HOME.mkdir(parents=True, exist_ok=True)
    init_auth()
    store = AuthStore()

    username = os.environ.get("QEVIK_LOCAL_USER", "ayoub")
    if store.get_user(username) is None:
        # Written to a file readable only by this account, and printed once.
        # Not committed, not logged, and not reused if one already exists.
        password = secrets.token_urlsafe(18)
        store.create_user(username, password, scopes=frozenset(Scope),
                          tenant_id="tenant-qevik")
        secret_file = HOME / "first-login.txt"
        secret_file.write_text(
            f"username: {username}\npassword: {password}\n", encoding="utf-8")
        secret_file.chmod(0o600)
        print(f"\n  Created a local operator.\n"
              f"  username: {username}\n  password: {password}\n"
              f"  (also written to {secret_file}, mode 600)\n")

    return create_app(Wiring(
        auth=store,
        mission_timeline=HOME / "missions.jsonl",
        chat_events=Turns(HOME / "chat.json"),
        vault_path=HOME / "vault.json",
        repository_root=ROOT,
    ))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    os.environ.setdefault(
        "ATLAS_DATABASE_URL", f"sqlite+pysqlite:///{HOME / 'qevik.db'}")
    HOME.mkdir(parents=True, exist_ok=True)

    sealed = not os.environ.get("QEVIK_VAULT_MASTER_KEY")
    print("=" * 66)
    print("  Qevik control panel")
    print("=" * 66)
    print(f"  http://{args.host}:{args.port}")
    print(f"  state    {HOME}")
    if sealed:
        print()
        print("  VAULT SEALED — QEVIK_VAULT_MASTER_KEY is not set, so the")
        print("  Credentials page can show providers but cannot store a key.")
        print("  It refuses rather than writing plaintext. To unseal:")
        print()
        print("    export QEVIK_VAULT_MASTER_KEY=\"$(python3 -c "
              "'import secrets;print(secrets.token_urlsafe(32))')\"")
        print()
        print("  Keep that value: the vault cannot be read without it.")
    print("=" * 66)

    import uvicorn

    uvicorn.run(build(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

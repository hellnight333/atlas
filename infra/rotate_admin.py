#!/usr/bin/env python3
"""Rotate the Qevik admin password. Never prints it.

The old password was generated once and left in plaintext in `/opt/qevik/atlas.env`,
where it stayed readable for as long as the file did. It has since been read aloud.
This replaces it with a fresh secret that this program generates, uses, writes to
that same 0600 file, and never emits — not to stdout, not to the log, not to an
argument another process could see in `ps`.

The order matters, and it is the opposite of the obvious one:

    1. generate
    2. write the new value to the env file, keeping a backup
    3. update the database hash and revoke every live session
    4. log in through the PUBLIC url with the new password
    5. only then remove the backup

Verification happens against `https://app.qevik.ai`, not loopback, because the
question being answered is "can the operator log in", and the operator arrives
through Cloudflare, Caddy and the auth middleware. A loopback check would pass
while any one of those was broken.

If verification fails the backup is restored and the exit code is non-zero, so a
failed rotation leaves a working credential rather than a locked-out control
plane. The database hash cannot be rolled back — it is a one-way function of a
password nobody kept — so the restore also re-applies the old file's password to
the database, which is why the old value is read before anything changes.

    rotate_admin.py                    # rotate, verify, report
    rotate_admin.py --verify-only      # check the stored password still works
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

import httpx  # noqa: E402

ENV_FILE = Path(os.environ.get("QEVIK_ENV_FILE", "/opt/qevik/atlas.env"))
KEY = "QEVIK_ADMIN_PASSWORD"
LOGIN_URL = os.environ.get("QEVIK_LOGIN_URL", "https://app.qevik.ai/auth/login")
USERNAME = "admin"

#: No ambiguous glyphs. The operator will read this off a terminal and type it
#: into a browser, and a rotation that produces a password they mistype is a
#: rotation that gets rolled back for the wrong reason.
ALPHABET = "".join(
    c for c in string.ascii_letters + string.digits + "!@#$%^&*-_=+" if c not in "Il1O0"
)


def generate(length: int = 32) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.startswith("#"):
            values[key.strip()] = value
    return values


def write_env(key: str, value: str) -> None:
    """Replace one key, preserving every other line exactly.

    Rewritten through a temp file in the same directory and moved into place, so
    a crash mid-write cannot leave the control plane with a truncated env file
    and no database URL.
    """
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    out, replaced = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(f"{key}={value}")

    temp = ENV_FILE.with_suffix(".tmp")
    temp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.chmod(temp, 0o600)
    shutil.chown(temp, user=ENV_FILE.owner(), group=ENV_FILE.group())
    os.replace(temp, ENV_FILE)


def can_log_in(password: str) -> tuple[bool, str]:
    try:
        response = httpx.post(
            LOGIN_URL,
            json={"username": USERNAME, "password": password},
            timeout=30.0,
        )
    except httpx.HTTPError as failure:
        return False, f"could not reach {LOGIN_URL}: {failure}"
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}"
    # A 200 with no token would be a broken login that looks like a working one.
    body = response.json() if response.headers.get("content-type", "").startswith(
        "application/json"
    ) else {}
    if not any(k in body for k in ("token", "session", "access_token")):
        return False, "200 but no session token in the response"
    return True, "session issued"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)

    if not ENV_FILE.exists():
        print(f"no env file at {ENV_FILE}", file=sys.stderr)
        return 1

    current = read_env().get(KEY, "")
    if not current:
        print(f"{KEY} is not set in {ENV_FILE}", file=sys.stderr)
        return 1

    if args.verify_only:
        ok, detail = can_log_in(current)
        print(f"stored password: {'WORKS' if ok else 'REJECTED'} — {detail}")
        return 0 if ok else 1

    from atlas_kernel.auth.store import AuthStore, init_auth

    init_auth()
    store = AuthStore()

    backup = ENV_FILE.with_suffix(".pre-rotation")
    shutil.copy2(ENV_FILE, backup)
    os.chmod(backup, 0o600)
    print(f"backup      : {backup}")

    new_password = generate()
    write_env(KEY, new_password)
    print(f"env file    : {KEY} replaced ({len(new_password)} chars, not shown)")

    ended = store.set_password(USERNAME, new_password)
    print(f"database    : hash replaced, {ended} live session(s) revoked")

    ok, detail = can_log_in(new_password)
    if not ok:
        # Put the old password back in both places, so a failed rotation is a
        # no-op rather than a lockout.
        shutil.copy2(backup, ENV_FILE)
        store.set_password(USERNAME, current)
        print(f"VERIFY FAILED — {detail}", file=sys.stderr)
        print("rolled back: old password restored in the env file and the database")
        return 1

    print(f"verified    : login through {LOGIN_URL} — {detail}")
    backup.unlink()
    print("backup      : removed")
    print()
    print("The new password is in the env file and nowhere else. Read it with:")
    print(f"  ssh -i ~/.ssh/naml_hetzner root@2.28.62.83 \"grep '^{KEY}=' {ENV_FILE}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

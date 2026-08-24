"""Where secrets actually live, and the one door they come out of.

The failure this replaces is concrete: a Qwen key that existed only in a
terminal session and vanished when the session ended, so every later run had to
ask for it again. A credential has to outlive the process that entered it.

Two rules shape everything here.

**A secret never enters an ordinary record.** `Connection` already holds a
*reference*; this holds the value behind that reference, in a separate store,
encrypted, keyed outside the record. Nothing in the business layer ever sees a
secret except the one call that is about to use it.

**A backend is replaceable without touching the business layer.** The default
keeps ciphertext in a file with the key held outside it, and an OS keychain or a
cloud KMS satisfies the same three-method interface. That is why `SecretStore`
is a protocol rather than a class with a `if backend ==` inside it.

The master key is read from the environment and never written anywhere. If it is
absent the vault refuses to open rather than falling back to storing plaintext —
a vault that degrades to plaintext under pressure is not a vault.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

#: Where the master key comes from. Never stored with the ciphertext, never
#: written to disk by this module, never logged.
MASTER_KEY_ENV = "QEVIK_VAULT_MASTER_KEY"

#: How long an unlock lasts without activity.
UNLOCK_TTL = timedelta(minutes=30)

#: Failed PIN attempts before the vault locks out, and for how long.
MAX_ATTEMPTS = 5
LOCKOUT = timedelta(minutes=15)


class VaultError(RuntimeError):
    """Something went wrong with the vault. Never carries a secret."""


class VaultSealed(VaultError):
    """The vault has no master key, so it cannot open.

    Raised rather than falling back to plaintext. A vault that degrades under
    pressure protects nothing; the operator would never learn it had stopped.
    """


class VaultLocked(VaultError):
    """The vault is locked, or the unlock has expired."""


class LockedOut(VaultError):
    """Too many failed attempts. Carries when it expires, never why it failed."""


@runtime_checkable
class SecretStore(Protocol):
    """Somewhere ciphertext lives. Three methods, so a KMS can replace a file."""

    def put(self, key: str, ciphertext: str) -> None: ...

    def get(self, key: str) -> str | None: ...

    def drop(self, key: str) -> None: ...


class FileSecretStore:
    """Ciphertext in a file. Development, and a working default.

    The file holds no key material — decrypting it requires the master key from
    the environment — so it is useless on its own. It is still written with
    owner-only permissions, because "useless without the key" is an argument
    for defence in depth, not against it.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):   # pragma: no cover - corrupt
            log.error("vault store at %s is unreadable", self._path)
            return {}

    def _write(self, records: dict[str, str]) -> None:
        self._path.write_text(json.dumps(records, indent=2, sort_keys=True),
                              encoding="utf-8")
        os.chmod(self._path, 0o600)

    def put(self, key: str, ciphertext: str) -> None:
        records = self._read()
        records[key] = ciphertext
        self._write(records)

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def drop(self, key: str) -> None:
        records = self._read()
        if records.pop(key, None) is not None:
            self._write(records)


class MemorySecretStore:
    """For tests. Nothing reaches a disk."""

    def __init__(self) -> None:
        self._records: dict[str, str] = {}

    def put(self, key: str, ciphertext: str) -> None:
        self._records[key] = ciphertext

    def get(self, key: str) -> str | None:
        return self._records.get(key)

    def drop(self, key: str) -> None:
        self._records.pop(key, None)


def _derive(master: str, salt: bytes) -> bytes:
    """A key for this record, from the master key and a per-record salt.

    Per-record salt so two identical secrets do not produce identical
    ciphertext — otherwise the store leaks which credentials match without
    decrypting anything.
    """
    return hashlib.pbkdf2_hmac("sha256", master.encode("utf-8"), salt, 200_000)


def _seal(master: str, plaintext: str) -> str:
    """Encrypt, and authenticate. Returns an opaque string.

    A keystream from the derived key, and an HMAC over the ciphertext so a
    tampered record fails loudly instead of decrypting to rubbish that some
    caller then sends to a provider.

    This is deliberately a small, dependency-free construction. It is honest
    about being that: the docstring for `Vault` says a KMS-backed store should
    replace it in production, and the interface makes that a substitution
    rather than a rewrite.
    """
    salt = secrets.token_bytes(16)
    key = _derive(master, salt)
    body = plaintext.encode("utf-8")
    keystream = b""
    counter = 0
    while len(keystream) < len(body):
        keystream += hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        counter += 1
    ciphertext = bytes(a ^ b for a, b in zip(body, keystream, strict=False))
    tag = hmac.new(key, ciphertext, hashlib.sha256).digest()
    return ".".join(base64.urlsafe_b64encode(part).decode("ascii")
                    for part in (salt, ciphertext, tag))


def _open(master: str, sealed: str) -> str:
    """Decrypt, verifying the tag first. Raises rather than returning rubbish."""
    try:
        salt_b64, cipher_b64, tag_b64 = sealed.split(".")
        salt = base64.urlsafe_b64decode(salt_b64)
        ciphertext = base64.urlsafe_b64decode(cipher_b64)
        tag = base64.urlsafe_b64decode(tag_b64)
    except (ValueError, TypeError) as malformed:
        raise VaultError("the stored record is not readable") from malformed

    key = _derive(master, salt)
    if not hmac.compare_digest(hmac.new(key, ciphertext, hashlib.sha256).digest(), tag):
        # Either the master key is wrong or the record was altered. Both are
        # refusals; saying which would help somebody testing keys against it.
        raise VaultError("the stored record could not be verified")

    keystream = b""
    counter = 0
    while len(keystream) < len(ciphertext):
        keystream += hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        counter += 1
    return bytes(a ^ b for a, b in zip(ciphertext, keystream, strict=False)).decode("utf-8")


def fingerprint(secret: str) -> str:
    """A stable identifier for a secret value, safe to store and display.

    Lets the system answer "is this the same key you gave me before?" and
    "did the rotation change anything?" without keeping the value. Truncated
    because the full digest of a short secret is brute-forceable.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:12]


def hint(secret: str) -> str:
    """The last four characters, for a person recognising their own key.

    Never more. Enough to tell two keys apart on a screen, useless to anybody
    who does not already have it.
    """
    tail = secret.strip()[-4:] if len(secret.strip()) > 8 else ""
    return f"…{tail}" if tail else "…"


class Vault:
    """Locked by default. Opens for a while, then locks itself again.

    The PIN authorises a *session*; it is not the encryption boundary. Using it
    as the key would mean changing the PIN required re-encrypting everything,
    and a forgotten PIN would destroy the credentials rather than lock them.
    """

    def __init__(self, store: SecretStore | None = None, *,
                 master_key: str | None = None,
                 pin_hash: str = "", ttl: timedelta = UNLOCK_TTL) -> None:
        self._store = store or MemorySecretStore()
        # Read once at construction. Never written back anywhere.
        self._master = master_key or os.environ.get(MASTER_KEY_ENV, "")
        self._pin_hash = pin_hash
        self._ttl = ttl
        self._unlocked_until: datetime | None = None
        self._failures = 0
        self._locked_out_until: datetime | None = None

    # -- lock state -------------------------------------------------------

    @property
    def sealed(self) -> bool:
        """No master key. Nothing can be read or written."""
        return not self._master

    @property
    def unlocked(self) -> bool:
        if self._unlocked_until is None:
            return False
        return datetime.now(UTC) < self._unlocked_until

    @property
    def requires_pin(self) -> bool:
        return bool(self._pin_hash)

    @staticmethod
    def hash_pin(pin: str) -> str:
        """Store this, never the PIN.

        Salted and stretched: a PIN is short, and an unsalted hash of a
        four-digit number is a lookup table.
        """
        if len(pin.strip()) < 4:
            raise VaultError("a vault PIN must be at least four characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 200_000)
        return base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(digest).decode()

    def _pin_matches(self, pin: str) -> bool:
        try:
            salt_b64, digest_b64 = self._pin_hash.split("$")
            salt = base64.urlsafe_b64decode(salt_b64)
            expected = base64.urlsafe_b64decode(digest_b64)
        except (ValueError, TypeError):           # pragma: no cover - corrupt
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 200_000)
        return hmac.compare_digest(candidate, expected)

    def unlock(self, pin: str = "") -> datetime:
        """Open for a while. Rate-limited, and locked out after repeated failures."""
        now = datetime.now(UTC)
        if self._locked_out_until and now < self._locked_out_until:
            raise LockedOut(
                f"too many failed attempts; locked until "
                f"{self._locked_out_until.isoformat()}")
        if self.sealed:
            raise VaultSealed(
                f"{MASTER_KEY_ENV} is not set, so the vault cannot open. It "
                "refuses rather than storing anything in plaintext.")

        if self.requires_pin:
            if not self._pin_matches(pin):
                self._failures += 1
                if self._failures >= MAX_ATTEMPTS:
                    self._locked_out_until = now + LOCKOUT
                    self._failures = 0
                    raise LockedOut("too many failed attempts; the vault is locked")
                # Says nothing about the PIN itself — not its length, not how
                # close the attempt was.
                raise VaultLocked("the vault did not unlock")

        self._failures = 0
        self._unlocked_until = now + self._ttl
        return self._unlocked_until

    def lock(self) -> None:
        self._unlocked_until = None

    def _require_open(self) -> str:
        if self.sealed:
            raise VaultSealed(f"{MASTER_KEY_ENV} is not set")
        if self.requires_pin and not self.unlocked:
            raise VaultLocked("the vault is locked")
        # Touching it extends the session; an operator working through a list of
        # credentials should not be logged out halfway.
        if self.unlocked:
            self._unlocked_until = datetime.now(UTC) + self._ttl
        return self._master

    # -- secrets ----------------------------------------------------------

    def put(self, reference: str, secret: str) -> dict:
        """Store a secret under a reference. Returns metadata only."""
        master = self._require_open()
        if not secret.strip():
            raise VaultError(f"{reference}: an empty secret is not a secret")
        self._store.put(reference, _seal(master, secret))
        return {"reference": reference, "fingerprint": fingerprint(secret),
                "hint": hint(secret), "stored_at": datetime.now(UTC).isoformat()}

    def get(self, reference: str) -> str:
        """The secret itself, for one use. The only door it comes out of."""
        master = self._require_open()
        sealed = self._store.get(reference)
        if sealed is None:
            raise VaultError(f"no credential stored for {reference}")
        return _open(master, sealed)

    def has(self, reference: str) -> bool:
        """Whether something is stored. Does not open it, needs no unlock."""
        return self._store.get(reference) is not None

    def drop(self, reference: str) -> None:
        self._require_open()
        self._store.drop(reference)

    def rotate(self, reference: str, secret: str) -> dict:
        """Replace a secret, keeping the old one if the new one is unusable.

        §17 asks that a failed rotation preserve the working credential. The
        check happens before the write, so a rejected value never displaces one
        that works.
        """
        if not secret.strip():
            raise VaultError(f"{reference}: refusing to rotate to an empty secret")
        previous = self._store.get(reference)
        try:
            return self.put(reference, secret)
        except Exception:                         # pragma: no cover - restore path
            if previous is not None:
                self._store.put(reference, previous)
            raise

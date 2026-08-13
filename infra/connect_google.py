"""Connect a Google account to Qevik. Run once, by a human, at a browser.

    python infra/connect_google.py

Reads the client secrets from the environment (``QEVIK_GOOGLE_CLIENT_SECRETS_FILE``
or ``~/.qevik/credentials/google_client_secret.json``), opens Google's consent
screen, and stores the resulting token at ``~/.qevik/credentials/google_token.json``
with mode 0600.

This cannot be automated and should not be: it exists so a person sees which
account they are connecting and which permissions they are granting. Nothing
here prints the client secret, the access token or the refresh token.

Requires a **Desktop app** OAuth client. Google applies port-agnostic loopback
matching to that client type (RFC 8252 §7.3), so the ephemeral port this flow
listens on needs no registration in the console.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.media.publishers.google_oauth import (  # noqa: E402
    CREDENTIALS_DIR,
    ClientSecrets,
    DesktopAuthFlow,
    GoogleCredentials,
    OAuthError,
    TokenStore,
)
from atlas_kernel.opportunity.gmail import GMAIL_SEND_SCOPES  # noqa: E402

TOKEN_PATH = CREDENTIALS_DIR / "google_token.json"


def main() -> int:
    try:
        secrets = ClientSecrets.from_environment()
    except OAuthError as error:
        print(f"Cannot start: {error}", file=sys.stderr)
        return 1

    store = TokenStore(TOKEN_PATH)
    if store.load() is not None:
        print(f"A token already exists at {TOKEN_PATH}.")
        print("Delete it first if you want to connect a different account.")
        return 0

    print("Scopes being requested:")
    for scope in GMAIL_SEND_SCOPES:
        print(f"  {scope}")
    print("\nSend-only. Qevik cannot read this mailbox.\n")
    print("Opening Google's consent screen. If no browser opens, the URL is printed below.\n")

    flow = DesktopAuthFlow(secrets, scopes=GMAIL_SEND_SCOPES)
    try:
        token = flow.authorise()
    except OAuthError as error:
        print(f"Authorisation failed: {error}", file=sys.stderr)
        return 1

    store.save(token)

    # Deliberately reports only non-secret facts. The token itself is never
    # printed, and neither is any part of it.
    credentials = GoogleCredentials(flow, store)
    print(f"Connected. Token stored at {TOKEN_PATH} (mode 0600).")
    print(f"Granted scopes: {' '.join(token.scopes) or '(none reported)'}")
    print(f"Refresh token present: {'yes' if token.refresh_token else 'NO — see below'}")
    if not token.refresh_token:
        print(
            "\nWithout a refresh token this connection stops working when the access "
            "token expires. Revoke Qevik at https://myaccount.google.com/permissions "
            "and run this again.",
            file=sys.stderr,
        )
        return 1
    print(f"Usable now: {'yes' if credentials.connected else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

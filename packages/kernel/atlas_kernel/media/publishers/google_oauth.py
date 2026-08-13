"""Google's installed-application OAuth flow, and the tokens it produces.

Implemented against the documented protocol rather than with
``google-auth-oauthlib``, for two reasons that are specific to Atlas rather than
general preferences:

* Atlas ships as a PyInstaller binary, and the Google client libraries are a
  well-known source of packaging breakage -- discovery documents resolved at
  runtime, data files that must be declared by hand. M012 spent two days on
  exactly that class of bug and it is not worth inviting back for four HTTP
  calls.
* The flow *is* four HTTP calls. What it is not is a place to be casual, so
  PKCE and state are both implemented and both tested.

Only the parts Atlas uses are here. This is not a general OAuth client.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import httpx

AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

#: Upload needs ``youtube.upload``; captions need ``force-ssl``. Requested
#: together so a caption failure is not a second consent screen months later.
YOUTUBE_SCOPES = (
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
)

#: Refresh slightly early. A token that expires while a 140 MB upload is in
#: flight fails the whole upload, and the clock is not perfectly synchronised.
EXPIRY_MARGIN = timedelta(seconds=120)

#: Where credentials live by default — **outside the working tree**, and not
#: configurable to somewhere inside it by accident. A secret stored in the repo
#: is one ``git add -A`` from being published, and that command is run by tired
#: people at the end of long days.
CREDENTIALS_DIR = Path.home() / ".qevik" / "credentials"

#: Owner-only. Google's download lands world-readable in ~/Downloads, and moving
#: it without tightening the mode carries that across.
SECRET_FILE_MODE = 0o600

#: Preferred prefix after the rename; the old one still resolves so nothing that
#: already works stops working.
_ENV_PREFIXES = ("QEVIK_", "ATLAS_")


def _env(name: str) -> str | None:
    """First non-empty value across the accepted prefixes.

    Empty strings are treated as unset. An exported-but-blank variable is the
    usual result of a half-finished shell profile, and honouring it produces an
    authentication error that points at Google rather than at the shell.
    """
    for prefix in _ENV_PREFIXES:
        value = os.environ.get(f"{prefix}{name}")
        if value and value.strip():
            return value.strip()
    return None


def default_client_secrets_path() -> Path:
    return CREDENTIALS_DIR / "google_client_secret.json"


class OAuthError(RuntimeError):
    """The authorisation flow could not complete."""


class NotAuthorised(OAuthError):
    """No usable credentials.

    Its own type so a caller can tell "nobody has connected an account yet"
    from "the upload failed", which are different problems with different fixes.
    """


@dataclass(frozen=True)
class ClientSecrets:
    """The client-secrets JSON downloaded from Google Cloud.

    Only the ``installed`` (Desktop app) shape is accepted. A web client would
    also parse, and then fail at the redirect with a message that sends the
    reader somewhere unhelpful -- so it is rejected by name here instead.
    """

    client_id: str
    client_secret: str

    @classmethod
    def from_file(cls, path: Path) -> ClientSecrets:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OAuthError(f"could not read client secrets at {path}: {error}") from error

        if "installed" not in payload:
            kind = ", ".join(payload) or "nothing recognisable"
            raise OAuthError(
                f"{path} is not a Desktop app client-secrets file (it contains {kind}). "
                "In Google Cloud, create an OAuth client of type 'Desktop app' and "
                "download its JSON."
            )
        section = payload["installed"]
        try:
            return cls(client_id=section["client_id"], client_secret=section["client_secret"])
        except KeyError as error:
            raise OAuthError(f"{path} is missing {error}") from error

    @classmethod
    def from_environment(cls) -> ClientSecrets:
        """Resolve credentials without a path being written into the codebase.

        Three sources, in order, and the order is the point: the most explicit
        wins, and the default is a location **outside the repository**.

        1. ``QEVIK_GOOGLE_CLIENT_ID`` + ``QEVIK_GOOGLE_CLIENT_SECRET`` — direct
           values, for CI and containers where mounting a file is the awkward
           option.
        2. ``QEVIK_GOOGLE_CLIENT_SECRETS_FILE`` — a path to the JSON Google
           issued.
        3. ``~/.qevik/credentials/google_client_secret.json`` — the default,
           deliberately not inside the working tree. A credential that lives in
           the repository is a credential one ``git add -A`` away from being
           published, and that command gets run by tired people.

        ``ATLAS_``-prefixed names are still accepted so nothing that already
        works stops working.

        Raises rather than returning ``None``: a missing credential should stop
        the caller with an actionable message, not surface three frames later as
        an authentication failure.
        """
        client_id = _env("GOOGLE_CLIENT_ID")
        client_secret = _env("GOOGLE_CLIENT_SECRET")
        if client_id and client_secret:
            return cls(client_id=client_id, client_secret=client_secret)

        configured = _env("GOOGLE_CLIENT_SECRETS_FILE")
        path = Path(configured).expanduser() if configured else default_client_secrets_path()
        if not path.is_file():
            raise OAuthError(
                "no Google client secrets configured. Either set "
                "QEVIK_GOOGLE_CLIENT_ID and QEVIK_GOOGLE_CLIENT_SECRET, or point "
                "QEVIK_GOOGLE_CLIENT_SECRETS_FILE at the JSON Google issued, or "
                f"place that file at {default_client_secrets_path()}. "
                "Do not put it inside the repository."
            )
        return cls.from_file(path)

    def __repr__(self) -> str:
        """Never render the secret.

        A dataclass prints its fields, so the default repr puts a live client
        secret into every traceback, log line and debugger session that touches
        one of these. That is not a hypothetical: exception text is the most
        common way a secret escapes.
        """
        return f"ClientSecrets(client_id={self.client_id!r}, client_secret='***')"

    __str__ = __repr__


@dataclass
class Token:
    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scopes: tuple[str, ...] = ()

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(UTC) + EXPIRY_MARGIN >= self.expires_at

    def to_json(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scopes": list(self.scopes),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any]) -> Token:
        expires = payload.get("expires_at")
        return cls(
            access_token=payload.get("access_token", ""),
            refresh_token=payload.get("refresh_token"),
            expires_at=datetime.fromisoformat(expires) if expires else None,
            scopes=tuple(payload.get("scopes", ())),
        )


class TokenStore:
    """A refresh token on disk, readable only by its owner.

    Not encrypted. That is the same choice ``gcloud``, ``gh`` and ``aws`` make,
    and it is stated plainly rather than implied: anything that can read the
    file as this user can act as this user on the connected channel. When Atlas
    grows a real vault this moves into it, which is a change of one class.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Token | None:
        if not self.path.exists():
            return None
        try:
            return Token.from_json(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError):
            # A corrupt token is not a crash: re-authorising is the fix, and
            # saying so beats a stack trace about JSON.
            return None

    def save(self, token: Token) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Written 0600 from the start rather than chmod-ed afterwards, so it is
        # never briefly world-readable.
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(token.to_json(), handle)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclass
class _Capture:
    code: str | None = None
    state: str | None = None
    error: str | None = None
    received: threading.Event = field(default_factory=threading.Event)


def _handler(capture: _Capture) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

            def first(name: str) -> str | None:
                values = query.get(name)
                return values[0] if values else None

            capture.code = first("code")
            capture.state = first("state")
            capture.error = first("error")

            body = (
                b"<html><body style='font-family:system-ui;padding:3rem'>"
                b"<h2>Qevik is connected.</h2>"
                b"<p>You can close this tab and go back to Qevik.</p>"
                b"</body></html>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            capture.received.set()

        def log_message(self, *_args: Any) -> None:
            """Silence. The server exists for one redirect and should not
            narrate it to stderr."""

    return Handler


class DesktopAuthFlow:
    """The consent dance, once, on the machine the operator is sitting at."""

    def __init__(
        self,
        secrets_file: ClientSecrets,
        *,
        scopes: tuple[str, ...] = YOUTUBE_SCOPES,
        client: httpx.Client | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        self.secrets = secrets_file
        self.scopes = scopes
        self._client = client
        self.timeout_seconds = timeout_seconds

    def authorise(self, *, open_browser: bool = True) -> Token:
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        state = secrets.token_urlsafe(32)

        capture = _Capture()
        server = HTTPServer(("127.0.0.1", 0), _handler(capture))
        redirect_uri = f"http://127.0.0.1:{server.server_port}"

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = self.authorisation_url(redirect_uri, challenge, state)
            if open_browser:
                webbrowser.open(url)

            if not capture.received.wait(self.timeout_seconds):
                raise OAuthError(
                    f"no response from Google within {self.timeout_seconds}s. "
                    f"If a browser did not open, visit:\n{url}"
                )
        finally:
            server.shutdown()
            server.server_close()

        if capture.error:
            raise OAuthError(f"Google refused the request: {capture.error}")
        # Checked before the code is used for anything. A mismatched state means
        # the redirect did not come from the request Atlas made.
        if capture.state != state:
            raise OAuthError(
                "the authorisation response did not match the request (state mismatch). "
                "Nothing was exchanged."
            )
        if not capture.code:
            raise OAuthError("Google returned no authorisation code")

        return self.exchange(capture.code, redirect_uri, verifier)

    def authorisation_url(self, redirect_uri: str, challenge: str, state: str) -> str:
        query = urllib.parse.urlencode(
            {
                "client_id": self.secrets.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(self.scopes),
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                # Without both of these Google returns no refresh token on a
                # repeat authorisation, and Atlas would work today and stop
                # working tomorrow.
                "access_type": "offline",
                "prompt": "consent",
            }
        )
        return f"{AUTH_ENDPOINT}?{query}"

    def exchange(self, code: str, redirect_uri: str, verifier: str) -> Token:
        payload = {
            "code": code,
            "client_id": self.secrets.client_id,
            "client_secret": self.secrets.client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }
        return self._token_request(payload, require_refresh=True)

    def refresh(self, refresh_token: str) -> Token:
        payload = {
            "refresh_token": refresh_token,
            "client_id": self.secrets.client_id,
            "client_secret": self.secrets.client_secret,
            "grant_type": "refresh_token",
        }
        token = self._token_request(payload, require_refresh=False)
        # A refresh response does not repeat the refresh token, and dropping it
        # would silently turn a long-lived connection into a single-use one.
        return Token(
            access_token=token.access_token,
            refresh_token=refresh_token,
            expires_at=token.expires_at,
            scopes=token.scopes,
        )

    def _token_request(self, payload: dict[str, str], *, require_refresh: bool) -> Token:
        client = self._client or httpx.Client(timeout=30)
        try:
            response = client.post(TOKEN_ENDPOINT, data=payload)
        except httpx.HTTPError as error:
            raise OAuthError(f"could not reach Google's token endpoint: {error}") from error
        finally:
            if self._client is None:
                client.close()

        if response.status_code != 200:
            raise OAuthError(f"token request failed ({response.status_code}): {response.text}")

        body = response.json()
        expires_in = body.get("expires_in")
        token = Token(
            access_token=body["access_token"],
            refresh_token=body.get("refresh_token"),
            expires_at=(
                datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
            ),
            scopes=tuple((body.get("scope") or "").split()) or self.scopes,
        )
        if require_refresh and not token.refresh_token:
            raise OAuthError(
                "Google did not return a refresh token. Atlas would lose access the "
                "moment this one expires. Revoke Atlas's access in your Google account "
                "and authorise again."
            )
        return token


class GoogleCredentials:
    """A token that keeps itself usable."""

    def __init__(self, flow: DesktopAuthFlow, store: TokenStore) -> None:
        self.flow = flow
        self.store = store

    def access_token(self) -> str:
        token = self.store.load()
        if token is None or not token.access_token:
            raise NotAuthorised(
                "Atlas is not connected to a YouTube channel yet. Run the authorisation "
                "flow once to connect one."
            )
        if not token.expired:
            return token.access_token

        if not token.refresh_token:
            raise NotAuthorised(
                "the stored credentials have expired and carry no refresh token. Authorise again."
            )
        refreshed = self.flow.refresh(token.refresh_token)
        self.store.save(refreshed)
        return refreshed.access_token

    @property
    def connected(self) -> bool:
        return self.store.load() is not None

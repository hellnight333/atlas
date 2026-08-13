"""Sending through Gmail.

The first real channel behind M014's ``OutreachChannel`` protocol, which was
written for this and has been waiting for a sending identity:

    "This is the MVP's only channel, because Atlas has no sending identity yet
    -- no domain, no mailbox, no reputation to protect or ruin. A real SMTP
    channel is a small amount of code once those exist."

It is a small amount of code, because everything around it already exists.
``OutreachService`` checks approval, the fingerprint, suppression and the
cooldown *before* this is called, so nothing here validates any of that — a
guard duplicated into every channel is a guard that will eventually be missing
from one of them. By the time ``deliver`` runs, the decision to send has been
made and audited.

The OAuth flow is imported from ``media.publishers.google_oauth`` rather than
moved. It now has two consumers, which is the point at which the rule stated in
``website/gate.py`` says to import: *"If a third consumer appears, that is when
it moves."* Moving it now would be a refactor across a frozen milestone to save
one import line.

**Scope: ``gmail.send`` only.** Atlas can send and cannot read. That is not a
default worth widening casually — a credential that can read a mailbox is a
different thing to hold than one that can only add to it, and the narrower one
is what outreach actually needs.
"""

from __future__ import annotations

import base64
from email.message import EmailMessage

import httpx

from ..media.publishers.google_oauth import GoogleCredentials, NotAuthorised, OAuthError
from .models import OutreachMessage
from .outreach import SendResult

#: Send-only. Cannot read, cannot delete, cannot list.
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SEND_SCOPES: tuple[str, ...] = (GMAIL_SEND_SCOPE,)

SEND_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

#: Generous. A send is one small request, but a slow network should surface as
#: an error rather than a hang.
REQUEST_TIMEOUT_SECONDS = 30.0


class GmailSendError(RuntimeError):
    """Gmail refused the message.

    Distinct from ``NotAuthorised``: "nobody has connected an account" and
    "Google rejected this particular message" have different fixes, and
    collapsing them sends the reader to the wrong place.
    """


def build_mime(message: OutreachMessage, *, sender: str | None = None) -> str:
    """RFC 2822, base64url-encoded the way Gmail's API expects.

    ``urlsafe_b64encode`` rather than ``standard_b64encode``: Gmail requires the
    URL-safe alphabet, and the standard one differs in exactly two characters —
    so a message containing neither works fine and a message containing either
    is rejected with a message about the payload rather than the encoding. That
    is a bug that appears at random, weeks later.
    """
    mime = EmailMessage()
    mime["To"] = message.recipient
    mime["Subject"] = message.subject
    if sender:
        mime["From"] = sender
    mime.set_content(message.body)
    return base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")


class GmailChannel:
    """Delivers one already-approved message through Gmail.

    ``sender`` is optional. Gmail sends as the authenticated account, and
    setting ``From`` to anything else requires a verified send-as alias — so a
    value here that has not been configured in Gmail is silently ignored by
    Google, or rejected, depending on the address. Leaving it unset is the
    honest default.
    """

    def __init__(
        self,
        credentials: GoogleCredentials,
        *,
        sender: str | None = None,
        client: httpx.Client | None = None,
        name: str = "gmail",
    ) -> None:
        self._credentials = credentials
        self._sender = sender
        self._client = client
        self._owns_client = client is None
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def deliver(self, message: OutreachMessage) -> SendResult:
        """Send it. Approval, suppression and cooldown are already decided."""
        token = self._credentials.access_token()

        try:
            response = self._get_client().post(
                SEND_ENDPOINT,
                headers={"Authorization": f"Bearer {token}"},
                json={"raw": build_mime(message, sender=self._sender)},
            )
        except httpx.HTTPError as error:
            raise GmailSendError(f"could not reach Gmail: {error}") from error

        if response.status_code == 401:
            # The credential is stale or revoked. Not a message problem, and
            # retrying the send cannot fix it.
            raise NotAuthorised("Gmail rejected the credentials (401). Authorise Qevik again.")
        if response.status_code == 403:
            raise GmailSendError(
                "Gmail refused the send (403). The usual cause is that the "
                f"connected account was not granted {GMAIL_SEND_SCOPE}, or the "
                "OAuth app is in Testing and this account is not a test user."
            )
        if response.status_code == 429:
            raise GmailSendError("Gmail rate-limited the send (429). Back off and retry later.")
        if response.status_code >= 400:
            # Google's error body can echo request content. Only the status and
            # a short reason are surfaced -- never the body, which contains the
            # message that was being sent.
            raise GmailSendError(f"Gmail refused the send ({response.status_code}).")

        body = response.json() if response.content else {}
        return SendResult(
            message_id=body.get("id"),
            detail=f"sent via Gmail (thread {body.get('threadId', 'unknown')})",
        )


def connected_channel(
    credentials: GoogleCredentials,
    *,
    sender: str | None = None,
) -> GmailChannel:
    """A channel, or a clear error about what is missing.

    Fails at construction rather than at the first send. Discovering that
    nothing is connected while a batch of approved proposals is going out is
    strictly worse than discovering it now.
    """
    if not credentials.connected:
        raise OAuthError(
            "no Google account is connected. Run `python infra/connect_google.py` once."
        )
    return GmailChannel(credentials, sender=sender)

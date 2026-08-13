"""Sending through Gmail (M014's first real channel).

Driven against a controlled transport, so the real request shapes are exercised
without a network or a credential. What is being defended:

**The channel validates nothing.** ``OutreachService`` has already checked
approval, the fingerprint, suppression and the cooldown. A channel that
re-checks is a second implementation of the same policy, and the M014 lesson is
that a guard duplicated is a guard eventually missing from one copy.

**Nothing secret reaches an error message.** Google's error bodies can echo the
request, which for this channel means the message being sent. Status codes are
surfaced; bodies are not.

**Failures are distinguishable.** "Nobody connected an account", "the scope is
missing" and "Gmail rate-limited you" have different fixes, and collapsing them
sends the reader somewhere useless.
"""

from __future__ import annotations

import base64
import email
import email.policy
import json

import httpx
import pytest

from atlas_kernel.media.publishers.google_oauth import NotAuthorised, OAuthError
from atlas_kernel.opportunity.gmail import (
    GMAIL_SEND_SCOPE,
    GmailChannel,
    GmailSendError,
    build_mime,
    connected_channel,
)
from atlas_kernel.opportunity.models import OutreachMessage
from atlas_kernel.opportunity.outreach import OutreachChannel


class FakeCredentials:
    """Stands in for GoogleCredentials, which handles its own refresh.

    Not a mock of the refresh logic — that is tested where it lives. This is
    only a source of a token so the channel can be exercised.
    """

    def __init__(self, token: str = "an-access-token", *, connected: bool = True) -> None:
        self._token = token
        self.connected = connected
        self.calls = 0

    def access_token(self) -> str:
        self.calls += 1
        if not self.connected:
            raise NotAuthorised("not connected")
        return self._token


def _message(**overrides) -> OutreachMessage:
    payload = {
        "proposal_id": "p1",
        "business_id": "b1",
        "channel": "gmail",
        "recipient": "hello@alnoor.test",
        "subject": "Your site is hard to use on a phone",
        "body": "Hello Al Noor Dental Clinic,\n\nI looked at your site today.",
    }
    payload.update(overrides)
    return OutreachMessage(**payload)


def _channel(handler, **kwargs) -> tuple[GmailChannel, FakeCredentials]:
    credentials = FakeCredentials()
    channel = GmailChannel(
        credentials,  # type: ignore[arg-type]
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        **kwargs,
    )
    return channel, credentials


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"id": "18f0", "threadId": "18f0-thread"})


class TestItSatisfiesTheExistingProtocol:
    def test_it_is_an_outreach_channel(self) -> None:
        """The protocol M014 defined and left one implementation short."""
        channel, _ = _channel(_ok)
        assert isinstance(channel, OutreachChannel)

    def test_a_send_reports_the_provider_message_id(self) -> None:
        channel, _ = _channel(_ok)
        result = channel.deliver(_message())
        assert result.message_id == "18f0"
        assert "Gmail" in (result.detail or "")

    def test_it_asks_for_a_token_on_every_send(self) -> None:
        """So an expired credential refreshes rather than failing — the refresh
        lives in GoogleCredentials and must actually be consulted."""
        channel, credentials = _channel(_ok)
        channel.deliver(_message())
        channel.deliver(_message())
        assert credentials.calls == 2


class TestTheRequestIsShapedCorrectly:
    def test_it_authenticates_with_a_bearer_token(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _ok(request)

        channel, _ = _channel(handler)
        channel.deliver(_message())
        assert seen[0].headers["Authorization"] == "Bearer an-access-token"

    def test_it_posts_a_base64url_raw_message(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _ok(request)

        channel, _ = _channel(handler)
        channel.deliver(_message())

        payload = json.loads(seen[0].content)
        assert set(payload) == {"raw"}
        decoded = base64.urlsafe_b64decode(payload["raw"]).decode()
        assert "Your site is hard to use on a phone" in decoded
        assert "hello@alnoor.test" in decoded

    def test_the_encoding_is_url_safe_not_standard(self) -> None:
        """Gmail requires the URL-safe alphabet. The two differ in exactly two
        characters, so a message containing neither works and a message
        containing either fails — weeks later, at random."""
        raw = build_mime(_message(body="a" * 200 + "\n>>> ??? <<<\n" + "b" * 200))
        assert "+" not in raw and "/" not in raw
        assert base64.urlsafe_b64decode(raw)

    def test_the_sender_is_omitted_unless_configured(self) -> None:
        """Gmail sends as the authenticated account. A From it has not been
        configured for is ignored or rejected, so not setting one is honest."""
        raw = build_mime(_message())
        assert email.message_from_bytes(base64.urlsafe_b64decode(raw))["From"] is None

    def test_a_configured_sender_is_used(self) -> None:
        raw = build_mime(_message(), sender="ayoub@qevik.test")
        assert email.message_from_bytes(base64.urlsafe_b64decode(raw))["From"] == (
            "ayoub@qevik.test"
        )

    def test_the_body_survives_intact(self) -> None:
        body = "Hello,\n\n• A bullet\n• Another — with an em dash\n\nRegards"
        raw = build_mime(_message(body=body))
        # policy=default, or this returns a legacy Message and the modern
        # accessors are absent — which is a property of the parser here, not of
        # the message that was built.
        parsed = email.message_from_bytes(
            base64.urlsafe_b64decode(raw), policy=email.policy.default
        )
        assert body.strip() in parsed.get_content().strip()


class TestFailuresAreDistinguishable:
    def _fails_with(self, status: int, body: str = "") -> httpx.Response:
        return httpx.Response(status, text=body)

    def test_401_is_not_connected_rather_than_a_send_failure(self) -> None:
        """Retrying the send cannot fix a revoked credential."""
        channel, _ = _channel(lambda r: self._fails_with(401))
        with pytest.raises(NotAuthorised, match="Authorise Qevik again"):
            channel.deliver(_message())

    def test_403_names_the_causes_that_actually_produce_it(self) -> None:
        channel, _ = _channel(lambda r: self._fails_with(403))
        with pytest.raises(GmailSendError) as raised:
            channel.deliver(_message())
        message = str(raised.value)
        assert "Gmail API is not enabled" in message
        assert GMAIL_SEND_SCOPE in message
        assert "test user" in message

    def test_403_surfaces_googles_structured_reason(self) -> None:
        """The first real send failed exactly this way, and the two causes the
        message named were both wrong -- the scope was granted and the account
        was a test user. The real reason was sitting in a structured field the
        code was discarding."""
        body = {
            "error": {
                "status": "PERMISSION_DENIED",
                "message": "Gmail API has not been used in project 930669101081 before",
                "details": [
                    {
                        "reason": "SERVICE_DISABLED",
                        "metadata": {"activationUrl": "https://console.example/enable"},
                    }
                ],
            }
        }
        channel, _ = _channel(lambda r: httpx.Response(403, json=body))
        with pytest.raises(GmailSendError) as raised:
            channel.deliver(_message())
        message = str(raised.value)
        assert "PERMISSION_DENIED" in message
        assert "SERVICE_DISABLED" in message
        assert "https://console.example/enable" in message

    def test_the_free_text_message_is_still_never_surfaced(self) -> None:
        """Structured fields yes, free text no. Google echoes request content
        into error.message, which here is a real person's address."""
        body = {
            "error": {
                "status": "INVALID_ARGUMENT",
                "message": "Invalid To header: hello@alnoor.test says ...",
                "details": [{"reason": "BAD_REQUEST"}],
            }
        }
        channel, _ = _channel(lambda r: httpx.Response(400, json=body))
        with pytest.raises(GmailSendError) as raised:
            channel.deliver(_message())
        message = str(raised.value)
        assert "INVALID_ARGUMENT" in message and "BAD_REQUEST" in message
        assert "hello@alnoor.test" not in message
        assert "Invalid To header" not in message

    def test_a_body_that_is_not_json_does_not_crash_the_error_path(self) -> None:
        """An error while building an error message is the worst kind."""
        channel, _ = _channel(lambda r: httpx.Response(502, text="<html>gateway</html>"))
        with pytest.raises(GmailSendError, match="502"):
            channel.deliver(_message())

    def test_429_says_to_back_off(self) -> None:
        channel, _ = _channel(lambda r: self._fails_with(429))
        with pytest.raises(GmailSendError, match="rate-limited"):
            channel.deliver(_message())

    def test_a_transport_failure_is_reported_as_one(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route to host")

        channel, _ = _channel(handler)
        with pytest.raises(GmailSendError, match="could not reach Gmail"):
            channel.deliver(_message())


class TestNothingSecretLeaks:
    def test_an_error_never_carries_googles_response_body(self) -> None:
        """Google's error body can echo the request — which here is the message
        being sent, to a real person, on their real address."""
        echoed = "the recipient was hello@alnoor.test and the body said ..."
        channel, _ = _channel(lambda r: httpx.Response(400, text=echoed))
        with pytest.raises(GmailSendError) as raised:
            channel.deliver(_message())
        assert "hello@alnoor.test" not in str(raised.value)
        assert "400" in str(raised.value)

    def test_an_error_never_carries_the_access_token(self) -> None:
        channel, _ = _channel(lambda r: httpx.Response(500, text="an-access-token leaked here"))
        with pytest.raises(GmailSendError) as raised:
            channel.deliver(_message())
        assert "an-access-token" not in str(raised.value)


class TestConstructionFailsEarly:
    def test_an_unconnected_account_fails_before_a_batch_starts(self) -> None:
        """Discovering nothing is connected while approved proposals are going
        out is strictly worse than discovering it now."""
        with pytest.raises(OAuthError, match="connect_google.py"):
            connected_channel(FakeCredentials(connected=False))  # type: ignore[arg-type]

    def test_a_connected_account_produces_a_channel(self) -> None:
        channel = connected_channel(FakeCredentials())  # type: ignore[arg-type]
        assert channel.name == "gmail"


class TestScope:
    def test_it_is_send_only(self) -> None:
        """A credential that can read a mailbox is a different thing to hold
        than one that can only add to it."""
        assert GMAIL_SEND_SCOPE.endswith("/gmail.send")
        assert "readonly" not in GMAIL_SEND_SCOPE
        assert "modify" not in GMAIL_SEND_SCOPE

"""The YouTube publisher (M013 step 7).

**None of this has run against the real API.** No Google Cloud project or
channel exists yet, so every test here drives a fake that mimics the documented
responses — including the awkward ones: 308 with a short Range, a 5xx mid-file,
an expired token.

That is worth being honest about. These tests prove the code does what the
documentation says YouTube does. They cannot prove the documentation is right,
and the step is not finished until something has actually been uploaded.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from atlas_kernel.media.models import Visibility
from atlas_kernel.media.publishers.google_oauth import (
    ClientSecrets,
    DesktopAuthFlow,
    GoogleCredentials,
    NotAuthorised,
    OAuthError,
    Token,
    TokenStore,
)
from atlas_kernel.media.publishers.youtube import YouTubeError, YouTubePublisher
from atlas_kernel.media.publishing import (
    PublicVisibilityRefused,
    Publisher,
    PublishRequest,
)

SECRETS = ClientSecrets(client_id="client-id", client_secret="client-secret")


# -- a fake YouTube -------------------------------------------------------


class FakeYouTube:
    """The documented behaviour, including the parts that are easy to get wrong."""

    def __init__(
        self,
        *,
        chunk_acknowledgement: int | None = None,
        fail_times: int = 0,
        fail_status: int = 503,
        privacy: str = "private",
        video_id: str = "abc123XYZ",
    ) -> None:
        self.received = bytearray()
        self.chunk_acknowledgement = chunk_acknowledgement
        self.fail_times = fail_times
        self.fail_status = fail_status
        self.privacy = privacy
        self.video_id = video_id
        self.snippet: dict = {}
        self.status: dict = {}
        self.captions_uploaded = False
        self.session_opened = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        if url.startswith("https://www.googleapis.com/upload/youtube/v3/videos"):
            payload = json.loads(request.content)
            self.snippet = payload["snippet"]
            self.status = payload["status"]
            self.session_opened += 1
            return httpx.Response(200, headers={"location": "https://upload.example/session/1"})

        if url.startswith("https://upload.example/session/"):
            return self._upload(request)

        if url.startswith("https://www.googleapis.com/upload/youtube/v3/captions"):
            self.captions_uploaded = True
            return httpx.Response(200, json={"id": "caption-1"})

        if url.startswith("https://www.googleapis.com/youtube/v3/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": self.video_id,
                            "status": {
                                "privacyStatus": self.privacy,
                                "uploadStatus": "uploaded",
                            },
                            "processingDetails": {"processingStatus": "processing"},
                        }
                    ]
                },
            )

        return httpx.Response(404, json={"error": {"message": f"unexpected {url}"}})

    def _upload(self, request: httpx.Request) -> httpx.Response:
        content_range = request.headers.get("Content-Range", "")

        # "bytes */total" is a status query, not data.
        if content_range.startswith("bytes */"):
            return httpx.Response(308, headers=self._range_header())

        if self.fail_times > 0:
            self.fail_times -= 1
            return httpx.Response(self.fail_status, text="try again")

        start = int(content_range.split(" ")[1].split("-")[0])
        total = int(content_range.split("/")[1])
        body = request.content

        # Only accept what follows what we already have.
        if start != len(self.received):
            return httpx.Response(308, headers=self._range_header())

        # Optionally acknowledge less than was sent, which the API is allowed
        # to do and which a client that counts locally will get wrong.
        accepted = (
            body if self.chunk_acknowledgement is None else body[: self.chunk_acknowledgement]
        )
        self.received.extend(accepted)

        if len(self.received) >= total:
            return httpx.Response(200, json={"id": self.video_id, "snippet": self.snippet})
        return httpx.Response(308, headers=self._range_header())

    def _range_header(self) -> dict[str, str]:
        """YouTube omits Range entirely when it has received nothing.

        The fake said "bytes=0--1" instead, which is not a response the API can
        produce -- and modelling it wrongly hid a real livelock in the client.
        """
        if not self.received:
            return {}
        return {"range": f"bytes=0-{len(self.received) - 1}"}


def _client(fake: FakeYouTube) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake.handler))


def _publisher(credentials, fake: FakeYouTube, **kwargs) -> YouTubePublisher:
    """A publisher whose backoff does not actually sleep.

    The retry logic is what is under test, not the wall clock. Real backoff
    would add half a minute to the suite and prove nothing extra.
    """
    kwargs.setdefault("chunk_bytes", 16_384)
    return YouTubePublisher(
        credentials, client=_client(fake), backoff=lambda _seconds: None, **kwargs
    )


@pytest.fixture
def credentials(tmp_path: Path) -> GoogleCredentials:
    store = TokenStore(tmp_path / "token.json")
    store.save(
        Token(
            access_token="live-token",
            refresh_token="refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    return GoogleCredentials(DesktopAuthFlow(SECRETS), store)


@pytest.fixture
def video(tmp_path: Path) -> Path:
    path = tmp_path / "final.mp4"
    path.write_bytes(b"x" * 40_000)
    return path


# -- the happy path -------------------------------------------------------


def test_a_video_is_uploaded_and_confirmed(credentials, video: Path) -> None:
    fake = FakeYouTube()
    publisher = _publisher(credentials, fake)

    receipt = publisher.publish(
        PublishRequest(
            media_path=video,
            title="Explaining the Atlas kernel",
            description="A short explainer.",
            tags=["atlas"],
            visibility=Visibility.PRIVATE,
        )
    )

    assert receipt.remote_id == "abc123XYZ"
    assert receipt.remote_url == "https://www.youtube.com/watch?v=abc123XYZ"
    assert receipt.visibility is Visibility.PRIVATE
    assert bytes(fake.received) == video.read_bytes(), "the file did not arrive intact"
    assert fake.snippet["title"] == "Explaining the Atlas kernel"
    assert fake.status["privacyStatus"] == "private"


def test_the_publisher_satisfies_the_protocol(credentials) -> None:
    """YouTube must be substitutable for any later platform, or the abstraction
    is decoration."""
    assert isinstance(YouTubePublisher(credentials), Publisher)
    assert YouTubePublisher(credentials).platform == "youtube"


def test_captions_are_uploaded_when_present(credentials, video: Path, tmp_path: Path) -> None:
    captions = tmp_path / "final.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello.\n")

    fake = FakeYouTube()
    YouTubePublisher(credentials, client=_client(fake)).publish(
        PublishRequest(media_path=video, title="x", captions_path=captions)
    )
    assert fake.captions_uploaded is True


def test_a_caption_failure_does_not_fail_the_publish(
    credentials, video: Path, tmp_path: Path
) -> None:
    """The video is up. Reporting the publish as failed would leave an uploaded
    video Atlas believes does not exist -- the worse of the two states."""
    captions = tmp_path / "final.srt"
    captions.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi.\n")

    class CaptionsBroken(FakeYouTube):
        def handler(self, request: httpx.Request) -> httpx.Response:
            if "captions" in str(request.url):
                return httpx.Response(403, json={"error": {"message": "no"}})
            return super().handler(request)

    fake = CaptionsBroken()
    receipt = YouTubePublisher(credentials, client=_client(fake)).publish(
        PublishRequest(media_path=video, title="x", captions_path=captions)
    )
    assert receipt.remote_id == "abc123XYZ"


def test_metadata_is_trimmed_to_what_youtube_accepts(credentials, video: Path) -> None:
    """So the video is titled what Atlas intended rather than whatever survived
    the platform's truncation."""
    fake = FakeYouTube()
    YouTubePublisher(credentials, client=_client(fake)).publish(
        PublishRequest(media_path=video, title="T" * 300, description="D" * 9000)
    )
    assert len(fake.snippet["title"]) == 100
    assert len(fake.snippet["description"]) == 5000


# -- resumption -----------------------------------------------------------


def test_a_partially_acknowledged_chunk_resumes_correctly(credentials, video: Path) -> None:
    """YouTube may accept less than was sent. A client that counts locally
    corrupts the upload; the offset must come from the Range header."""
    fake = FakeYouTube(chunk_acknowledgement=5_000)
    _publisher(credentials, fake).publish(PublishRequest(media_path=video, title="x"))
    assert bytes(fake.received) == video.read_bytes()


def test_a_server_error_mid_upload_is_retried(credentials, video: Path) -> None:
    fake = FakeYouTube(fail_times=2)
    _publisher(credentials, fake).publish(PublishRequest(media_path=video, title="x"))
    assert bytes(fake.received) == video.read_bytes()


def test_persistent_server_errors_eventually_give_up(credentials, video: Path) -> None:
    fake = FakeYouTube(fail_times=999)
    with pytest.raises(YouTubeError, match="503"):
        _publisher(credentials, fake).publish(PublishRequest(media_path=video, title="x"))


def test_a_server_that_never_advances_is_given_up_on(credentials, video: Path) -> None:
    """The livelock this caught.

    A 308 that keeps asking for a range already sent means retrying cannot
    help. Resetting the attempt counter on every 308 -- which is correct when
    progress is being made -- spun here forever. An upload that hangs with no
    diagnosis is worse than one that fails with a reason.
    """

    class NeverAdvances(FakeYouTube):
        def _upload(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(308, headers={"range": "bytes=0-99"})

    with pytest.raises(YouTubeError, match="kept asking for the same range"):
        _publisher(credentials, NeverAdvances()).publish(
            PublishRequest(media_path=video, title="x")
        )


def test_a_missing_range_header_means_nothing_arrived(credentials, video: Path) -> None:
    """YouTube omits Range when it has received nothing. That means zero, not
    "keep whatever offset you had"."""
    assert YouTubePublisher._offset_from_range(None, 0) == 0
    assert YouTubePublisher._offset_from_range("", 0) == 0


def test_a_malformed_range_is_not_believed() -> None:
    """A negative or partial range splits into pieces whose last element is a
    plausible number, and resuming from it would corrupt the upload."""
    assert YouTubePublisher._offset_from_range("bytes=0--1", 77) == 77
    assert YouTubePublisher._offset_from_range("bytes=500-999", 0) == 0


def test_a_range_header_offset_is_read_as_inclusive() -> None:
    """ "bytes=0-262143" means 262144 bytes arrived, so the next wanted byte is
    262144. Off by one here silently corrupts every resumed upload."""
    assert YouTubePublisher._offset_from_range("bytes=0-262143", 0) == 262144
    assert YouTubePublisher._offset_from_range(None, 77) == 77
    assert YouTubePublisher._offset_from_range("nonsense", 77) == 77


# -- refusals -------------------------------------------------------------


def test_public_is_refused_before_anything_happens(credentials, video: Path) -> None:
    """Before a token is fetched or a byte is read, so a mistake costs
    nothing."""
    fake = FakeYouTube()
    with pytest.raises(PublicVisibilityRefused):
        YouTubePublisher(credentials, client=_client(fake)).publish(
            PublishRequest(media_path=video, title="x", visibility=Visibility.PUBLIC)
        )
    assert fake.session_opened == 0


def test_a_channel_that_publishes_publicly_is_caught(credentials, video: Path) -> None:
    """Atlas never asks for public, but a channel default could still make it
    so. The receipt is read back, and this is refused rather than reported as
    a success."""
    fake = FakeYouTube(privacy="public")
    with pytest.raises(YouTubeError, match="is public on YouTube"):
        YouTubePublisher(credentials, client=_client(fake)).publish(
            PublishRequest(media_path=video, title="x")
        )


def test_a_missing_file_fails_before_the_network(credentials, tmp_path: Path) -> None:
    fake = FakeYouTube()
    with pytest.raises(YouTubeError, match="nothing to publish"):
        YouTubePublisher(credentials, client=_client(fake)).publish(
            PublishRequest(media_path=tmp_path / "gone.mp4", title="x")
        )
    assert fake.session_opened == 0


def test_an_unconnected_account_says_so(tmp_path: Path, video: Path) -> None:
    """ "Not connected" and "upload failed" are different problems with
    different fixes."""
    credentials = GoogleCredentials(DesktopAuthFlow(SECRETS), TokenStore(tmp_path / "absent.json"))
    with pytest.raises(YouTubeError, match="not connected"):
        YouTubePublisher(credentials).publish(PublishRequest(media_path=video, title="x"))


def test_quota_errors_explain_themselves(credentials, video: Path) -> None:
    """A 403 from YouTube is usually quota, and saying so saves an hour reading
    the wrong documentation."""

    class OverQuota(FakeYouTube):
        def handler(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                403,
                json={
                    "error": {
                        "message": "The request cannot be completed because you have "
                        "exceeded your quota.",
                        "errors": [{"reason": "quotaExceeded"}],
                    }
                },
            )

    with pytest.raises(YouTubeError, match="quota limit"):
        YouTubePublisher(credentials, client=_client(OverQuota())).publish(
            PublishRequest(media_path=video, title="x")
        )


def test_an_expired_authorisation_explains_the_fix(credentials, video: Path) -> None:
    class Unauthorised(FakeYouTube):
        def handler(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": {"message": "Invalid Credentials"}})

    with pytest.raises(YouTubeError, match="connect the channel again"):
        YouTubePublisher(credentials, client=_client(Unauthorised())).publish(
            PublishRequest(media_path=video, title="x")
        )


# -- OAuth ----------------------------------------------------------------


def test_only_desktop_client_secrets_are_accepted(tmp_path: Path) -> None:
    """A web client would parse and then fail at the redirect, with a message
    that sends the reader somewhere unhelpful."""
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"web": {"client_id": "x", "client_secret": "y"}}))

    with pytest.raises(OAuthError, match="Desktop app"):
        ClientSecrets.from_file(path)


def test_desktop_client_secrets_load(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"installed": {"client_id": "abc", "client_secret": "shh"}}))
    assert ClientSecrets.from_file(path).client_id == "abc"


def test_the_authorisation_url_carries_pkce_and_offline_access() -> None:
    """Without access_type and prompt, Google returns no refresh token on a
    repeat authorisation -- Atlas would work today and stop working tomorrow."""
    url = DesktopAuthFlow(SECRETS).authorisation_url(
        "http://127.0.0.1:9999", "challenge-value", "state-value"
    )
    for expected in (
        "code_challenge=challenge-value",
        "code_challenge_method=S256",
        "state=state-value",
        "access_type=offline",
        "prompt=consent",
        "youtube.upload",
    ):
        assert expected in url


def test_an_exchange_without_a_refresh_token_is_refused() -> None:
    """Atlas would lose access the moment the access token expired, and would
    not find out until an upload failed weeks later."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "a", "expires_in": 3600})

    flow = DesktopAuthFlow(SECRETS, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(OAuthError, match="did not return a refresh token"):
        flow.exchange("code", "http://127.0.0.1:1", "verifier")


def test_a_refresh_keeps_the_refresh_token() -> None:
    """A refresh response does not repeat it, and dropping it turns a long-lived
    connection into a single-use one."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "new", "expires_in": 3600})

    flow = DesktopAuthFlow(SECRETS, client=httpx.Client(transport=httpx.MockTransport(handler)))
    token = flow.refresh("the-refresh-token")
    assert token.access_token == "new"
    assert token.refresh_token == "the-refresh-token"


def test_an_expiring_token_is_refreshed_automatically(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"access_token": "refreshed", "expires_in": 3600})

    store = TokenStore(tmp_path / "token.json")
    store.save(
        Token(
            access_token="stale",
            refresh_token="r",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    flow = DesktopAuthFlow(SECRETS, client=httpx.Client(transport=httpx.MockTransport(handler)))

    assert GoogleCredentials(flow, store).access_token() == "refreshed"
    # And it was written back, so the next call does not refresh again.
    assert store.load().access_token == "refreshed"


def test_a_token_about_to_expire_counts_as_expired(tmp_path: Path) -> None:
    """A token that dies mid-upload fails the whole upload."""
    soon = Token(access_token="a", expires_at=datetime.now(UTC) + timedelta(seconds=30))
    assert soon.expired is True
    healthy = Token(access_token="a", expires_at=datetime.now(UTC) + timedelta(hours=1))
    assert healthy.expired is False


def test_tokens_are_written_readable_only_by_their_owner(tmp_path: Path) -> None:
    """Anything that can read this file can act as this user on the channel."""
    path = tmp_path / "token.json"
    TokenStore(path).save(Token(access_token="secret", refresh_token="r"))
    assert path.stat().st_mode & 0o077 == 0, "the token file is readable by others"


def test_a_corrupt_token_file_is_not_a_crash(tmp_path: Path) -> None:
    """Re-authorising is the fix, and saying so beats a stack trace about JSON."""
    path = tmp_path / "token.json"
    path.write_text("{ not json")
    assert TokenStore(path).load() is None

    with pytest.raises(NotAuthorised):
        GoogleCredentials(DesktopAuthFlow(SECRETS), TokenStore(path)).access_token()


def test_credentials_report_whether_a_channel_is_connected(tmp_path: Path) -> None:
    store = TokenStore(tmp_path / "token.json")
    credentials = GoogleCredentials(DesktopAuthFlow(SECRETS), store)
    assert credentials.connected is False

    store.save(Token(access_token="a", refresh_token="r"))
    assert credentials.connected is True

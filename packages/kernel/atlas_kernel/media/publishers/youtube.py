"""Uploading to YouTube, via the Data API v3.

Implements ``media.publishing.Publisher`` and nothing else. Everything above it
-- the approval gate, the dependency graph, the assembler -- is unaware this
file exists, which is what makes the next platform a new module rather than a
change to the workflow.

Written against the documented REST contract with ``httpx`` rather than the
Google client library: see ``google_oauth`` for why. The resumable protocol is
implemented here because it is the part that carries a 140 MB file over a
consumer connection, and it has to survive an interruption.

**This has never run against the real API.** No Google Cloud project or channel
exists yet. It is written to the contract, exercised against a fake that mimics
the documented responses, and is not finished until it has uploaded something.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ..models import Visibility
from ..publishing import PublishError, PublishReceipt, PublishRequest, assert_not_public
from .google_oauth import GoogleCredentials, NotAuthorised

UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
CAPTIONS_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/captions"
VIDEOS_ENDPOINT = "https://www.googleapis.com/youtube/v3/videos"

#: 8 MiB. A multiple of 256 KiB as the API requires, and large enough that a
#: long video is not thousands of round trips.
CHUNK_BYTES = 8 * 1024 * 1024

#: Google returns 308 while it wants more, and 5xx for its own trouble. Only
#: the latter is worth retrying.
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
MAX_ATTEMPTS = 5


class YouTubeError(PublishError):
    """YouTube rejected something, with whatever it said attached."""


class YouTubePublisher:
    """Publishes a finished video to a YouTube channel."""

    platform = "youtube"

    def __init__(
        self,
        credentials: GoogleCredentials,
        *,
        client: httpx.Client | None = None,
        chunk_bytes: int = CHUNK_BYTES,
        category_id: str = "27",  # Education. Overridable per request.
        made_for_kids: bool = False,
        verify_processing: bool = True,
        backoff: Callable[[float], None] = time.sleep,
    ) -> None:
        self.credentials = credentials
        self._client = client
        self.chunk_bytes = chunk_bytes
        self.category_id = category_id
        self.made_for_kids = made_for_kids
        self.verify_processing = verify_processing
        #: Injectable so tests exercise the retry logic without waiting out the
        #: real backoff. Production always uses time.sleep.
        self._backoff = backoff

    # -- the protocol -----------------------------------------------------

    def publish(self, request: PublishRequest) -> PublishReceipt:
        # First, before a token is fetched or a byte is read. Refusing early
        # means a mistake costs nothing.
        assert_not_public(request.visibility)

        if not request.media_path.exists():
            raise YouTubeError(f"nothing to publish at {request.media_path}")

        token = self._token()
        client = self._client or httpx.Client(timeout=120)
        try:
            session_url = self._begin(client, token, request)
            video = self._upload(client, token, session_url, request.media_path)
            video_id = video.get("id")
            if not video_id:
                raise YouTubeError(f"YouTube accepted the upload but returned no id: {video}")

            if request.captions_path and request.captions_path.exists():
                # Not fatal. A published video without captions is a video;
                # failing the publish for it would leave an uploaded private
                # video that Atlas believes does not exist.
                self._captions(client, token, video_id, request.captions_path)

            status = self._verify(client, token, video_id) if self.verify_processing else {}
            actual = self._visibility_of(status) or request.visibility
            if actual is Visibility.PUBLIC:
                raise YouTubeError(
                    f"video {video_id} is public on YouTube, which Atlas never requests. "
                    "Check the channel's default visibility and make it private."
                )

            return PublishReceipt(
                remote_id=video_id,
                remote_url=f"https://www.youtube.com/watch?v={video_id}",
                visibility=actual,
                raw={"video": video, "status": status},
            )
        finally:
            if self._client is None:
                client.close()

    # -- the steps --------------------------------------------------------

    def _token(self) -> str:
        try:
            return self.credentials.access_token()
        except NotAuthorised as error:
            raise YouTubeError(str(error)) from error

    def _begin(self, client: httpx.Client, token: str, request: PublishRequest) -> str:
        """Open a resumable session and return the URL to send bytes to."""
        size = request.media_path.stat().st_size
        body = {
            "snippet": {
                # YouTube truncates at 100 characters and 5000 respectively.
                # Trimming here means the video is titled what Atlas intended
                # rather than whatever survived.
                "title": (request.title or "Untitled")[:100],
                "description": request.description[:5000],
                "tags": request.tags[:500],
                "categoryId": request.metadata.get("category_id", self.category_id),
            },
            "status": {
                "privacyStatus": request.visibility.value,
                "selfDeclaredMadeForKids": self.made_for_kids,
                "embeddable": True,
            },
        }

        response = self._request(
            client,
            "POST",
            UPLOAD_ENDPOINT,
            token=token,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/*",
            },
            content=json.dumps(body).encode("utf-8"),
        )
        session_url = response.headers.get("location")
        if not session_url:
            raise YouTubeError(
                "YouTube did not return an upload session URL. "
                f"Status {response.status_code}: {response.text[:400]}"
            )
        return session_url

    def _upload(
        self, client: httpx.Client, token: str, session_url: str, path: Path
    ) -> dict[str, Any]:
        """Send the file in chunks, resuming where YouTube says it got to.

        The offset comes from YouTube's ``Range`` header rather than from a
        local count. After an interruption those two disagree, and trusting the
        local one silently corrupts the upload.
        """
        size = path.stat().st_size
        offset = 0
        attempts = 0
        #: 308s that ask for a range we have already sent. Counted separately
        #: from transport failures because the remedy is different: retrying
        #: cannot help, so it has to stop.
        stalls = 0

        with path.open("rb") as handle:
            while offset < size:
                handle.seek(offset)
                chunk = handle.read(self.chunk_bytes)
                last = offset + len(chunk) - 1

                try:
                    response = client.put(
                        session_url,
                        content=chunk,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{last}/{size}",
                        },
                    )
                except httpx.HTTPError as error:
                    attempts += 1
                    if attempts >= MAX_ATTEMPTS:
                        raise YouTubeError(
                            f"upload failed after {attempts} attempts: {error}"
                        ) from error
                    self._backoff(min(2**attempts, 30))
                    offset = self._resume_offset(client, token, session_url, size, offset)
                    continue

                if response.status_code in (200, 201):
                    return dict(response.json())

                if response.status_code == 308:
                    advanced = self._offset_from_range(
                        response.headers.get("range"), offset + len(chunk)
                    )
                    if advanced <= offset:
                        # A 308 that does not move forward means we would send
                        # the same bytes again, and resetting `attempts` on it
                        # would spin here forever. An upload that hangs with no
                        # diagnosis is worse than one that fails with a reason.
                        stalls += 1
                        if stalls >= MAX_ATTEMPTS:
                            raise YouTubeError(
                                f"YouTube stopped accepting data at byte {offset} of "
                                f"{size} and kept asking for the same range. Giving up "
                                f"after {stalls} attempts rather than retrying forever."
                            )
                        self._backoff(min(2**stalls, 30))
                    else:
                        stalls = 0
                        attempts = 0
                    offset = max(advanced, offset)
                    continue

                if response.status_code in RETRYABLE_STATUS:
                    attempts += 1
                    if attempts >= MAX_ATTEMPTS:
                        raise YouTubeError(
                            f"YouTube returned {response.status_code} {attempts} times: "
                            f"{response.text[:400]}"
                        )
                    self._backoff(min(2**attempts, 30))
                    offset = self._resume_offset(client, token, session_url, size, offset)
                    continue

                raise YouTubeError(
                    f"upload rejected ({response.status_code}): {response.text[:400]}"
                )

        raise YouTubeError("the upload finished without YouTube confirming the video")

    def _resume_offset(
        self, client: httpx.Client, token: str, session_url: str, size: int, fallback: int
    ) -> int:
        """Ask YouTube how much it actually has."""
        try:
            response = client.put(
                session_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Length": "0",
                    "Content-Range": f"bytes */{size}",
                },
            )
        except httpx.HTTPError:
            return fallback
        if response.status_code in (200, 201):
            return size
        return self._offset_from_range(response.headers.get("range"), fallback)

    @staticmethod
    def _offset_from_range(header: str | None, fallback: int) -> int:
        """Next byte wanted, from a ``Range`` header.

        "bytes=0-262143" means everything up to and including 262143 arrived,
        so the next byte wanted is 262144.

        Parsed with a pattern rather than by splitting on "-": a malformed or
        negative range splits into pieces whose last element is a plausible
        number, and believing it would resume from the wrong place. YouTube
        also omits the header entirely when it has received nothing, which
        means zero, not "keep whatever you had".
        """
        if not header:
            return fallback
        match = re.search(r"(\d+)\s*-\s*(\d+)", header)
        if not match:
            return fallback
        first, last = int(match.group(1)), int(match.group(2))
        if first != 0:
            # A non-zero start would mean YouTube has a hole, which the
            # resumable protocol does not produce. Do not guess.
            return fallback
        return last + 1

    def _captions(self, client: httpx.Client, token: str, video_id: str, captions: Path) -> None:
        metadata = {
            "snippet": {"videoId": video_id, "language": "en", "name": "Atlas", "isDraft": False}
        }
        boundary = "atlas-caption-boundary"
        body = b"".join(
            [
                f"--{boundary}\r\n".encode(),
                b"Content-Type: application/json; charset=UTF-8\r\n\r\n",
                json.dumps(metadata).encode("utf-8"),
                f"\r\n--{boundary}\r\n".encode(),
                b"Content-Type: application/octet-stream\r\n\r\n",
                captions.read_bytes(),
                f"\r\n--{boundary}--\r\n".encode(),
            ]
        )
        try:
            self._request(
                client,
                "POST",
                CAPTIONS_ENDPOINT,
                token=token,
                params={"uploadType": "multipart", "part": "snippet"},
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                content=body,
            )
        except YouTubeError:
            # Deliberately swallowed. The video is up; captions can be added
            # afterwards. Failing here would leave an uploaded video that Atlas
            # reports as unpublished, which is the worse of the two states.
            return

    def _verify(self, client: httpx.Client, token: str, video_id: str) -> dict[str, Any]:
        """Read the video back, so the receipt reflects YouTube rather than hope."""
        response = self._request(
            client,
            "GET",
            VIDEOS_ENDPOINT,
            token=token,
            params={"part": "status,processingDetails", "id": video_id},
        )
        items = response.json().get("items") or []
        return dict(items[0]) if items else {}

    @staticmethod
    def _visibility_of(status: dict[str, Any]) -> Visibility | None:
        privacy = (status.get("status") or {}).get("privacyStatus")
        if not privacy:
            return None
        try:
            return Visibility(privacy)
        except ValueError:
            return None

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        token: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        merged = {"Authorization": f"Bearer {token}", **(headers or {})}
        try:
            response = client.request(method, url, params=params, headers=merged, content=content)
        except httpx.HTTPError as error:
            raise YouTubeError(f"could not reach YouTube: {error}") from error

        if response.status_code >= 400:
            raise YouTubeError(self._explain(response))
        return response

    @staticmethod
    def _explain(response: httpx.Response) -> str:
        """Turn an API error into something worth reading.

        The generic message is nearly always the wrong thing to act on: a 403
        from YouTube is usually quota or an unverified channel, and saying so
        saves an hour of reading the wrong documentation.
        """
        try:
            error = response.json().get("error", {})
            detail = error.get("message") or response.text[:300]
            reason = (error.get("errors") or [{}])[0].get("reason", "")
        except (json.JSONDecodeError, ValueError):
            detail, reason = response.text[:300], ""

        hint = ""
        if response.status_code == 401:
            hint = " Atlas's authorisation is no longer valid; connect the channel again."
        elif response.status_code == 403:
            if "quota" in f"{reason}{detail}".lower():
                hint = (
                    " This is a quota limit. An upload costs about 1600 units of a "
                    "default 10,000 per day, so roughly six a day without an increase."
                )
            else:
                hint = (
                    " Check that the YouTube Data API v3 is enabled for the project and "
                    "that the channel is verified for uploads."
                )
        return f"YouTube returned {response.status_code} ({reason or 'error'}): {detail}.{hint}"

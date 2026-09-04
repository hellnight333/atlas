"""A real provider: one token, many models.

The media stack has had a complete assembly, provenance and publish chain and a
mock at the bottom of it since it was written. Everything downstream of the
provider boundary is production code running on production bytes; the one thing
missing was a provider that generates.

This is that provider, and it is deliberately **not** an integration with one
model. Replicate exposes hundreds — Flux for stills, Wan and Kling and Hailuo
for video, SDXL, upscalers — behind a single asynchronous job API with the same
three moments the `LongRunningProvider` protocol already has: start, ask, collect.
So one adapter, one credential, and the choice of model stays where it belongs:
in a recipe, versioned in git, not in code.

## What this adapter refuses to do

**It does not choose a model.** `recipe.parameters["model"]` says which version
runs, because a recipe is a reviewed artefact and an adapter improvising a model
is how output quality changes without a commit. A request with no model named is
a `ProviderError`, not a default.

**It does not invent progress.** Replicate reports a status and, for some
models, logs; it does not report a fraction. `progress` stays `None` rather than
becoming a number that moves at a rate nobody chose. A made-up progress bar is
worse than an honest spinner because it is believed.

**It does not hold the artefact in memory.** `fetch` streams to the destination
path, because a 1080p clip has no business being a Python bytes object on its
way to disk.

**It does not retry on its own.** A failed render is the caller's decision —
the same render costs money every time it runs, and an adapter that quietly
tries three times is an adapter that quietly triples a bill.

## Cost is reported, never estimated

`poll` carries whatever the API says about timing into `metadata`, and the
registration carries the price. Nothing here multiplies a guess by a duration
and calls the product a cost.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .base import JobState, ProviderError, ProviderJobStatus, RenderRequest

#: Where the API lives. Overridable for a proxy or a test double, never for a
#: different vendor: a different vendor is a different adapter.
API_BASE = os.environ.get("QEVIK_REPLICATE_API", "https://api.replicate.com/v1")

#: The credential. Registered in `integrations.registry` so an unset token is a
#: named, visible state rather than a stack trace at the first render.
TOKEN_VARIABLE = "QEVIK_REPLICATE_API_TOKEN"

#: How long a single HTTP call may take. Submission and polling are both small
#: JSON round trips; a minute is already generous and an unbounded socket is how
#: a worker thread disappears.
HTTP_TIMEOUT_SECONDS = 60.0

#: Replicate's own status vocabulary, mapped to ours. Anything unrecognised is
#: treated as running rather than as success — a provider that invents a
#: terminal state is how a half-finished render gets published.
_STATES = {
    "starting": JobState.QUEUED,
    "processing": JobState.RUNNING,
    "succeeded": JobState.SUCCEEDED,
    "failed": JobState.FAILED,
    "canceled": JobState.FAILED,
}


class ReplicateProvider:
    """Submit, poll and fetch against Replicate's predictions API."""

    name = "replicate"

    def __init__(self, token: str | None = None, *, api_base: str | None = None,
                 opener: Any | None = None) -> None:
        self._token = token or os.environ.get(TOKEN_VARIABLE, "")
        self._api = (api_base or API_BASE).rstrip("/")
        # Injected for tests. Production passes nothing and gets urllib, so the
        # test double cannot drift from the real call shape: both go through
        # `_request` below.
        self._opener = opener or urllib.request.urlopen

    # --- the protocol ---------------------------------------------------------

    def submit(self, request: RenderRequest) -> str:
        """Start a prediction. Returns Replicate's id, which is our handle."""
        model = request.parameters.get("model")
        if not model:
            raise ProviderError(
                f"recipe {request.recipe_id!r} does not name a model. The recipe "
                "decides which model runs, not the adapter — add `model:` to its "
                "parameters rather than relying on a default that nobody reviewed.")

        # The prompt and the shape of the output are the caller's; everything
        # else in `parameters` is passed through untouched so a recipe can reach
        # a model-specific input without this file learning about that model.
        passthrough = {k: v for k, v in request.parameters.items()
                       if k not in {"model", "version"}}
        payload: dict[str, Any] = {
            "input": {
                "prompt": request.prompt,
                **passthrough,
            }
        }
        version = request.parameters.get("version")
        if version:
            payload["version"] = version
            endpoint = f"{self._api}/predictions"
        else:
            # The owner/name form, which pins to a model's current version.
            endpoint = f"{self._api}/models/{model}/predictions"

        body = self._request("POST", endpoint, payload)
        handle = body.get("id")
        if not handle:
            raise ProviderError(f"Replicate accepted the request without an id: {body!r}")
        return str(handle)

    def poll(self, handle: str) -> ProviderJobStatus:
        body = self._request("GET", f"{self._api}/predictions/{handle}")
        raw = str(body.get("status", ""))
        state = _STATES.get(raw, JobState.RUNNING)

        detail = None
        if state is JobState.FAILED:
            # The provider's own words. A generic "render failed" here would
            # throw away the one sentence that says whether this is a bad prompt,
            # a missing model, or an account out of credit.
            detail = str(body.get("error") or raw or "the provider reported a failure")

        metrics = body.get("metrics") or {}
        return ProviderJobStatus(
            handle=handle,
            state=state,
            # Deliberately absent: Replicate reports no fraction, and inventing
            # one is worse than showing none.
            progress=None,
            detail=detail,
            metadata={
                "raw_status": raw,
                "model": body.get("model", ""),
                # Reported, not estimated. Present only when the API says so.
                **({"predict_time_seconds": metrics["predict_time"]}
                   if "predict_time" in metrics else {}),
                **({"output_url": _first_output(body)} if body.get("output") else {}),
            },
        )

    def fetch(self, handle: str, destination: Path) -> Path:
        """Stream the finished artefact to `destination`."""
        body = self._request("GET", f"{self._api}/predictions/{handle}")
        raw = str(body.get("status", ""))
        if _STATES.get(raw, JobState.RUNNING) is not JobState.SUCCEEDED:
            raise ProviderError(
                f"prediction {handle} is {raw!r}, so there is nothing to fetch. "
                "Poll until it succeeds; a partial render is not an artefact.")

        url = _first_output(body)
        if not url:
            raise ProviderError(
                f"prediction {handle} succeeded with no output URL: {body.get('output')!r}")

        destination.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "qevik/1.0"})
        try:
            with self._opener(request, timeout=HTTP_TIMEOUT_SECONDS) as response, \
                    destination.open("wb") as sink:
                # Streamed in chunks: a 1080p clip does not become a bytes object
                # on its way to a file.
                while chunk := response.read(1 << 16):
                    sink.write(chunk)
        except urllib.error.URLError as error:
            raise ProviderError(f"could not download {handle}: {error}") from error

        if destination.stat().st_size == 0:
            destination.unlink(missing_ok=True)
            raise ProviderError(f"prediction {handle} produced an empty file")
        return destination

    # --- one place that talks to the network ----------------------------------

    def _request(self, method: str, url: str, payload: dict | None = None) -> dict:
        if not self._token:
            raise ProviderError(
                f"{TOKEN_VARIABLE} is not set. This is a configuration state, not "
                "a render failure: connect Replicate in the Credential Centre.")

        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "User-Agent": "qevik/1.0",
        })
        try:
            with self._opener(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            body = ""
            try:
                body = error.read().decode()[:400]
            except Exception:  # pragma: no cover - the error body is a courtesy
                pass
            # The token must never reach a log or an exception message; the URL
            # and the status are what a person needs to act.
            raise ProviderError(
                f"Replicate returned {error.code} for {method} {url.rsplit('/', 2)[-1]}: {body}"
            ) from error
        except urllib.error.URLError as error:
            raise ProviderError(f"could not reach Replicate: {error.reason}") from error


def _first_output(body: dict) -> str:
    """Replicate returns a string, a list of strings, or a dict per model.

    Normalised here rather than in three call sites, and never guessed: an
    unrecognised shape returns empty so the caller raises with the real body
    instead of downloading something that is not the artefact.
    """
    output = body.get("output")
    if isinstance(output, str):
        return output
    if isinstance(output, list) and output and isinstance(output[-1], str):
        # Last, not first: image models return progressive frames and the final
        # entry is the finished one.
        return output[-1]
    if isinstance(output, dict):
        for key in ("video", "url", "image", "audio"):
            value = output.get(key)
            if isinstance(value, str):
                return value
    return ""


def wait(provider: ReplicateProvider, handle: str, *, timeout: float = 900.0,
         interval: float = 3.0, sleep=time.sleep) -> ProviderJobStatus:
    """Poll until the job finishes, and say plainly when it did not.

    A helper rather than part of the protocol: waiting is the caller's policy,
    and a worker that can afford to block is not the same as one that cannot.
    """
    deadline = time.monotonic() + timeout
    while True:
        status = provider.poll(handle)
        if status.finished:
            return status
        if time.monotonic() >= deadline:
            raise ProviderError(
                f"prediction {handle} was still {status.state.value} after "
                f"{timeout:.0f}s. It may still be running on the provider — this "
                "is a timeout here, not a cancellation there.")
        sleep(interval)

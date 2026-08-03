"""The minimum abstraction for work that outlives a request.

``ProviderAdapter.execute(action, payload) -> dict`` is synchronous. That is
fine for the two simulation stubs it was written for, and wrong for video: a Wan
render is minutes of work on a remote GPU, and parking a worker thread on it is
not a design.

So: three methods, because a remote job genuinely has three moments -- you start
it, you ask how it is going, and you collect it.

Deliberately absent, until a second real provider exists and disagrees with the
first: capability negotiation, streaming, lifecycle hooks, plugin discovery,
cancellation semantics, retry policy. Every one of those is a guess right now,
and a wrong guess in an interface is far more expensive than a missing one.

``ProviderAdapter`` is untouched. This is additive.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ProviderError(RuntimeError):
    """A provider could not do what was asked."""


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ProviderJobStatus(BaseModel):
    """Where a submitted job has got to."""

    handle: str
    state: JobState
    #: 0.0-1.0 when the provider knows; None when it does not. Not faked --
    #: a made-up progress bar is worse than an honest spinner.
    progress: float | None = None
    detail: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.state in (JobState.SUCCEEDED, JobState.FAILED)


class RenderRequest(BaseModel):
    """What a provider is asked to make.

    Carries the *rendered* intent, not the domain object: a provider never sees
    a ``Scene``, so the content layer cannot leak into an adapter and no adapter
    can start depending on the shape of the script.
    """

    #: Recipe that decides how this is made. Providers must not improvise.
    recipe_id: str
    #: What to render. For video, the visual direction; for TTS, the words.
    prompt: str
    duration_seconds: float = 5.0
    width: int = 1920
    height: int = 1080
    #: Recipe parameters, already resolved. Providers read, never invent.
    parameters: dict[str, Any] = Field(default_factory=dict)
    #: Free-form identification, for logs and filenames. Never load-bearing.
    labels: dict[str, str] = Field(default_factory=dict)


@runtime_checkable
class LongRunningProvider(Protocol):
    """A provider whose work outlives a request."""

    #: Stable identifier, matching the registered ``ProviderSpec.name``.
    name: str

    def submit(self, request: RenderRequest) -> str:
        """Start the work. Returns a handle; must not block until it finishes."""
        ...

    def poll(self, handle: str) -> ProviderJobStatus:
        """Report progress. Cheap enough to call in a loop."""
        ...

    def fetch(self, handle: str, destination: Path) -> Path:
        """Write the finished artefact to ``destination`` and return the path.

        Takes a destination rather than returning bytes: a 1080p clip has no
        business being held in memory just to be written to disk immediately
        afterwards.
        """
        ...

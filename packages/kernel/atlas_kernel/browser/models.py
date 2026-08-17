"""What a browser session does, and what it hands back.

The interface is Qevik's, not Playwright's. §28.5 says not to hard-code
provider assumptions into the core when an adapter is practical, and browser
runtimes are a field where today's obvious choice is replaced every two years.

Two decisions worth stating.

**Snapshot-and-ref rather than CSS selectors.** A ref is a stable handle to an
element that the backend assigns; callers never write ``div.card > button``.
Selector-based automation breaks on every redesign and cannot be driven by a
model that has not seen the page. This idea is borrowed from newer agent-facing
browser tools and is adopted here as an Atlas concept so another backend can
implement it — copying a good idea is not the same as being wrapped by it.

**Deterministic actions only.** There is no ``do_the_task`` method. The planner
stays in Qevik; the browser executes single, named, auditable steps. Nesting a
second autonomous loop inside a step makes failures unattributable and cost
unbounded, which is the same conclusion the OpenClaw review reached.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

#: The capability. Asked for by name; never a runtime.
BROWSER_OPERATE = "browser.operate"


def _now() -> datetime:
    return datetime.now(UTC)


class BrowserProfile(StrEnum):
    """Which browser identity a job runs under (§4).

    The distinction is a security boundary, not a convenience. A research
    profile carries no credentials and can safely visit hostile pages; an
    operational profile acts as a logged-in human and is the largest blast
    radius in the system.
    """

    #: Isolated, no credentials, no persistence. Safe for arbitrary pages.
    RESEARCH = "research"
    #: Authenticated. Every write is approval-gated. Not enabled by default.
    OPERATIONAL = "operational"


class ElementRef(BaseModel):
    """A handle to something on the page, assigned by the backend."""

    model_config = ConfigDict(frozen=True)

    ref: str
    role: str = ""
    name: str = ""
    #: Present only when the element accepts input, so a caller can tell a
    #: button from a text field without guessing from the name.
    editable: bool = False


class PageSnapshot(BaseModel):
    """What the page is, in a form a planner can act on.

    Carries refs rather than raw HTML because the caller needs to *choose an
    action*, and a megabyte of markup is both expensive to pass to a model and
    useless for deciding which button to press.
    """

    model_config = ConfigDict(frozen=True)

    url: str
    title: str = ""
    status: int | None = None
    #: Visible text, truncated. Evidence, and enough to decide what to do next.
    text: str = ""
    elements: list[ElementRef] = Field(default_factory=list)
    #: Console errors seen since the last action. §17 asks for these, and they
    #: are the difference between "the page loaded" and "the page works".
    console_errors: list[str] = Field(default_factory=list)
    captured_at: datetime = Field(default_factory=_now)

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 400


class Screenshot(BaseModel):
    """An image, and where it came from.

    Bytes are not held here. §16 requires provenance and the artifact system
    already stores content; a screenshot that lives only in a task's memory is
    the temporary-directory problem the spec warns about.
    """

    model_config = ConfigDict(frozen=True)

    url: str
    path: str
    width: int = 0
    height: int = 0
    full_page: bool = False
    captured_at: datetime = Field(default_factory=_now)


class BrowserJobStatus(StrEnum):
    """§5's lifecycle, unchanged."""

    QUEUED = "queued"
    PLANNING = "planning"
    STARTING = "starting"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BrowserJob(BaseModel):
    """§5's job, expressed against Qevik's existing job model.

    ``allowed_actions`` is the per-job authorisation §21 asks for: a research
    crawl gets navigation and reading, and cannot type into a form even if a
    planner decides it should. Least privilege stated per task rather than per
    profile.
    """

    id: str = Field(default_factory=lambda: f"bjob-{uuid4().hex[:12]}")
    #: The Qevik run this belongs to, so browser work appears in one history
    #: rather than in a parallel system.
    run_id: str | None = None
    business_id: str | None = None
    profile: BrowserProfile = BrowserProfile.RESEARCH
    target_url: str = ""
    objective: str = ""
    allowed_actions: list[str] = Field(
        default_factory=lambda: ["open", "snapshot", "extract", "screenshot"]
    )
    status: BrowserJobStatus = BrowserJobStatus.QUEUED
    screenshots: list[Screenshot] = Field(default_factory=list)
    extracted: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None

    def permits(self, action: str) -> bool:
        return action in self.allowed_actions

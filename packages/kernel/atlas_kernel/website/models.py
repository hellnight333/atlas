"""Entities for the Website Factory.

Read ``M015.md`` before changing anything here. Two properties in this file are
load-bearing rather than stylistic.

**A build is reproducible from the durable record alone.** Everything that ends
up on a customer's site is stored here — the files, byte for byte — so deleting
the working directory costs nothing. The failure that prevents: a customer asks
for a change eighteen months later and the site can only be edited by whoever
still has the folder. A factory whose output cannot be rebuilt is a consultancy
with extra steps.

**Atlas owns the artifact, not the host.** A ``SiteBuild`` is provider-agnostic:
it knows nothing about Cloudflare or Hetzner, and a ``Deployment`` records which
target a build was sent to rather than the build belonging to one. That is what
makes moving a customer between providers publish-and-promote instead of a
migration project.

The layering follows M013: ``Site`` is the content layer and carries no HTML, no
theme, no host. ``SiteBuild`` is the rendering layer. In Phase A a build is
authored by hand; in Phase B it is generated from ``Site``. Neither changes the
shape of a ``Deployment``, which is the point of separating them.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


def _digest(*parts: object) -> str:
    """A stable hash. ``None`` and ``""`` stay distinct, as elsewhere in Atlas."""
    material = "\x1f".join("\x00NULL" if part is None else str(part) for part in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Content layer — what the site says.
#
# Nothing here may reference HTML, a theme, a host or a deployment. If a field
# only makes sense for one rendering of the site, it belongs on a SiteBuild.
# ---------------------------------------------------------------------------


class Site(BaseModel):
    """A customer's site, as content rather than as markup.

    Phase A stores little more than the identity and where it should live;
    Phase B fills in services, hours and location. The shape is here now so that
    Phase B is filling a model in rather than reshaping one that deployments
    already reference.

    ``business_id`` and nothing else identifies the customer. There is no
    ``WebsiteClient`` and there never will be — see
    ``tests/test_one_customer_entity.py``.
    """

    id: str = Field(default_factory=_new_id)
    business_id: str
    name: str
    #: Where this site is meant to be reachable, once a domain is pointed at it.
    domain: str | None = None
    #: Content, deliberately open in Phase A. Phase B replaces this with typed
    #: fields; until then it is a place for facts the operator supplied, and it
    #: is still part of the durable record.
    content: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @field_validator("name")
    @classmethod
    def _named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a site must have a name")
        return value.strip()


# ---------------------------------------------------------------------------
# Rendering layer
# ---------------------------------------------------------------------------


class BuildStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class SiteBuild(BaseModel):
    """One rendered version of a site — the artifact, held by Atlas.

    ``files`` is the whole build: path to contents, stored rather than
    referenced. That is the literal meaning of "rebuild from Business memory",
    and it is why a provider can be swapped without a migration: the bytes never
    lived only inside Cloudflare.

    Text only for now, which is a real limit and stated rather than hidden. A
    hand-authored HTML and CSS site is tens of kilobytes and belongs in the
    database; the moment real images arrive they go to the asset system and this
    model holds references instead. Phase A does not need that, and building it
    now would be an abstraction with no user.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=_new_id)
    site_id: str
    business_id: str
    #: Relative path -> file contents. The complete artifact.
    files: dict[str, str]
    status: BuildStatus = BuildStatus.READY
    #: What produced this build, so a rebuild can be compared like with like.
    generator: str = "authored"
    #: Free-form record of inputs — theme, content version, generator settings.
    #: Provenance rather than configuration: nothing reads it to make a decision.
    provenance: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)

    @field_validator("files")
    @classmethod
    def _not_empty(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("a build must contain at least one file")
        if not any(path.endswith(".html") for path in value):
            raise ValueError(
                "a build must contain at least one HTML file — a site nobody can "
                "load is not a deployable artifact"
            )
        return value

    @property
    def fingerprint(self) -> str:
        """Identity of the *content*, not of the record.

        Deliberately excludes id, timestamps and provenance: two builds of the
        same files are the same artifact whoever made them and whenever. That is
        what lets "rebuilt correctly" be settled by comparing fingerprints
        instead of by a person looking at two pages, and it is what makes
        deploying the same build to a second provider verifiable.
        """
        return _digest(*(f"{path}\x00{_digest(self.files[path])}" for path in sorted(self.files)))

    @property
    def total_bytes(self) -> int:
        return sum(len(body.encode("utf-8")) for body in self.files.values())


# ---------------------------------------------------------------------------
# Deployment layer
# ---------------------------------------------------------------------------


class DeploymentStatus(StrEnum):
    """The publish-then-promote lifecycle.

    ``PUBLISHED`` is the state that makes the gate possible: the artifact exists
    at the target and is reachable, and no visitor is being served it yet.
    """

    PENDING = "pending"
    PUBLISHED = "published"
    GATE_FAILED = "gate_failed"
    LIVE = "live"
    SUPERSEDED = "superseded"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"


class Deployment(BaseModel):
    """One build sent to one target.

    A build may have many deployments — that is the whole point. The same
    artifact on Cloudflare and on Hetzner is two deployments of one build, and
    moving a customer between them promotes a different deployment rather than
    rebuilding anything.

    Atlas's record of what is live, deliberately: reading it back from a
    provider's API would make the answer depend on an account that can be
    closed and an API that can change.
    """

    id: str = Field(default_factory=_new_id)
    build_id: str
    site_id: str
    business_id: str
    #: Registered target name, never a provider class. "cloudflare-pages",
    #: "hetzner", "local" — the kernel does not branch on it.
    target: str
    status: DeploymentStatus = DeploymentStatus.PENDING
    #: The target's own handle for this published version, opaque to Atlas.
    remote_id: str | None = None
    #: Reachable before promotion. What the gate inspects.
    preview_url: str | None = None
    #: Reachable by visitors after promotion.
    live_url: str | None = None
    #: Fingerprint of the build at publish time, so a deployment can be shown to
    #: be the artifact it claims to be.
    build_fingerprint: str = ""
    #: Findings from the pre-promotion gate. Empty on a clean pass.
    gate_findings: list[str] = Field(default_factory=list)
    detail: str | None = None
    created_at: datetime = Field(default_factory=_now)
    promoted_at: datetime | None = None

    @property
    def is_serving(self) -> bool:
        return self.status is DeploymentStatus.LIVE


class VerificationResult(BaseModel):
    """What a live URL actually returned.

    A deployment tool's exit code says the upload succeeded. It does not say a
    visitor can load the page, which is the only thing that matters — so every
    promotion is confirmed by fetching the site and looking at what came back.
    """

    model_config = ConfigDict(frozen=True)

    url: str
    ok: bool
    status_code: int | None = None
    elapsed_seconds: float | None = None
    detail: str = ""
    checked_at: datetime = Field(default_factory=_now)

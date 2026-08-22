"""What a publication is, and the two things it must never contain.

**It must never contain a secret.** A `Connection` holds a *reference* to a
credential — an environment variable name, a vault key — and never the
credential. The secret is fetched at the moment of use by a resolver supplied at
the boundary, used, and dropped. Nothing that is written down here can leak,
because there is nothing here to leak; that is a stronger property than
remembering to redact, which works until the one log line nobody thought about.

**It must never contain a claim.** A publication record says an artefact reached
a destination. Whether that helped the business is a measurement question,
answered later at whatever attribution level the evidence supports. So the
record has `status`, `external_id` and `error`, and deliberately no field that
could be read as a result.

`PublicationStatus` is imported from `media.models` rather than redeclared. Its
six values are already the right ones and a second copy would drift.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ..media.models import PublicationStatus

#: Statuses meaning the artefact is live somewhere. Exactly one value, and it is
#: not reachable except through a target reporting success.
LIVE: frozenset[PublicationStatus] = frozenset({PublicationStatus.PUBLISHED})

#: The action name a policy can attach to. Distinct from the P1.6 execution
#: action on purpose: "should Qevik do this work" and "may this exact output go
#: to this exact destination" are different questions asked of different people
#: at different times, and one approval must never answer both.
PUBLISH_ACTION = "qevik.publication.artefact.publish"

#: Stored on the approval so the check at publish time compares like with like.
ARTEFACT_FINGERPRINT = "artefact_fingerprint"


class SecretLeak(Exception):
    """Something that looks like a credential reached a place records are kept."""


class NotPublishable(Exception):
    """Publication was refused. Carries every unmet condition, not the first."""

    def __init__(self, asset_id: str, reasons: tuple[str, ...]) -> None:
        self.asset_id = asset_id
        self.reasons = reasons
        super().__init__(f"{asset_id} cannot be published: " + "; ".join(reasons))


class ConnectionKind(StrEnum):
    """How a target is reached. What varies is where the secret comes from."""

    #: A path on a filesystem Atlas already controls. No secret at all — the
    #: reference is the root directory, and it is not sensitive.
    FILESYSTEM = "filesystem"
    #: A bearer token or API key resolved from the environment or a vault.
    API_TOKEN = "api_token"
    #: An OAuth refresh token, resolved and exchanged at use time.
    OAUTH = "oauth"


#: Substrings that mean a value is a secret rather than a reference to one. Used
#: to refuse a Connection built with the credential pasted into it, which is the
#: mistake that makes every other protection here irrelevant.
_SECRET_SHAPED = ("-----BEGIN", "ya29.", "sk-", "ghp_", "xoxb-", "AKIA")


class Connection(BaseModel):
    """How to reach one target, on behalf of one tenant.

    Owned by a tenant, always. A connection with no tenant is not a shared
    connection — it is refused, because the failure mode of the other reading is
    one customer publishing with another customer's credential.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    tenant_id: str
    #: The registered target this reaches. Not a URL: which host, not where.
    target: str
    kind: ConnectionKind = ConnectionKind.FILESYSTEM
    #: **A reference, never a secret.** The name of an environment variable, a
    #: vault key, a directory root. Whatever a resolver can turn into a
    #: credential — and whatever is safe to write in an event, a log and a
    #: customer-visible report, because all three will contain it.
    reference: str
    label: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def model_post_init(self, _: object) -> None:
        if not self.tenant_id:
            raise SecretLeak(
                f"{self.id}: a connection with no tenant belongs to nobody, and "
                "would be usable by everybody")
        if not self.reference:
            raise SecretLeak(f"{self.id}: a connection needs a reference to resolve")
        for marker in _SECRET_SHAPED:
            if marker in self.reference:
                raise SecretLeak(
                    f"{self.id}: reference looks like a credential itself "
                    f"(contains {marker!r}). Store the *name* of the secret here, "
                    "not the secret — this value is written to events and reports.")


class Destination(BaseModel):
    """Where exactly, at the target. Part of what an approver consents to."""

    model_config = ConfigDict(frozen=True)

    #: The site or account slug at the target.
    slug: str
    #: For display and for the approval. Not resolved or fetched here.
    url: str = ""
    detail: str = ""


class PublicationRecord(BaseModel):
    """One attempt to put one artefact somewhere real. Immutable.

    Every link in the chain by id, so six months later "why is this page live,
    who agreed to it, and what evidence was it built from" is answerable without
    inference. A record is never edited: a retry is a new record, and the failed
    one stays.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    #: --- who ---------------------------------------------------------
    tenant_id: str
    business_id: str
    #: --- what it came from, all existing ids -------------------------
    recommendation_id: str
    roadmap_task_id: str = ""
    run_id: str
    job_id: str
    asset_id: str
    #: The artefact's content hash. What was published, not merely which row.
    content_hash: str
    #: --- where it went ------------------------------------------------
    target: str
    destination: Destination
    #: The connection's id, never its reference and never its secret.
    connection_id: str
    #: --- who allowed it ------------------------------------------------
    #: The P1.6 approval that authorised the work.
    execution_approval_id: str = ""
    #: The second boundary: this exact artefact, this exact destination.
    artefact_approval_id: str
    artefact_fingerprint: str
    #: --- what happened -------------------------------------------------
    status: PublicationStatus = PublicationStatus.PENDING_APPROVAL
    #: The target's own handle for what it accepted. Opaque to us.
    external_id: str = ""
    external_url: str = ""
    error: str = ""
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None

    @property
    def published(self) -> bool:
        """True only when a target reported success. Never inferred."""
        return self.status is PublicationStatus.PUBLISHED

    @property
    def is_business_result(self) -> bool:
        """Always False, and present so the question has a written answer.

        A successful upload is an intervention, not an outcome. Code reaching
        for "did this work" gets a no from here and has to go to `measurement/`,
        where the answer depends on evidence rather than on an HTTP status.
        """
        return False

    def summary(self) -> dict:
        """What is safe to put in an event, a log or a customer report.

        The connection appears as an id. There is no field on this model that
        holds a secret, so this is a narrowing for readability rather than a
        redaction — but it is the only shape anything downstream should copy.
        """
        return {
            "publication_id": self.id, "tenant_id": self.tenant_id,
            "business_id": self.business_id,
            "recommendation_id": self.recommendation_id,
            "roadmap_task_id": self.roadmap_task_id,
            "run_id": self.run_id, "job_id": self.job_id,
            "asset_id": self.asset_id, "content_hash": self.content_hash,
            "target": self.target, "destination": self.destination.model_dump(),
            "connection_id": self.connection_id,
            "execution_approval_id": self.execution_approval_id,
            "artefact_approval_id": self.artefact_approval_id,
            "artefact_fingerprint": self.artefact_fingerprint,
            "status": self.status.value, "external_id": self.external_id,
            "external_url": self.external_url, "error": self.error,
            "attempted_at": self.attempted_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


def artefact_fingerprint(*, content_hash: str, target: str, destination: Destination,
                         tenant_id: str) -> str:
    """What an artefact approval is a decision about.

    The content, the host and the exact destination. Change any of them and the
    decision no longer describes what would happen — a different file, a
    different slug, or the same file pointed at somebody else's site are all
    things a person did not say yes to.
    """
    material = {"content_hash": content_hash, "target": target,
                "slug": destination.slug, "url": destination.url,
                "tenant_id": tenant_id}
    return hashlib.sha256(
        json.dumps(material, sort_keys=True).encode("utf-8")).hexdigest()[:32]

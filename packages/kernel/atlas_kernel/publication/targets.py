"""Where a site actually goes, and what happens when it cannot go there.

This is the boundary the commercial review named as the one thing standing
between "complete" and "delivered": three capabilities produce a finished bundle
and every customer receives a folder rather than a website.

Everything that can be built without a host is built here — the target
abstraction, a Cloudflare adapter, a DNS model, a domain-verification flow, and
a local target that genuinely works. What cannot be built is the host itself.

Three rules shape it.

**A publication either happened or it did not.** There is no partial success. A
target that uploaded four files of six and reported success would leave a site
half-replaced and live, which is worse than a failed deployment: the customer's
old page is gone and the new one is broken. So `Deployment` carries every file
it wrote, and a failure carries what it managed before failing, so a rollback
knows what to undo.

**A domain is verified before anything is published to it.** Publishing to a
domain somebody typed is publishing to whatever they typed — a competitor's
name, a typo, or a domain they do not own. Verification is a DNS record only the
owner can create, and `VerificationState` distinguishes *not yet checked* from
*checked and failed*, because retrying one is sensible and retrying the other is
not.

**A refusal names the dependency.** `PendingCredentialTarget` and
`PendingInfrastructureTarget` are different classes because they are different
human actions: one is a key somebody enters, the other is a machine that does not
exist. Collapsing them into "not configured" makes the second look solvable by
typing.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)

#: A hostname, conservatively. Anything else is refused rather than normalised —
#: guessing what somebody meant by a malformed domain is how a site gets
#: published to the wrong one.
HOSTNAME = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$")

#: The TXT record a domain owner creates to prove they control it. Prefixed so it
#: cannot collide with anything else in the zone.
VERIFICATION_PREFIX = "qevik-site-verification"


class TargetUnavailable(RuntimeError):
    """This target cannot publish, and why."""


class MissingCredential(TargetUnavailable):
    """A key somebody enters in the Credential Centre. Solvable by typing."""


class MissingInfrastructure(TargetUnavailable):
    """A machine, a domain or a DNS record. Not solvable by typing."""


class PublishState(StrEnum):
    """What actually happened. Deliberately without a partial success."""

    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    #: Everything was ready and nothing was sent, because publishing was not
    #: authorised. Distinct from FAILED: nothing went wrong.
    NOT_AUTHORISED = "NOT_AUTHORISED"
    ROLLED_BACK = "ROLLED_BACK"


class VerificationState(StrEnum):
    """Whether this domain is ours to publish to."""

    VERIFIED = "VERIFIED"
    #: The record was looked for and is not there. Retrying will not help until
    #: somebody creates it.
    FAILED = "FAILED"
    #: Nobody has looked yet. Retrying is exactly the right move.
    NOT_CHECKED = "NOT_CHECKED"
    #: We looked and could not tell — DNS timeout, resolver failure. **Not** the
    #: same as failed, and publishing on it would be publishing on our outage.
    UNKNOWN = "UNKNOWN"


class Domain(BaseModel):
    """A domain, and whether it has been proved to belong to this tenant."""

    model_config = ConfigDict(frozen=True)

    hostname: str
    tenant_id: str
    state: VerificationState = VerificationState.NOT_CHECKED
    checked_at: datetime | None = None
    detail: str = ""

    @property
    def token(self) -> str:
        """The value the owner puts in the TXT record.

        Derived from the hostname and the tenant, so one tenant's token cannot
        verify another tenant's domain — and so it is reproducible without
        being stored.
        """
        digest = hashlib.sha256(
            f"{self.tenant_id}:{self.hostname}".encode()).hexdigest()
        return f"{VERIFICATION_PREFIX}={digest[:32]}"

    @property
    def record(self) -> dict:
        """Exactly what a person types into their DNS provider."""
        return {"type": "TXT", "name": self.hostname, "value": self.token,
                "ttl": 300,
                "note": ("Only somebody who controls this domain can create "
                         "this record, which is what makes it proof.")}

    @property
    def publishable(self) -> bool:
        return self.state is VerificationState.VERIFIED


def verify(domain: Domain, *, records: tuple[str, ...] | None) -> Domain:
    """Check the TXT records for our token.

    `records=None` means the lookup itself failed — resolver down, timeout, no
    answer. That is UNKNOWN, not FAILED: publishing on the strength of our own
    outage is exactly the mistake, and so is telling a customer their record is
    missing when we could not look.
    """
    now = datetime.now(UTC)
    if records is None:
        return domain.model_copy(update={
            "state": VerificationState.UNKNOWN, "checked_at": now,
            "detail": ("the DNS lookup did not answer, so nothing was "
                       "established about this domain")})
    if domain.token in records:
        return domain.model_copy(update={
            "state": VerificationState.VERIFIED, "checked_at": now,
            "detail": "the verification record is present"})
    return domain.model_copy(update={
        "state": VerificationState.FAILED, "checked_at": now,
        "detail": (f"no TXT record matching {VERIFICATION_PREFIX} was found on "
                   f"{domain.hostname}. {len(records)} other record(s) are "
                   "present, so the lookup worked and the record is absent.")})


def domain_for(hostname: str, *, tenant: str) -> Domain:
    """A domain to verify, or a refusal. Never a guess at what was meant."""
    cleaned = (hostname or "").strip().lower().removeprefix("http://")
    cleaned = cleaned.removeprefix("https://").split("/")[0].removeprefix("www.")
    if not HOSTNAME.match(cleaned):
        raise MissingInfrastructure(
            f"{hostname!r} is not a hostname Qevik will publish to. Guessing "
            "what a malformed domain meant is how a site reaches the wrong one.")
    return Domain(hostname=cleaned, tenant_id=tenant)


class Deployment(BaseModel):
    """What one publication attempt actually did."""

    model_config = ConfigDict(frozen=True)

    target: str
    state: PublishState
    #: Every file written, so a rollback knows precisely what to undo. Populated
    #: on failure too — a partial upload is the case rollback exists for.
    written: tuple[str, ...] = ()
    url: str = ""
    detail: str = ""
    #: The bundle's identity, carried through so a published site can be proved
    #: to be the artefact that was approved.
    content_hash: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def succeeded(self) -> bool:
        return self.state is PublishState.PUBLISHED

    def summary(self) -> dict:
        return {"target": self.target, "state": self.state.value,
                "written": list(self.written), "url": self.url,
                "detail": self.detail, "content_hash": self.content_hash,
                "at": self.at.isoformat(), "succeeded": self.succeeded}


@runtime_checkable
class PublicationTarget(Protocol):
    """Somewhere a bundle of files can be put where the public can reach it."""

    @property
    def name(self) -> str: ...

    @property
    def requires_verified_domain(self) -> bool:
        """False only for targets that serve no public domain."""
        ...

    def publish(self, files: dict[str, str], *, domain: Domain | None,
                content_hash: str = "") -> Deployment:
        """Put every file, or none. Raise `TargetUnavailable` rather than half."""
        ...

    def rollback(self, deployment: Deployment) -> Deployment:
        """Undo what a deployment wrote."""
        ...


class LocalTarget:
    """A directory a web server serves. Real, and the only one connected.

    Not a stub: this genuinely publishes, and a deployment through it is a
    deployment. What it cannot do is give the site a public address, which is
    why `requires_verified_domain` is False and why the commercial review counts
    a customer served this way as receiving a bundle rather than a site.

    Writes to a temporary directory and moves it into place, so a failure
    halfway leaves the previous version intact. A target that overwrote files
    one at a time would leave a customer's live site half-replaced.
    """

    def __init__(self, root: Path | str, *, name: str = "local") -> None:
        self.root = Path(root)
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def requires_verified_domain(self) -> bool:
        return False

    def publish(self, files: dict[str, str], *, domain: Domain | None = None,
                content_hash: str = "") -> Deployment:
        if not files:
            return Deployment(target=self._name, state=PublishState.FAILED,
                              detail="there is nothing to publish")
        staging = self.root.parent / f".{self.root.name}.incoming"
        written: list[str] = []
        try:
            if staging.exists():
                _remove(staging)
            staging.mkdir(parents=True)
            for name, body in sorted(files.items()):
                path = staging / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(body, encoding="utf-8")
                written.append(name)

            previous = self.root.parent / f".{self.root.name}.previous"
            if previous.exists():
                _remove(previous)
            if self.root.exists():
                self.root.rename(previous)
            staging.rename(self.root)
        except OSError as failure:
            log.exception("local publish failed")
            _remove(staging)
            return Deployment(target=self._name, state=PublishState.FAILED,
                              written=tuple(written), content_hash=content_hash,
                              detail=f"{type(failure).__name__}: {failure}"[:200])

        return Deployment(target=self._name, state=PublishState.PUBLISHED,
                          written=tuple(written), url=f"file://{self.root}",
                          content_hash=content_hash,
                          detail=f"{len(written)} file(s) written")

    def rollback(self, deployment: Deployment) -> Deployment:
        """Put the previous version back, if there is one."""
        previous = self.root.parent / f".{self.root.name}.previous"
        if not previous.exists():
            return deployment.model_copy(update={
                "state": PublishState.FAILED,
                "detail": ("nothing to roll back to: this was the first "
                           "publication to this target")})
        _remove(self.root)
        previous.rename(self.root)
        return deployment.model_copy(update={
            "state": PublishState.ROLLED_BACK,
            "detail": "the previous version was restored"})


def _remove(path: Path) -> None:
    import shutil

    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


class CloudflareTarget:
    """Cloudflare Pages. Everything but the call.

    The adapter is written to the point where only the HTTP request is missing,
    and that request is deliberately absent rather than written blind. Cloudflare
    Pages' direct-upload flow takes three round trips — create a deployment, upload
    a manifest of file hashes, upload only the files Cloudflare says it is missing
    — and an implementation written against no account, with no way to run it,
    would be a plausible-looking sequence that fails on the first real call. Worse,
    it would read as finished.

    So `publish` refuses with `MissingCredential`, and everything around it is
    real: the domain must be verified first, the manifest is computed the way
    Cloudflare's API expects, and the refusal names exactly what is needed.

    **What a person must provide:** an API token with `Cloudflare Pages:Edit` on
    the account, and the account id. Both from
    `https://dash.cloudflare.com/profile/api-tokens`. Neither can be derived.
    """

    def __init__(self, *, project: str = "", account_id: str = "",
                 credential: str = "QEVIK_CLOUDFLARE_API_TOKEN") -> None:
        self.project = project
        self.account_id = account_id
        self.credential = credential

    @property
    def name(self) -> str:
        return "cloudflare"

    @property
    def requires_verified_domain(self) -> bool:
        return True

    @staticmethod
    def manifest(files: dict[str, str]) -> dict[str, str]:
        """Path -> content hash, the shape Cloudflare's upload flow expects.

        Computed here rather than at call time because it is the part that can
        be tested without an account, and because a manifest that disagreed with
        the bundle would upload the wrong files under the right names.
        """
        return {f"/{name}": hashlib.blake2b(body.encode("utf-8"),
                                            digest_size=16).hexdigest()
                for name, body in sorted(files.items())}

    def publish(self, files: dict[str, str], *, domain: Domain | None = None,
                content_hash: str = "") -> Deployment:
        if domain is None or not domain.publishable:
            raise MissingInfrastructure(
                "Cloudflare Pages serves a public domain, and this one is not "
                f"verified ({domain.state.value if domain else 'no domain'}). "
                "Publishing to an unverified domain is publishing to whatever "
                "somebody typed.")
        raise MissingCredential(
            f"Cloudflare is not connected. Add {self.credential} and the "
            "account id in the Credential Centre. The token needs "
            "'Cloudflare Pages:Edit' on the account; nothing else here can be "
            "derived, and the upload call is deliberately unwritten rather than "
            "written blind against an API nobody can run.")

    def rollback(self, deployment: Deployment) -> Deployment:
        raise MissingCredential(
            f"Cloudflare is not connected, so there is nothing to roll back. "
            f"Add {self.credential} first.")


class PendingCredentialTarget:
    """A target whose adapter exists and whose key does not.

    Registered rather than absent, so the gap is visible in the Credential
    Centre with a name and an action instead of the target simply not existing.
    """

    def __init__(self, name: str, *, credential: str,
                 requires_verified_domain: bool = True) -> None:
        self._name = name
        self.credential = credential
        self._requires_domain = requires_verified_domain

    @property
    def name(self) -> str:
        return self._name

    @property
    def requires_verified_domain(self) -> bool:
        return self._requires_domain

    def publish(self, files: dict[str, str], *, domain: Domain | None = None,
                content_hash: str = "") -> Deployment:
        raise MissingCredential(
            f"{self._name} is not connected. Add {self.credential} in the "
            "Credential Centre.")

    def rollback(self, deployment: Deployment) -> Deployment:
        raise MissingCredential(f"{self._name} is not connected.")


class PendingInfrastructureTarget:
    """A target that needs a machine, not a key.

    A separate class from `PendingCredentialTarget` because they are different
    human actions and collapsing them into "not configured" makes provisioning a
    server look like something solvable by typing a password.
    """

    def __init__(self, name: str, *, needs: str) -> None:
        self._name = name
        self.needs = needs

    @property
    def name(self) -> str:
        return self._name

    @property
    def requires_verified_domain(self) -> bool:
        return True

    def publish(self, files: dict[str, str], *, domain: Domain | None = None,
                content_hash: str = "") -> Deployment:
        raise MissingInfrastructure(
            f"{self._name} needs {self.needs}. This is not a credential — no "
            "key makes it exist.")

    def rollback(self, deployment: Deployment) -> Deployment:
        raise MissingInfrastructure(f"{self._name} needs {self.needs}.")


def deploy(target: PublicationTarget, files: dict[str, str], *,
           domain: Domain | None = None, content_hash: str = "",
           authorised: bool = False) -> Deployment:
    """Publish, with every precondition checked before anything is sent.

    `authorised` defaults to False and is the last gate rather than the first:
    a caller that has verified the domain, resolved the target and hashed the
    bundle has still not been told by a person that this may go live.
    `READY_TO_PUBLISH` is not `PUBLISHED`, and this is where that stops being a
    slogan.
    """
    if not authorised:
        return Deployment(
            target=target.name, state=PublishState.NOT_AUTHORISED,
            content_hash=content_hash,
            detail=("everything is ready and nothing was sent: publication has "
                    "not been authorised. This is not a failure."))
    if target.requires_verified_domain and (domain is None
                                            or not domain.publishable):
        state = domain.state.value if domain else "no domain supplied"
        return Deployment(
            target=target.name, state=PublishState.FAILED,
            content_hash=content_hash,
            detail=f"the domain is not verified ({state}), so nothing was sent")
    try:
        return target.publish(files, domain=domain, content_hash=content_hash)
    except TargetUnavailable as refused:
        # A refusal is recorded, not raised: the caller needs the reason on the
        # publication record, and a target that cannot publish is a fact about
        # this deployment rather than a crash.
        return Deployment(target=target.name, state=PublishState.FAILED,
                          content_hash=content_hash, detail=str(refused))


def describe(target: PublicationTarget) -> dict:
    """What this target can do and what it needs. For the action centre."""
    if isinstance(target, PendingCredentialTarget | CloudflareTarget):
        return {"target": target.name, "status": "PENDING_CREDENTIAL",
                "credential": target.credential,
                "action": f"Add {target.credential} in the Credential Centre",
                "publishes": False}
    if isinstance(target, PendingInfrastructureTarget):
        return {"target": target.name, "status": "PENDING_INFRASTRUCTURE",
                "needs": target.needs,
                "action": f"Provide {target.needs}", "publishes": False}
    return {"target": target.name, "status": "CONNECTED", "publishes": True,
            "public": target.requires_verified_domain,
            "note": "" if target.requires_verified_domain else
                    ("serves no public domain, so a customer receives a bundle "
                     "rather than a site")}

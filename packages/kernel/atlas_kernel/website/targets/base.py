"""What a deployment target is, and why the interface has this shape.

Two hosts were designed against from the start, because an interface validated
by one implementation is validated by nobody. Cloudflare Pages and a Hetzner box
work differently enough to be a real test:

============  ==============================  ============================
              Cloudflare Pages                Hetzner
============  ==============================  ============================
Publish       upload a bundle, get an id      copy a versioned directory
Activate      promote that deployment id      swap a symlink, reload nginx
Rollback      promote an earlier id           swap the symlink back
TLS           automatic                       Caddy / ACME
============  ==============================  ============================

An interface phrased as *"copy these files to this path"* encodes the second and
Cloudflare cannot satisfy it. One phrased as *"upload and give me a deployment
id"* encodes the first and Hetzner cannot. **Publish a versioned artifact, then
promote it** is what the two have in common, so that is the interface.

It buys something beyond portability. Promotion being separate from publication
means an artifact can be *reachable but not yet live*, which is what makes a
pre-promotion quality gate possible at all: the gate inspects exactly what
visitors will be served, on the real host, over the real TLS, before anybody is
served it.

**Rollback is not an operation here.** It is promotion of a version Atlas
already holds, and it is deliberately not delegated to the provider — a rollback
that depends on a provider's retention policy is a provider feature wearing
Atlas's name, and it stops working the day the provider is swapped. See
``service.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: The capability. The kernel asks for this and never for a named host.
DEPLOY = "site.deploy"


class DeploymentError(RuntimeError):
    """A target could not complete an operation.

    Distinct from a gate refusal: this means the host failed, not that the site
    was judged unfit. Conflating them would make a Cloudflare outage look like a
    quality problem with the customer's site.
    """


class NoTargetAvailable(RuntimeError):
    """Nothing is registered to deploy to.

    A configuration problem rather than a deployment failure, and worth its own
    error so the message can say which capability is unserved.
    """


@dataclass(frozen=True)
class PublishedVersion:
    """An artifact that exists at the target and serves nobody yet."""

    #: The target's own handle. Opaque to Atlas — a Cloudflare deployment id, a
    #: directory name, whatever the host uses. Nothing outside the adapter reads
    #: its structure.
    id: str
    #: Where this version can be fetched before promotion. What the gate checks.
    preview_url: str
    detail: str = ""


@runtime_checkable
class DeploymentTarget(Protocol):
    """Somewhere a site can be published and promoted.

    Implementations do no policy: they do not decide whether a build is fit to
    serve, do not consult a gate, and do not record anything. A guard duplicated
    into every adapter is a guard that will eventually be missing from one.
    """

    @property
    def name(self) -> str: ...

    def publish(self, site_slug: str, files: dict[str, str]) -> PublishedVersion:
        """Put an artifact at the target without serving it to anyone."""
        ...

    def promote(self, site_slug: str, version_id: str) -> str:
        """Make a published version the one visitors get. Returns the live URL."""
        ...


@runtime_checkable
class RemovableTarget(Protocol):
    """Targets that can clean up old versions.

    Optional on purpose. Retention is a host concern with real differences —
    Cloudflare keeps deployments, a disk fills up — and requiring it of every
    adapter would put a policy decision in the interface.
    """

    def remove(self, site_slug: str, version_id: str) -> None: ...


@dataclass
class TargetRegistration:
    target: DeploymentTarget
    #: Preferred when no target is named. Local-first, as everywhere in Atlas.
    is_local: bool = True
    #: USD per month, for a cost-aware choice later. Zero for a box already paid
    #: for.
    cost_per_month: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.target.name


class DeploymentTargetRegistry:
    """Which targets can serve ``site.deploy``.

    Same shape as the media provider registry, for the same reason: choosing a
    host becomes a registration and a policy rather than a code change, so
    moving a customer from Hetzner to Cloudflare is configuration.
    """

    def __init__(self) -> None:
        self._registrations: list[TargetRegistration] = []

    def register(self, registration: TargetRegistration) -> TargetRegistration:
        self._registrations = [
            item for item in self._registrations if item.name != registration.name
        ]
        self._registrations.append(registration)
        return registration

    @property
    def targets(self) -> list[TargetRegistration]:
        return list(self._registrations)

    def resolve(self, preferred: str | None = None) -> TargetRegistration:
        """Pick a target.

        ``preferred`` is a preference and not a demand — the same rule the media
        registry follows. A named target that is not registered is a
        configuration error worth failing loudly on, though, because silently
        deploying a customer's site somewhere other than intended is worse than
        not deploying it.
        """
        if not self._registrations:
            raise NoTargetAvailable(f"no target registered for {DEPLOY}")

        if preferred is not None:
            for registration in self._registrations:
                if registration.name == preferred:
                    return registration
            known = ", ".join(sorted(r.name for r in self._registrations))
            raise NoTargetAvailable(
                f"target {preferred!r} is not registered (known: {known}); "
                "refusing to deploy somewhere other than asked"
            )

        return sorted(
            self._registrations,
            key=lambda item: (not item.is_local, item.cost_per_month, item.name),
        )[0]

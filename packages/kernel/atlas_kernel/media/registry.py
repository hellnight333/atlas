"""Which provider serves a capability.

The kernel asks for ``video.generate``. It never asks for ComfyUI, Wan,
Seedance, Veo, Kling or LTX, and it never branches on which one answered. That
is the whole reason providers stay disposable: swapping one is a registration
change, and nothing downstream notices.

Selection is local-first, which is a policy and not an assumption. Nothing here
believes there is one GPU: several local providers can be registered, and the
cheapest wins. When the fleet grows, placement becomes the scheduler's problem
and this interface does not change.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .providers.base import LongRunningProvider


class NoProviderAvailable(RuntimeError):
    """Nothing registered can serve this capability.

    A distinct error because it is a configuration problem, not a render
    failure. "No local video provider is registered and cloud is disabled" is
    the correct, actionable message; "render failed" is not.
    """


@dataclass(frozen=True)
class ProviderRegistration:
    provider: LongRunningProvider
    capability: str
    #: Local providers are preferred. Cloud is a fallback, never the default.
    is_local: bool = True
    #: USD per second of output. 0.0 for local, where the cost is electricity.
    cost_per_second: float = 0.0
    #: Wall-clock seconds per second of output. Used for estimates.
    seconds_per_second: float | None = None
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.provider.name


class MediaProviderRegistry:
    def __init__(self, *, allow_cloud: bool = True) -> None:
        self._registrations: list[ProviderRegistration] = []
        self.allow_cloud = allow_cloud

    def register(self, registration: ProviderRegistration) -> ProviderRegistration:
        self._registrations = [r for r in self._registrations if r.name != registration.name]
        self._registrations.append(registration)
        return registration

    def resolve(self, capability: str, preferred: str | None = None) -> ProviderRegistration:
        """Pick a provider for a capability.

        ``preferred`` comes from a recipe and is exactly that -- a preference.
        A recipe that names a provider which is absent, or which cannot serve
        the capability it claims, falls through to normal selection rather than
        failing. Recipes outlive the providers they were written against.
        """
        candidates = [r for r in self._registrations if r.capability == capability]
        if not self.allow_cloud:
            candidates = [r for r in candidates if r.is_local]

        if not candidates:
            raise NoProviderAvailable(
                f"no provider is registered for {capability!r}"
                + ("" if self.allow_cloud else " (cloud providers are disabled)")
            )

        if preferred:
            exact = [r for r in candidates if r.name == preferred]
            if exact:
                return exact[0]

        # Local first, then cheapest, then fastest. Same ordering the kernel's
        # ProviderRouter already uses, so the two cannot disagree.
        return sorted(
            candidates,
            key=lambda r: (not r.is_local, r.cost_per_second, r.seconds_per_second or 0.0),
        )[0]

    def names(self) -> list[str]:
        return sorted(r.name for r in self._registrations)

"""What a detector is, and the registry that keeps them disposable.

Detection is capability-based for the same reason rendering is: the kernel asks
for ``opportunity.inspect`` and never learns which detector answered. Swapping
one is a registration change and nothing downstream notices.

Two capabilities exist:

* ``opportunity.discover`` -- produce candidate prospects for a niche.
* ``opportunity.inspect`` -- inspect one prospect and return evidenced findings.

A detector's only contract is that everything it returns carries evidence. That
is enforced by ``Finding`` itself rather than by anything here, so a detector
cannot cut the corner even by accident.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..models import Finding, NicheProfile, Prospect

DISCOVER = "opportunity.discover"
INSPECT = "opportunity.inspect"


class DetectorError(RuntimeError):
    """A detector could not complete.

    Distinct from "found nothing". A detector that fails must say so rather than
    return an empty list, because an empty list means "this business is fine"
    and a timeout does not.
    """


@runtime_checkable
class Detector(Protocol):
    """Inspects one prospect and reports what is wrong with evidence."""

    @property
    def name(self) -> str: ...

    def inspect(self, prospect: Prospect, profile: NicheProfile) -> list[Finding]: ...


@runtime_checkable
class ProspectSource(Protocol):
    """Produces candidates for a niche.

    The MVP ships a seed-list implementation and nothing else. Finding names is
    cheap and every market has a different way of doing it; producing evidenced
    findings is where the value is, so that is where the build went. A directory
    or search-backed source drops in here without touching anything else.
    """

    @property
    def name(self) -> str: ...

    def discover(self, profile: NicheProfile, limit: int) -> list[Prospect]: ...


class NoDetectorAvailable(RuntimeError):
    """Nothing is registered for a capability.

    A configuration problem rather than an inspection failure, and worth its own
    error so the message can say which capability is unserved instead of
    "detection failed".
    """


class DetectorRegistry:
    """Which detectors serve which capability."""

    def __init__(self) -> None:
        self._detectors: list[Detector] = []
        self._sources: list[ProspectSource] = []

    def register_detector(self, detector: Detector) -> Detector:
        self._detectors = [d for d in self._detectors if d.name != detector.name]
        self._detectors.append(detector)
        return detector

    def register_source(self, source: ProspectSource) -> ProspectSource:
        self._sources = [s for s in self._sources if s.name != source.name]
        self._sources.append(source)
        return source

    @property
    def detectors(self) -> list[Detector]:
        return list(self._detectors)

    @property
    def sources(self) -> list[ProspectSource]:
        return list(self._sources)

    def inspect(self, prospect: Prospect, profile: NicheProfile) -> list[Finding]:
        """Run every detector and collect what they found.

        One detector failing does not abandon the prospect -- the others may
        still have something substantiated to say. The failure is raised only if
        *nothing* succeeded, because then "no findings" would be a lie.
        """
        if not self._detectors:
            raise NoDetectorAvailable(f"no detector registered for {INSPECT}")

        findings: list[Finding] = []
        failures: list[str] = []
        for detector in self._detectors:
            try:
                findings.extend(detector.inspect(prospect, profile))
            except Exception as error:  # noqa: BLE001 — a detector must not take the run down
                failures.append(f"{detector.name}: {error}")

        if failures and len(failures) == len(self._detectors):
            raise DetectorError("; ".join(failures))
        return findings

    def discover(self, profile: NicheProfile, limit: int) -> list[Prospect]:
        if not self._sources:
            raise NoDetectorAvailable(f"no source registered for {DISCOVER}")
        found: list[Prospect] = []
        for source in self._sources:
            if len(found) >= limit:
                break
            found.extend(source.discover(profile, limit - len(found)))
        return found[:limit]

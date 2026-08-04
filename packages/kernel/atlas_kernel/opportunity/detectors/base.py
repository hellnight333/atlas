"""What a detector is, and the registry that keeps them disposable.

Detection is capability-based for the same reason rendering is: the kernel asks
for ``opportunity.inspect`` and never learns which detector answered. Swapping
one is a registration change and nothing downstream notices.

Two capabilities exist:

* ``opportunity.discover`` -- produce candidate businesses for a niche.
* ``opportunity.inspect`` -- inspect one business and return evidenced findings.

A detector's only contract is that everything it returns carries evidence. That
is enforced by ``Finding`` itself rather than by anything here, so a detector
cannot cut the corner even by accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..identity import BusinessIndex
from ..models import Business, Finding, NicheProfile

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
    """Inspects one business and reports what is wrong with evidence."""

    @property
    def name(self) -> str: ...

    def inspect(self, business: Business, profile: NicheProfile) -> list[Finding]: ...


@runtime_checkable
class BusinessSource(Protocol):
    """Produces candidate businesses for a niche.

    **Discovery is multi-source by construction, not seed-list-with-extras.**
    The MVP registers only a seed list, but nothing here treats that as the
    normal case: the registry queries every registered source, resolves the
    results against each other, and a source that returns nothing is
    unremarkable. Adding Google Maps, a directory scrape or a data API is a
    registration, and no caller changes.

    That distinction is the reason ``discover`` takes a profile rather than a
    list of names. A source is asked *what businesses match this niche and
    geography*, which a directory can answer autonomously and a seed list
    answers from a file. If the signature took the candidates as input, the
    seed-list assumption would be baked into the protocol and every autonomous
    source would have to fight it.
    """

    @property
    def name(self) -> str: ...

    def discover(self, profile: NicheProfile, limit: int) -> list[Business]: ...


@dataclass
class DiscoveryResult:
    """What a discovery run produced, including what it could not do.

    A bare list of businesses would hide the two things most worth knowing: that
    a source was down, and that two records look like the same company without
    enough agreement to merge them. Both are reported rather than swallowed —
    a run that quietly covered half the sources still looks successful otherwise.
    """

    businesses: list[Business] = field(default_factory=list)
    #: Sightings folded into an existing record on a strong key match.
    duplicates_merged: int = 0
    #: Same name and place, nothing stronger agreeing. For a human, never merged.
    possible_duplicates: list[tuple[Business, Business]] = field(default_factory=list)
    #: Sources that raised, by name. Empty on a clean run.
    source_failures: dict[str, str] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.businesses)

    def __iter__(self):
        return iter(self.businesses)


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
        self._sources: list[BusinessSource] = []

    def register_detector(self, detector: Detector) -> Detector:
        self._detectors = [d for d in self._detectors if d.name != detector.name]
        self._detectors.append(detector)
        return detector

    def register_source(self, source: BusinessSource) -> BusinessSource:
        self._sources = [s for s in self._sources if s.name != source.name]
        self._sources.append(source)
        return source

    @property
    def detectors(self) -> list[Detector]:
        return list(self._detectors)

    @property
    def sources(self) -> list[BusinessSource]:
        return list(self._sources)

    def inspect(self, business: Business, profile: NicheProfile) -> list[Finding]:
        """Run every detector and collect what they found.

        One detector failing does not abandon the business -- the others may
        still have something substantiated to say. The failure is raised only if
        *nothing* succeeded, because then "no findings" would be a lie.
        """
        if not self._detectors:
            raise NoDetectorAvailable(f"no detector registered for {INSPECT}")

        findings: list[Finding] = []
        failures: list[str] = []
        for detector in self._detectors:
            try:
                findings.extend(detector.inspect(business, profile))
            except Exception as error:  # noqa: BLE001 — a detector must not take the run down
                failures.append(f"{detector.name}: {error}")

        if failures and len(failures) == len(self._detectors):
            raise DetectorError("; ".join(failures))
        return findings

    def discover(self, profile: NicheProfile, limit: int) -> DiscoveryResult:
        """Ask every source, and resolve the answers against each other.

        Two sources will report the same clinic — that is the normal case once
        discovery is autonomous, not an edge case. Resolving here rather than at
        write time matters: an unresolved duplicate would be inspected twice,
        counted twice in the funnel, and eventually contacted twice.

        A source that fails does not end the run. Discovery from four sources
        where one is down should return three sources' worth of businesses, not
        an exception; the failure is reported alongside the results so a
        silently-degraded run is still visibly degraded.
        """
        if not self._sources:
            raise NoDetectorAvailable(f"no source registered for {DISCOVER}")

        index = BusinessIndex()
        failures: dict[str, str] = {}
        duplicates = 0

        for source in self._sources:
            if len(index.businesses) >= limit:
                break
            try:
                candidates = source.discover(profile, limit)
            except Exception as error:  # noqa: BLE001 — one bad source is not a dead run
                failures[source.name] = str(error)
                continue
            for candidate in candidates:
                if len(index.businesses) >= limit:
                    break
                tagged = candidate.model_copy(
                    update={"sources": candidate.sources or [source.name]}
                )
                _, is_new = index.resolve(tagged)
                if not is_new:
                    duplicates += 1

        return DiscoveryResult(
            businesses=index.businesses[:limit],
            duplicates_merged=duplicates,
            possible_duplicates=index.possible_duplicates(),
            source_failures=failures,
        )

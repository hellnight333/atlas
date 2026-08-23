"""Asking an assistant what it says about a business, behind an adapter.

`ai_visibility` is UNKNOWN on every roadmap Qevik has ever produced, because
nothing could answer it. This is the boundary that will, and it is written so
that the absence of a credential is an ordinary state rather than a failure:
the interface exists, a deterministic local provider satisfies it for tests, and
only the real network call is `PENDING_CREDENTIAL`.

The one rule that outranks the rest here: **a mention is not a rank.** An
assistant naming a business tells you it named it, and nothing about position.
Engines that genuinely return a rank set `position_available`; everything else
leaves `position` as `None`, and `AIVisibilityObservation` refuses a position
without the flag. Converting a mention into a "#3 ranking" would invent a number
the customer will eventually check against reality.
"""

from __future__ import annotations

import hashlib
from typing import Protocol, runtime_checkable

from ..measurement.models import AIVisibilityObservation, Confidence

#: The integration id this boundary belongs to, so the credential centre and
#: the provider agree on one name.
INTEGRATION = "ai-visibility"


class ProviderUnavailable(RuntimeError):
    """No credential, or the provider refused. Never a finding about the business.

    Distinct from "not mentioned" on purpose: an engine we could not ask has
    established nothing, and recording it as an absence would manufacture a
    weakness out of our own outage.
    """


@runtime_checkable
class VisibilityProvider(Protocol):
    """Somewhere a query can be asked and an answer observed."""

    @property
    def name(self) -> str: ...

    @property
    def supplies_position(self) -> bool:
        """True only for engines that genuinely return a rank."""
        ...

    def ask(self, query: str, *, business_name: str) -> AIVisibilityObservation:
        """Ask once. Raise `ProviderUnavailable` rather than inventing a miss."""
        ...


class LocalFixtureProvider:
    """A deterministic stand-in, for tests and for local development.

    Deliberately **not** a simulator of what an assistant would say. It answers
    from an explicit fixture, so a test that asserts "mentioned" is asserting
    something the test itself set up rather than something this class decided.
    A provider that guessed plausibly would make every test a test of the guess.
    """

    def __init__(self, *, name: str = "local-fixture",
                 mentions: dict[str, bool] | None = None,
                 citations: dict[str, str] | None = None,
                 supplies_position: bool = False,
                 positions: dict[str, int] | None = None,
                 unavailable: bool = False) -> None:
        self._name = name
        self._mentions = dict(mentions or {})
        self._citations = dict(citations or {})
        self._supplies_position = supplies_position
        self._positions = dict(positions or {})
        self._unavailable = unavailable

    @property
    def name(self) -> str:
        return self._name

    @property
    def supplies_position(self) -> bool:
        return self._supplies_position

    def ask(self, query: str, *, business_name: str) -> AIVisibilityObservation:
        if self._unavailable:
            raise ProviderUnavailable(
                f"{self._name} could not be reached, so nothing was established "
                "about this query. This is our outage, not a finding.")
        position = self._positions.get(query) if self._supplies_position else None
        return AIVisibilityObservation(
            engine=self._name, query=query,
            mentioned=self._mentions.get(query),
            cited=bool(self._citations.get(query)) if query in self._citations else None,
            citation_url=self._citations.get(query, ""),
            position=position,
            position_available=self._supplies_position,
            confidence=Confidence.HIGH)


class PendingCredentialProvider:
    """The shape a real engine takes before anybody has connected it.

    Registered so the system can name the engine, say what it would do and what
    it needs — and refuse cleanly — rather than the engine simply being absent
    and the gap being invisible.
    """

    def __init__(self, name: str, *, credential: str,
                 supplies_position: bool = False) -> None:
        self._name = name
        self.credential = credential
        self._supplies_position = supplies_position

    @property
    def name(self) -> str:
        return self._name

    @property
    def supplies_position(self) -> bool:
        return self._supplies_position

    def ask(self, query: str, *, business_name: str) -> AIVisibilityObservation:
        raise ProviderUnavailable(
            f"{self._name} is not connected. Add {self.credential} to collect "
            "AI visibility from it. Until then this engine establishes nothing, "
            "which is different from the business not being mentioned.")


def queries_for(business_name: str, *, category: str = "",
               geography: str = "") -> tuple[str, ...]:
    """The questions worth asking about a business.

    Built from what is known rather than from a template with the name dropped
    in: a business with no recorded category gets fewer questions, not invented
    ones. Deterministic, so the same business is asked the same things every
    time and two readings are comparable.
    """
    name = business_name.strip()
    if not name:
        return ()
    asked = [f"What is {name}?", f"Is {name} any good?"]
    if category:
        where = f" in {geography}" if geography else ""
        asked.append(f"Best {category}{where}")
        asked.append(f"Who should I use for {category}{where}?")
    if geography:
        asked.append(f"{name} {geography}")
    # Stable order, no duplicates.
    return tuple(dict.fromkeys(asked))


def fingerprint(queries: tuple[str, ...]) -> str:
    """Identity of a question set, so two sweeps can be compared like for like.

    A sweep that asked different questions is not a later reading of the same
    thing, and comparing them would report a change that was ours.
    """
    joined = "\n".join(sorted(queries))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]

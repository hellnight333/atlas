"""Niche profiles — one niche, one geography, as data.

Changing target market is editing one of these. Nothing anywhere in this package
branches on a niche; if something ever needs to, it belongs here as a field.

**The profile below is a worked example so the pipeline runs end to end. It is
not a recommendation.** Which niche and which geography to open with is a market
judgement, and Ayoub's read on the GCC beats anything inferable from code. It is
one file to change and no other file moves when it does.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import FindingKind, NicheProfile


@dataclass(frozen=True)
class ContactPolicy:
    """How often a business may be contacted, and nothing else.

    Deliberately smaller than `NicheProfile`. That type requires an `offer` and a
    `geography` — real commercial terms — and using one as "the default policy"
    would smuggle in an offer nobody agreed while pretending to state only a
    cooldown.

    `OutreachService` reads `contact_cooldown_days` and `id`. `NicheProfile`
    satisfies the same shape, so a niche that declares its own cooldown keeps
    overriding this without either type knowing about the other.
    """

    id: str
    contact_cooldown_days: int


#: **A commercial decision, taken by the owner on 2026-08-30, not a technical
#: default.**
#:
#: Fourteen days between contacting the same business. It is recorded here, in
#: data, with its date and its source, because a cooldown decides how often a
#: stranger is written to — and a number chosen inside a route, or inherited
#: from whichever profile happened to be registered, is a commercial policy
#: nobody can find and nobody remembers agreeing to.
#:
#: Changing it is editing this line. Widening it is safe; shortening it is a
#: decision about how often somebody who has not replied hears from us again.
INITIAL_CONTACT_POLICY = ContactPolicy(
    id="initial-commercial-2026-08",
    contact_cooldown_days=14,
)

#: A concrete profile so the pipeline is runnable today.
#:
#: The threshold is set so that a single low-severity finding -- a missing h1, no
#: structured data -- cannot qualify anyone. Contacting a business about a
#: cosmetic defect is how an outreach engine becomes spam regardless of how many
#: gates sit in front of it, so the floor is enforced in data rather than left to
#: whoever runs the pipeline.
EXAMPLE_PROFILE = NicheProfile(
    id="example-uae-services",
    name="Example — service businesses (placeholder, pending Ayoub's choice)",
    geography="United Arab Emirates",
    offer="A fast, mobile-first website with the business's details published "
    "where search engines can read them.",
    estimated_value=None,  # unknown until priced; never guessed
    currency="AED",
    qualify_threshold=7.5,
    ignore_kinds=[],
    contact_cooldown_days=90,
    notes=(
        "Placeholder profile. Replace id, name, geography, offer and pricing with "
        "the real target market before any outreach. Nothing else needs to change."
    ),
)


#: Profiles Atlas knows about, by id.
PROFILES: dict[str, NicheProfile] = {EXAMPLE_PROFILE.id: EXAMPLE_PROFILE}


def get_profile(profile_id: str) -> NicheProfile:
    try:
        return PROFILES[profile_id]
    except KeyError:  # pragma: no cover - defensive
        known = ", ".join(sorted(PROFILES)) or "none registered"
        raise KeyError(f"unknown niche profile {profile_id!r} (known: {known})") from None


def contact_policy_for(niche: str = "") -> ContactPolicy | NicheProfile:
    """Which contact policy governs this business.

    A registered niche profile wins when the mission names one, because a niche
    that has stated its own cadence has stated it deliberately. Otherwise the
    declared initial policy applies.

    **`signal.scope` is not a niche.** It holds the audited URL for a
    `weak_web_presence` signal and the source name for `missing_service` — the
    first implementation of this looked a niche up by scope and could never have
    matched. Callers pass a niche if they have one; today the mission pipeline
    has none, which is why the initial policy is what governs it.

    Never returns `EXAMPLE_PROFILE`. That profile exists so the pipeline is
    runnable and its own docstring says it is not a recommendation; letting it
    supply a real cooldown because it is the only one registered would be
    inheriting a commercial term from a placeholder.
    """
    found = PROFILES.get(niche.strip()) if niche.strip() else None
    if found is not None and found.id != EXAMPLE_PROFILE.id:
        return found
    return INITIAL_CONTACT_POLICY


def register_profile(profile: NicheProfile) -> NicheProfile:
    PROFILES[profile.id] = profile
    return profile


__all__ = ["EXAMPLE_PROFILE", "INITIAL_CONTACT_POLICY", "PROFILES",
           "ContactPolicy", "FindingKind", "contact_policy_for",
           "get_profile", "register_profile"]

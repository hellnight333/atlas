"""Niche profiles — one niche, one geography, as data.

Changing target market is editing one of these. Nothing anywhere in this package
branches on a niche; if something ever needs to, it belongs here as a field.

**The profile below is a worked example so the pipeline runs end to end. It is
not a recommendation.** Which niche and which geography to open with is a market
judgement, and Ayoub's read on the GCC beats anything inferable from code. It is
one file to change and no other file moves when it does.
"""

from __future__ import annotations

from .models import FindingKind, NicheProfile

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


def register_profile(profile: NicheProfile) -> NicheProfile:
    PROFILES[profile.id] = profile
    return profile


__all__ = ["EXAMPLE_PROFILE", "PROFILES", "FindingKind", "get_profile", "register_profile"]

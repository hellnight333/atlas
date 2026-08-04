"""Recognising a company Atlas has already seen.

Autonomous discovery means several sources reporting the same businesses. Google
Maps and a directory will both return the same clinic, spelled differently, and
without identity resolution the funnel counts it twice, the cooldown protects
only one of the copies, and eventually someone receives two proposals from the
same sender in one week.

**The asymmetry that shapes everything here: merging two different companies is
much worse than failing to merge one company.** A missed merge costs a duplicate
row. A wrong merge sends a business a proposal citing findings about somebody
else's website — indefensible, and exactly the failure the evidence rule exists
to prevent. So matching is deliberately conservative and refuses to guess.

Keys come in two strengths:

* **Strong** — a domain, an email address, a phone number. Two companies do not
  share these. A match on any one of them is a match.
* **Weak** — name and geography. Two branches of the same clinic, or two
  unrelated companies with a common name, produce the same weak key. These are
  surfaced as *possible* duplicates for a human, and never merged automatically.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import Business

STRONG_PREFIXES = ("domain:", "email:", "phone:")
WEAK_PREFIXES = ("name:",)

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
#: Words that carry no identifying information and differ between sources.
_NOISE_WORDS = frozenset(
    {"llc", "fz", "fze", "ltd", "limited", "co", "company", "the", "and", "l l c"}
)


def normalise_domain(website: str | None) -> str | None:
    """The host, lowercased, without ``www.``.

    Deliberately **not** reduced to a registrable domain. Doing so would map
    every business hosted on a shared platform — ``one.wixsite.com`` and
    ``two.wixsite.com`` — onto a single key and merge unrelated companies. The
    full host is the conservative choice, and the cost of being conservative is
    a duplicate row rather than a misdirected proposal.
    """
    if not website:
        return None
    candidate = website.strip().lower()
    if not candidate:
        return None
    if "//" not in candidate:
        candidate = f"//{candidate}"
    host = urlparse(candidate).hostname
    if not host:
        return None
    host = host.removeprefix("www.").strip(".")
    return host or None


def normalise_email(email: str | None) -> str | None:
    if not email:
        return None
    value = email.strip().lower()
    return value if "@" in value else None


def normalise_phone(phone: str | None) -> str | None:
    """Digits only, with a leading ``00`` treated as ``+``.

    No attempt to infer a country code from a local number: guessing that a
    9-digit number is a UAE one would silently merge companies in different
    countries that happen to share the trailing digits.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("00"):
        digits = digits[2:]
    # Shorter than this is an extension or a fragment, not a contactable number.
    return digits if len(digits) >= 9 else None


def normalise_name(name: str, geography: str = "") -> str:
    """A slug of the name and place, with legal-form noise removed.

    "Al Noor Dental Clinic LLC" and "al-noor dental clinic" collapse together,
    which is right for *suggesting* a duplicate and not enough to act on.
    """
    words = [w for w in _NON_ALNUM.sub(" ", name.lower()).split() if w not in _NOISE_WORDS]
    place = _NON_ALNUM.sub("-", geography.lower()).strip("-")
    return f"{'-'.join(words)}|{place}"


def identity_keys(business: Business) -> list[str]:
    """Every key this business can be recognised by, strongest first."""
    keys: list[str] = []
    if domain := normalise_domain(business.website):
        keys.append(f"domain:{domain}")
    if email := normalise_email(business.email):
        keys.append(f"email:{email}")
    if phone := normalise_phone(business.phone):
        keys.append(f"phone:{phone}")
    keys.append(f"name:{normalise_name(business.name, business.geography)}")
    return keys


def strong_keys(keys: list[str]) -> set[str]:
    return {key for key in keys if key.startswith(STRONG_PREFIXES)}


def weak_keys(keys: list[str]) -> set[str]:
    return {key for key in keys if key.startswith(WEAK_PREFIXES)}


def with_identity(business: Business) -> Business:
    """Stamp a business with its keys."""
    return business.model_copy(update={"identity_keys": identity_keys(business)})


def is_same_business(left: Business, right: Business) -> bool:
    """True only on a strong key match.

    A shared name and city is not enough, however plausible it looks.
    """
    return bool(strong_keys(identity_keys(left)) & strong_keys(identity_keys(right)))


def is_possible_duplicate(left: Business, right: Business) -> bool:
    """Same name and place, nothing stronger agreeing.

    Worth a human's attention and nothing more. Two branches of one clinic and
    two unrelated companies with a common name are indistinguishable from here.
    """
    if is_same_business(left, right):
        return False
    return bool(weak_keys(identity_keys(left)) & weak_keys(identity_keys(right)))


class BusinessIndex:
    """In-memory resolution across a batch, so one discovery run self-dedupes.

    The repository does the same against everything stored. This exists because
    a single run of three sources will report the same clinic three times before
    anything is written, and resolving only at write time would mean three
    inspections of one website.
    """

    def __init__(self) -> None:
        self._by_strong_key: dict[str, Business] = {}
        self._businesses: list[Business] = []

    def resolve(self, business: Business) -> tuple[Business, bool]:
        """Return the canonical record and whether it is new."""
        stamped = with_identity(business)
        for key in strong_keys(set(stamped.identity_keys)):
            existing = self._by_strong_key.get(key)
            if existing is not None:
                merged = with_identity(existing.merged_with(stamped))
                self._replace(existing, merged)
                return merged, False

        self._businesses.append(stamped)
        for key in strong_keys(set(stamped.identity_keys)):
            self._by_strong_key[key] = stamped
        return stamped, True

    def _replace(self, old: Business, new: Business) -> None:
        self._businesses = [new if b.id == old.id else b for b in self._businesses]
        for key in strong_keys(set(new.identity_keys)):
            self._by_strong_key[key] = new

    @property
    def businesses(self) -> list[Business]:
        return list(self._businesses)

    def possible_duplicates(self) -> list[tuple[Business, Business]]:
        """Pairs a human might want to look at. Never merged automatically."""
        pairs: list[tuple[Business, Business]] = []
        for index, left in enumerate(self._businesses):
            for right in self._businesses[index + 1 :]:
                if is_possible_duplicate(left, right):
                    pairs.append((left, right))
        return pairs

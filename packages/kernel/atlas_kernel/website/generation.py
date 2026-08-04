"""Content to artifact.

Thin on purpose. The theme decides markup, ``content.py`` decides what may be
said, and this decides neither — it seeds content from what Atlas already knows
about the business, hands it to a theme, and records where the result came from.

The seeding is the part worth reading. A ``Business`` record holds a name, a
phone number, an email and a geography that Atlas obtained from a real source,
so those become facts with ``BUSINESS_RECORD`` provenance rather than being
retyped by hand. Nothing else is inferred: a business with no recorded hours
gets a site with no opening hours on it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..opportunity.models import Business
from .content import ContactDetails, Fact, FactSource, SiteContent
from .themes import clean


@runtime_checkable
class Theme(Protocol):
    """Turns content into files. Must be deterministic."""

    def render(self, content: SiteContent) -> dict[str, str]: ...


class _ModuleTheme:
    """Adapts a theme module to the protocol, so themes stay plain modules."""

    def __init__(self, module) -> None:
        self._module = module

    @property
    def name(self) -> str:
        return f"{self._module.NAME}-v{self._module.VERSION}"

    def render(self, content: SiteContent) -> dict[str, str]:
        return self._module.render(content)


CLEAN = _ModuleTheme(clean)

#: Registered themes by name. One family, per the approved M015 scope.
THEMES: dict[str, _ModuleTheme] = {clean.NAME: CLEAN}


def get_theme(name: str = clean.NAME) -> _ModuleTheme:
    try:
        return THEMES[name]
    except KeyError:  # pragma: no cover - defensive
        known = ", ".join(sorted(THEMES))
        raise KeyError(f"unknown theme {name!r} (known: {known})") from None


def seed_content(business: Business) -> SiteContent:
    """The facts Atlas already holds about a company, as site content.

    Only what is recorded. A ``Business`` with no phone number produces content
    with no phone number — not a placeholder, and not a guess derived from the
    website domain.
    """
    return SiteContent(
        business_name=Fact(
            value=business.name,
            source=FactSource.BUSINESS_RECORD,
            note=f"business {business.id}",
        ),
        location=(
            Fact(
                value=business.geography,
                source=FactSource.BUSINESS_RECORD,
                note=f"business {business.id}",
            )
            if business.geography.strip()
            else None
        ),
        contact=ContactDetails(
            phone=(
                Fact(
                    value=business.phone,
                    source=FactSource.BUSINESS_RECORD,
                    note=f"business {business.id}",
                )
                if business.phone
                else None
            ),
            email=(
                Fact(
                    value=business.email,
                    source=FactSource.BUSINESS_RECORD,
                    note=f"business {business.id}",
                )
                if business.email
                else None
            ),
        ),
    )


def generate(content: SiteContent, *, theme: str = clean.NAME) -> tuple[dict[str, str], dict]:
    """Render content with a theme. Returns the files and their provenance.

    Provenance records what produced the artifact -- theme, version, and how
    many facts came from where -- so a rebuild can be compared like with like
    and a claim on a live site can be traced to its source without re-deriving
    anything.
    """
    renderer = get_theme(theme)
    files = renderer.render(content)
    provenance = {
        "theme": renderer.name,
        "facts": len(content.facts),
        "fact_sources": {
            source.value: len(content.sourced_from(source))
            for source in sorted(content.sources, key=lambda item: item.value)
        },
        "sections": {
            "about": content.about is not None,
            "services": len(content.services),
            "hours": len(content.hours.days),
            "contact": not content.contact.is_empty,
        },
    }
    return files, provenance

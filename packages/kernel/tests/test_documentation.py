"""Documentation and website validation.

Two failure modes this guards against:

* A link that goes nowhere. Easy to introduce, invisible until a user hits it.
* A document that claims a capability the code does not have. That is the
  failure this release cares most about, so the claims that matter most --
  no provider integrations, no API authentication -- are asserted directly
  against the source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DOCS = REPO / "docs"
WEBSITE = REPO / "website"

#: Documents this milestone promised an end user.
REQUIRED_DOCS = [
    "QUICK_START.md",
    "INSTALLATION.md",
    "USER_GUIDE.md",
    "ADMINISTRATOR_GUIDE.md",
    "TROUBLESHOOTING.md",
    "KEYBOARD_SHORTCUTS.md",
    "OVERVIEW.md",
    "PROVIDER_SETUP.md",
    "FAQ.md",
    "IMPLEMENTATION_STATUS.md",
    "KNOWN_ISSUES.md",
    "PRIVACY.md",
    "COMMUNITY.md",
]

REQUIRED_PAGES = [
    "index.html",
    "features.html",
    "studios.html",
    "enterprise.html",
    "docs.html",
    "download.html",
    "roadmap.html",
    "community.html",
    "privacy.html",
    "license.html",
]

MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
HREF = re.compile(r'href="([^"]+)"')
SRC = re.compile(r'src="([^"]+)"')


def _markdown_files() -> list[Path]:
    return sorted(
        [REPO / "README.md", REPO / "CONTRIBUTING.md", REPO / "CHANGELOG.md"]
        + [p for p in DOCS.glob("*.md")]
    )


# --------------------------------------------------------------------------
# Presence
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", REQUIRED_DOCS)
def test_required_document_exists_and_has_content(name: str) -> None:
    path = DOCS / name
    assert path.exists(), f"docs/{name} is missing"
    assert len(path.read_text(encoding="utf-8")) > 400, f"docs/{name} is a stub"


@pytest.mark.parametrize("name", REQUIRED_PAGES)
def test_required_website_page_exists(name: str) -> None:
    path = WEBSITE / name
    assert path.exists(), f"website/{name} is missing"
    body = path.read_text(encoding="utf-8")
    assert "<title>" in body and "</html>" in body


def test_website_assets_are_present() -> None:
    for asset in ("favicon-32.png", "favicon-180.png", "logo-512.png"):
        assert (WEBSITE / "assets" / asset).exists(), f"website asset {asset} is missing"
    assert (WEBSITE / "style.css").exists()


# --------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------


def test_every_relative_markdown_link_resolves() -> None:
    broken: list[str] = []
    for source in _markdown_files():
        for target in MARKDOWN_LINK.findall(source.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            resolved = (source.parent / target.split("#")[0]).resolve()
            if not resolved.exists():
                broken.append(f"{source.relative_to(REPO)} -> {target}")
    assert not broken, "broken relative links:\n  " + "\n  ".join(broken)


def test_every_website_link_resolves() -> None:
    broken: list[str] = []
    for page in WEBSITE.glob("*.html"):
        body = page.read_text(encoding="utf-8")
        for target in HREF.findall(body) + SRC.findall(body):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not (WEBSITE / target.split("#")[0]).exists():
                broken.append(f"{page.name} -> {target}")
    assert not broken, "broken website links:\n  " + "\n  ".join(broken)


def test_every_page_reaches_every_other_page() -> None:
    """A page nothing links to is a page nobody finds."""
    linked: set[str] = set()
    for page in WEBSITE.glob("*.html"):
        linked.update(
            t for t in HREF.findall(page.read_text(encoding="utf-8")) if t.endswith(".html")
        )
    unreachable = [p for p in REQUIRED_PAGES if p not in linked and p != "index.html"]
    assert not unreachable, f"unreachable pages: {unreachable}"


# --------------------------------------------------------------------------
# Honesty — claims checked against the code
# --------------------------------------------------------------------------


def test_documentation_states_that_providers_are_not_implemented() -> None:
    """The alpha's defining limit must be stated, not implied."""
    status = (DOCS / "IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    assert "not implemented" in status.lower()
    setup = (DOCS / "PROVIDER_SETUP.md").read_text(encoding="utf-8")
    assert "simulation" in setup.lower()


def test_the_provider_claim_is_still_true() -> None:
    """If a real adapter is ever added, this test fails and the docs get fixed.

    That is the point: the documentation claim is pinned to the code rather
    than to someone remembering to update it.
    """
    providers = (REPO / "packages/kernel/atlas_kernel/providers.py").read_text(encoding="utf-8")
    for sdk in ("import anthropic", "import openai", "from anthropic", "from openai"):
        assert sdk not in providers, (
            "A real provider SDK appeared in providers.py. "
            "docs/PROVIDER_SETUP.md and IMPLEMENTATION_STATUS.md now understate Atlas."
        )


def test_the_no_authentication_warning_is_present_everywhere_it_matters() -> None:
    for name in ("IMPLEMENTATION_STATUS.md", "KNOWN_ISSUES.md", "FAQ.md"):
        body = (DOCS / name).read_text(encoding="utf-8").lower()
        assert "authentication" in body, f"docs/{name} omits the API authentication warning"


def test_keyboard_shortcut_documentation_matches_the_code() -> None:
    """Only three shortcuts are bound. Documenting a fourth would teach a
    gesture that silently does nothing."""
    source = (REPO / "apps/desktop/src/hooks/useGlobalShortcuts.ts").read_text(encoding="utf-8")
    bound = set(re.findall(r"key\.toLowerCase\(\) === '(\w)'", source))
    documented = set(
        re.findall(r"Ctrl \+ (\w)", (DOCS / "KEYBOARD_SHORTCUTS.md").read_text(encoding="utf-8"))
    )
    assert {
        b.upper() for b in bound
    } == documented, f"shortcuts bound in code {bound} do not match those documented {documented}"


def test_no_document_promises_an_unbuilt_studio_as_present() -> None:
    """Video, Audio, Coding and Business studios do not exist. Any mention must
    be framed as planned."""
    guide = (DOCS / "USER_GUIDE.md").read_text(encoding="utf-8")
    for absent in ("Video Studio", "Audio Studio", "Coding Studio", "Business Studio"):
        assert absent not in guide, f"USER_GUIDE.md describes {absent}, which does not exist"


def test_the_website_carries_the_alpha_limitation_notice() -> None:
    """Somebody arriving at the site should not have to dig for the caveat."""
    for name in ("index.html", "features.html", "studios.html", "download.html"):
        body = (WEBSITE / name).read_text(encoding="utf-8")
        assert "no model provider integrations yet" in body, f"{name} omits the alpha notice"


def test_the_website_does_not_claim_atlas_is_open_source() -> None:
    """It is source-available. The distinction is legally meaningful."""
    for page in WEBSITE.glob("*.html"):
        body = page.read_text(encoding="utf-8").lower()
        if "open source" in body:
            assert (
                "not open source" in body or "source-available" in body
            ), f"{page.name} calls Atlas open source without qualification"


def test_version_is_consistent_across_the_site_and_the_code() -> None:
    from atlas_kernel.version import VERSION

    for page in ("index.html", "download.html"):
        body = (WEBSITE / page).read_text(encoding="utf-8")
        for found in re.findall(r"0\.\d+\.\d+-alpha\.\d+", body):
            assert found == VERSION, f"website/{page} cites {found}, code is {VERSION}"


def test_no_placeholder_text_anywhere_in_the_published_material() -> None:
    offenders: list[str] = []
    for path in list(WEBSITE.glob("*.html")) + _markdown_files():
        body = path.read_text(encoding="utf-8")
        for marker in ("lorem ipsum", "TKTK", "FIXME", "XXX_", "Coming soon!"):
            if marker.lower() in body.lower():
                offenders.append(f"{path.name}: {marker}")
    assert not offenders, f"placeholder text found: {offenders}"

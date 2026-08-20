#!/usr/bin/env python3
"""Detect portfolio samples that are one template wearing different colours.

Written because that is exactly what the first five samples were: same header,
same hero, same card grid, same section order, same footer, different hex values.
A prospect scrolling that does not see range — they see a theme picker.

So similarity is measured structurally rather than by eye. Each page is reduced
to a fingerprint of the decisions a visitor actually perceives, and every pair is
compared. Colour and copy are deliberately excluded from the fingerprint: they
are the two things that differ in a reskin, and counting them would let the
failure this exists to catch score as a pass.

    differentiation.py FILE [FILE ...]
    differentiation.py --dir apps/samples/dist
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path

#: Above this, two samples are too alike to sit in the same portfolio.
THRESHOLD = 0.62


@dataclass(frozen=True)
class Fingerprint:
    """What a visitor perceives, minus colour and words."""

    name: str
    nav: str
    hero: str
    sections: tuple[str, ...]
    typography: tuple[str, ...]
    layout: frozenset[str]
    cta: str
    footer: str
    interaction: frozenset[str]
    #: The components a sample actually uses. Two pages can share a navigation
    #: pattern and still be different products if one is built from filters and
    #: a cart and the other from a configurator and a comparison matrix.
    vocabulary: frozenset[str]
    #: How much is on the page. A single-screen estimator and a nine-section
    #: brochure are different products even where every other signal agrees.
    density: str

    def compare(self, other: Fingerprint) -> tuple[float, list[str]]:
        """How alike, and in which specific ways."""
        same: list[str] = []
        checks = 0

        def check(label: str, mine: object, theirs: object) -> None:
            nonlocal checks
            checks += 1
            if mine == theirs:
                same.append(label)

        check("navigation pattern", self.nav, other.nav)
        check("hero structure", self.hero, other.hero)
        check("primary CTA placement", self.cta, other.cta)
        check("footer structure", self.footer, other.footer)

        # Section order matters more than section presence: two sites can both
        # have a contact section without feeling the same, but the same run of
        # sections in the same order is one page shape.
        checks += 1
        if self.sections == other.sections:
            same.append("identical section order")
        elif len(set(self.sections) & set(other.sections)) >= max(
            3, min(len(self.sections), len(other.sections)) - 1
        ):
            same.append("near-identical section set")

        checks += 1
        if self.typography == other.typography:
            same.append("identical type stack")

        checks += 1
        overlap = self.layout & other.layout
        if overlap and len(overlap) / max(len(self.layout | other.layout), 1) > 0.7:
            same.append(f"same layout devices ({', '.join(sorted(overlap))})")

        checks += 1
        if self.interaction == other.interaction:
            same.append("same interaction model")

        # Component vocabulary is the strongest single signal of "different
        # product", so it is weighted as two checks rather than one.
        checks += 2
        shared_vocab = self.vocabulary & other.vocabulary
        union = self.vocabulary | other.vocabulary
        if union and len(shared_vocab) / len(union) > 0.6:
            same.append(f"same component vocabulary ({', '.join(sorted(shared_vocab))})")
            same.append("component vocabulary overlap")

        checks += 1
        if self.density == other.density:
            same.append(f"same page density ({self.density})")

        return len(same) / checks, same


def strip_comments(html: str) -> str:
    """Comments describe intent; the fingerprint must measure what is rendered.

    The Pulse sample's stylesheet opens with "no hero, no card grid" explaining
    what it deliberately omits — and the first version of this function read that
    as evidence of a hero. A checker that scores prose about the design instead
    of the design is worse than none.
    """
    without_html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"/\*.*?\*/", " ", without_html, flags=re.S)


def fingerprint(name: str, html: str) -> Fingerprint:
    body = strip_comments(html).lower()

    # --- navigation ---
    #
    # "<nav> absent" is not one thing. A page with a fixed header carrying a
    # brand and a phone number reads completely differently from one that opens
    # straight into full-bleed content with no chrome at all, and the first
    # version of this scored both as "none".
    has_links = len(re.findall(r'<header[^>]*>.*?</header>', body, re.S)) and re.search(
        r"<header[^>]*>.*?<a[^>]*>.*?<a[^>]*>", body, re.S
    )
    if "<aside" in body or 'class="sidebar' in body:
        nav = "sidebar"
    elif re.search(r'position:\s*sticky[^}]*top:\s*0', body) and "<nav" in body:
        nav = "sticky-top-bar"
    elif "<nav" in body and has_links:
        nav = "static-link-bar"
    elif "<nav" in body:
        nav = "minimal-nav"
    elif "<header" in body:
        nav = "header-no-nav"
    else:
        nav = "chromeless"

    # --- hero ---
    if "hero" not in body:
        hero = "no-hero"
    elif re.search(r'grid-template-columns:[^;]*(1\.?\d*fr\s+\.?\d*\.?\d*fr)', body):
        hero = "split-column"
    elif "100vh" in body or "min-height:80vh" in body or "min-height: 80vh" in body:
        hero = "full-viewport"
    elif re.search(r'<h1[^>]*>', body) and "background-image" in body:
        hero = "image-backed"
    else:
        hero = "stacked-text"

    # --- section order, by landmark headings ---
    sections = tuple(
        re.sub(r"[^a-z ]", "", h).strip()[:22]
        for h in re.findall(r"<h2[^>]*>([^<]{2,40})</h2>", body)
    )

    # --- typography: the declared families, in order of first appearance ---
    # Custom properties count. Nearly every modern stylesheet declares its
    # stacks once as --sans/--serif and then writes font-family: var(--sans)
    # everywhere, so reading only font-family found nothing and scored two
    # completely different type treatments as "identical".
    families = []
    for match in re.findall(r"(?:font-family|--[\w-]*(?:sans|serif|mono|display|body|font)[\w-]*)\s*:\s*([^;}]+)", body):
        first = match.split(",")[0].strip().strip("\"'")
        if first and first not in families and not first.startswith("var("):
            families.append(first)
    typography = tuple(families[:3])

    # --- layout devices ---
    layout: set[str] = set()
    if re.search(r"grid-template-columns:\s*repeat\(auto-fit", body):
        layout.add("auto-fit card grid")
    if "position:fixed" in body.replace(" ", "") and "bottom:0" in body.replace(" ", ""):
        layout.add("sticky mobile bar")
    if "<table" in body:
        layout.add("data table")
    if "<svg" in body and ("polyline" in body or "<path" in body and "chart" in body):
        layout.add("chart")
    if "<details" in body:
        layout.add("accordion")
    if re.search(r"grid-column:\s*span", body) or "grid-area" in body:
        layout.add("asymmetric grid")
    if "aspect-ratio" in body:
        layout.add("media tiles")
    if "overflow-x:auto" in body.replace(" ", "") or "scroll-snap" in body:
        layout.add("horizontal scroller")

    # --- primary CTA placement ---
    if "sticky mobile bar" in layout:
        cta = "persistent-bottom-bar"
    elif re.search(r'<header[^>]*>.{0,900}?(class="[^"]*btn|<button)', body, re.S):
        cta = "in-header"
    elif re.search(r"hero.{0,1200}?(class=\"[^\"]*btn|<button)", body, re.S):
        cta = "in-hero"
    else:
        cta = "in-body"

    # --- footer ---
    if "<footer" not in body:
        footer = "none"
    elif re.search(r"footer.{0,600}?grid-template-columns", body, re.S):
        footer = "multi-column"
    else:
        footer = "single-line"

    # --- interaction model ---
    interaction: set[str] = set()
    if "addeventlistener" in body:
        interaction.add("scripted")
    if re.search(r"data-(step|filter|tab|category|panel)", body):
        interaction.add("stateful ui")
    if "<form" in body:
        interaction.add("form")
    if "<dialog" in body or "drawer" in body or "modal" in body:
        interaction.add("overlay")
    if not interaction:
        interaction.add("static")

    # --- component vocabulary -------------------------------------------
    vocabulary: set[str] = set()
    for token, present in (
        ("filters", bool(re.search(r'data-(filter|group)="(light|care|size|area|beds|deal)"', body))),
        ("cart", "basket" in body or "cart" in body),
        ("configurator", bool(re.search(r'data-(step|stage)', body))),
        # HomeFix computes a range from buttons and a counter with no <input>
        # anywhere, and the first version of this missed it entirely — reporting
        # the page's whole reason for existing as absent.
        ("estimator", "estimat" in body and bool(re.search(r"\baed\b|\bamount\b", body))),
        ("comparison matrix", bool(re.search(r"<table", body)) and "included" in body),
        ("pricing tiers", "pricing" in body and bool(re.search(r"tier|plan", body))),
        ("dashboard", "dashboard" in body or bool(re.search(r'class="kpis?"', body))),
        ("chart", "polyline" in body or "polygon" in body),
        ("detail overlay", bool(re.search(r"\.(detail|drawer)\b", body))),
        ("search", 'type="search"' in body or "seek" in body),
        ("menu list", "menu" in body and "course" in body),
        ("faq", "<details" in body),
        ("map link", "google.com/maps" in body),
        ("saved list", "saved" in body or "wishlist" in body),
        ("hours", "opening hours" in body or "hours" in body),
        ("form", "<form" in body or "request" in body and "<input" in body),
    ):
        if present:
            vocabulary.add(token)

    # --- density ----------------------------------------------------------
    words = len(re.findall(r"[a-z]{3,}", re.sub(r"<[^>]+>", " ", body)))
    density = "sparse" if words < 450 else "medium" if words < 1100 else "dense"

    return Fingerprint(
        name=name,
        nav=nav,
        hero=hero,
        sections=sections,
        typography=typography,
        layout=frozenset(layout),
        cta=cta,
        footer=footer,
        interaction=frozenset(interaction),
        vocabulary=frozenset(vocabulary),
        density=density,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--dir", type=Path)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    args = parser.parse_args(argv)

    paths = list(args.files)
    if args.dir:
        paths += sorted(args.dir.glob("*/index.html"))
    if not paths:
        print("nothing to compare", file=sys.stderr)
        return 1

    prints = [
        fingerprint(p.parent.name if p.name == "index.html" else p.stem,
                    p.read_text(encoding="utf-8"))
        for p in paths
    ]

    print(f"{'sample':<14} {'nav':<16} {'hero':<14} {'cta':<22} {'density':<8} vocabulary")
    print("-" * 118)
    for fp in prints:
        print(f"{fp.name:<14} {fp.nav:<16} {fp.hero:<14} {fp.cta:<22} {fp.density:<8} "
              f"{', '.join(sorted(fp.vocabulary))[:44]}")

    print()
    worst = 0.0
    failures = []
    for a, b in combinations(prints, 2):
        score, shared = a.compare(b)
        worst = max(worst, score)
        if score >= args.threshold:
            failures.append((a.name, b.name, score, shared))

    if failures:
        print(f"TOO SIMILAR — {len(failures)} pair(s) at or above {args.threshold:.2f}:")
        for left, right, score, shared in sorted(failures, key=lambda f: -f[2]):
            print(f"\n  {left}  vs  {right}   similarity {score:.2f}")
            for item in shared:
                print(f"    · {item}")
        print("\nRedesign one of each pair before calling the portfolio done.")
        return 1

    print(f"All {len(prints)} samples are structurally distinct. "
          f"Closest pair: {worst:.2f} (threshold {args.threshold:.2f}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

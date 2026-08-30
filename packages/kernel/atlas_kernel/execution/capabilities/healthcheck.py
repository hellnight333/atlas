"""A website health check the business owner can actually open and use.

Qevik holds 396 real audits. Each carries twenty observations, and each
observation already knows three things: what was looked for, what was found, and
**the evidence** — "no `tel:` link in the homepage HTML", not "poor contact
options". That is an unusually honest dataset and nothing gave it to the person
it is about.

So this is the digital product: one self-contained page, built from that
business's own audit, that says what was checked, what was found, what it costs
them, and how each claim was established.

## Why this one

Every other candidate needed something Qevik does not have. A price calculator
needs their prices; a booking tool needs their calendar; a branch finder needs
per-branch geodata. Each would have landed in `REQUIRES_CUSTOMER_INPUT` and
never executed. This needs nothing but the audit already in the ledger.

## The rule this product exists to keep

**Every claim shows its evidence, or it is not shown.** A health check that
asserts "no online booking" without saying how it looked is indistinguishable
from a sales pitch, and the recipient is entitled to check. `validate()` refuses
an artefact containing a claim with no evidence, and the executor calls it
before returning — a generated file nobody validated is not a product.

**An unread check is never drawn as a failure.** `status` is `present`,
`not_found`, or something else entirely — a timeout, a page that would not
parse. The third case is `NOT_VERIFIED`, and rendering it as a fault invents a
finding about a real business, in writing, in their name.

Self-contained by construction: no script src, no stylesheet link, no font
fetch. It is opened from a file, an email attachment, or a published URL, often
by somebody on a phone with a bad connection, and a page that needs a CDN to
render its own findings is a page that fails when it matters.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ...opportunity.models import Business
from ...opportunity.website_audit import FEATURE_NOTES

#: Categories in the order a business owner cares about them, not the order the
#: auditor happened to emit. Money first: a business nobody can phone loses the
#: enquiry today, a missing meta description costs a slow trickle.
CATEGORY_ORDER: tuple[str, ...] = (
    "conversion", "contact", "booking", "local_seo", "content", "trust",
    "mobile", "performance", "accessibility", "multilingual", "technical",
    "seo",
)

#: What each category is for, in the reader's terms. Every category the auditor
#: emits. Three were missing and rendered as raw
#: slugs — "accessibility", "mobile", "multilingual" — at the bottom of a page
#: sent to a business. A test now fails when the auditor gains a category this
#: has no sentence for, because the failure otherwise appears in the artefact.
CATEGORY_MEANING: dict[str, str] = {
    "conversion": "Turning a visitor into an enquiry",
    "contact": "Being reachable the way people actually get in touch",
    "booking": "Letting somebody commit without phoning",
    "local_seo": "Being found and driven to",
    "content": "Answering what people came to ask",
    "trust": "Reasons to believe you",
    "mobile": "Usable on a phone",
    "performance": "Loading before somebody gives up",
    "accessibility": "Usable by people who cannot see the screen",
    "multilingual": "Readable in the language your customers think in",
    "technical": "The basics browsers and search engines rely on",
    "seo": "Being found at all",
}


class Verdict(StrEnum):
    """Three states, drawn three ways.

    `NOT_VERIFIED` is not a soft failure. It means the check did not complete —
    a timeout, a page that would not parse — and presenting it as a fault puts
    an invented finding about a real business in writing.
    """

    GOOD = "CONFIRMED_PRESENT"
    MISSING = "CONFIRMED_ABSENT"
    UNKNOWN = "NOT_VERIFIED"


@dataclass(frozen=True)
class Check:
    """One thing that was looked for, and what was found."""

    feature: str
    category: str
    verdict: Verdict
    #: How it was established. Never empty for a rendered claim.
    evidence: str
    #: What it costs them, in their terms. Written by the auditor, not here.
    consequence: str = ""

    @property
    def label(self) -> str:
        return self.feature.replace("_", " ")


class NothingObserved(ValueError):
    """The audit recorded nothing, so there is no health check to build.

    A finding, not a failure. An empty report that says "everything looks fine"
    because nothing was examined is the worst possible artefact to put a
    business's name on.
    """


class Unevidenced(ValueError):
    """A claim was assembled with no evidence behind it.

    Raised by `validate()`, and the executor calls `validate()` before it
    returns. A health check whose claims cannot be checked is a sales document
    wearing the clothes of an audit.
    """


def _checks(research: dict) -> tuple[Check, ...]:
    """Every observation, as a check. Nothing is dropped and nothing is guessed.

    An observation whose status is neither `present` nor `not_found` becomes
    `NOT_VERIFIED` rather than being filtered out. Dropping it would quietly
    turn "we could not tell" into "we did not look", and the count at the top of
    the page would then be wrong about how much was examined.
    """
    found = []
    for observation in research.get("observations") or []:
        feature = str(observation.get("feature") or "").strip()
        if not feature:
            continue
        status = observation.get("status")
        verdict = (Verdict.GOOD if status == "present"
                   else Verdict.MISSING if status == "not_found"
                   else Verdict.UNKNOWN)
        # Evidence and consequence come from different places, on purpose.
        #
        # The evidence is an observation about *their* site and belongs to the
        # audit that made it. The consequence is Qevik's explanation of why it
        # matters — editorial, not observed — and is looked up fresh rather than
        # read out of the stored event.
        #
        # This is not tidiness. The audit's notes were written for dental
        # clinics and 396 stored audits carry them, including 40 retail ones:
        # replayed verbatim, this page tells Sony at the Dubai Mall that "a
        # patient in pain phones". Correcting the table fixed future audits and
        # could not fix the ones already recorded. Looking the sentence up now
        # fixes both, and a feature this build does not recognise gets no
        # consequence at all rather than an inherited one.
        known = FEATURE_NOTES.get(feature)
        found.append(Check(
            feature=feature,
            category=str(observation.get("category") or "technical"),
            verdict=verdict,
            evidence=str(observation.get("evidence") or "").strip(),
            consequence=known[1] if known else ""))
    return tuple(found)


def validate(checks: tuple[Check, ...]) -> None:
    """Refuse an artefact that cannot be checked by the person receiving it.

    Two rules, and both have a victim if broken:

    - **A confirmed claim with no evidence.** The recipient cannot verify it and
      Qevik cannot defend it. This is the difference between an audit and an
      assertion.
    - **Nothing observed at all.** A page saying a business is fine because
      nothing was examined is worse than no page.
    """
    if not checks:
        raise NothingObserved(
            "the audit recorded no observations, so there is nothing to report")
    unevidenced = [c.feature for c in checks
                   if c.verdict is not Verdict.UNKNOWN and not c.evidence]
    if unevidenced:
        raise Unevidenced(
            "these claims have no evidence behind them and would be published "
            f"as findings about a real business: {', '.join(sorted(unevidenced))}")


def _e(text: str) -> str:
    return html.escape(text or "", quote=True)


def render(*, business_name: str, checks: tuple[Check, ...], url: str = "",
           audited_at: str = "") -> str:
    """The page. Self-contained, printable, and legible on a phone."""
    missing = [c for c in checks if c.verdict is Verdict.MISSING]
    good = [c for c in checks if c.verdict is Verdict.GOOD]
    unknown = [c for c in checks if c.verdict is Verdict.UNKNOWN]

    by_category: dict[str, list[Check]] = {}
    for check in checks:
        by_category.setdefault(check.category, []).append(check)
    ordered = sorted(by_category, key=lambda c: (
        CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else len(CATEGORY_ORDER), c))

    def row(check: Check) -> str:
        tone = {"CONFIRMED_PRESENT": "good", "CONFIRMED_ABSENT": "missing",
                "NOT_VERIFIED": "unknown"}[check.verdict.value]
        word = {"CONFIRMED_PRESENT": "Found", "CONFIRMED_ABSENT": "Not found",
                "NOT_VERIFIED": "Could not check"}[check.verdict.value]
        return f"""      <details class="check {tone}">
        <summary><span class="mark">{_e(word)}</span>
          <span class="what">{_e(check.label)}</span></summary>
        <div class="body">
          {f'<p class="why">{_e(check.consequence)}</p>' if check.consequence else ''}
          {f'<p class="ev">How we checked: {_e(check.evidence)}</p>' if check.evidence
           else '<p class="ev">This check did not complete, so nothing is claimed.</p>'}
        </div>
      </details>"""

    sections = "\n".join(
        f"""    <section>
      <h2>{_e(CATEGORY_MEANING.get(category, category.replace('_', ' ')))}</h2>
"""
        + "\n".join(row(c) for c in sorted(
            by_category[category],
            key=lambda c: (c.verdict is not Verdict.MISSING, c.feature)))
        + "\n    </section>"
        for category in ordered)

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Website check — {_e(business_name)}</title>
<style>
  :root {{ --ink:#16181d; --soft:#5c626e; --line:#e3e5ea; --page:#fbfbfc;
           --missing:#b23c17; --good:#1f7a4d; --unknown:#7a6a1f; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--page); color:var(--ink);
    font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:44rem; margin:0 auto; padding:2rem 1.1rem 4rem; }}
  h1 {{ font-size:1.55rem; line-height:1.2; margin:0 0 .3rem; }}
  .site {{ color:var(--soft); margin:0 0 1.6rem; word-break:break-all; }}
  .tally {{ display:flex; gap:.5rem; flex-wrap:wrap; margin:0 0 1.8rem; }}
  .tally div {{ flex:1 1 8rem; border:1px solid var(--line); background:#fff;
    border-radius:10px; padding:.7rem .8rem; }}
  .tally b {{ display:block; font-size:1.5rem; font-variant-numeric:tabular-nums; }}
  .tally span {{ color:var(--soft); font-size:.82rem; }}
  h2 {{ font-size:.78rem; text-transform:uppercase; letter-spacing:.09em;
    color:var(--soft); margin:2rem 0 .6rem; }}
  .check {{ border:1px solid var(--line); background:#fff; border-radius:10px;
    margin-bottom:.45rem; }}
  .check summary {{ cursor:pointer; padding:.7rem .85rem; display:flex; gap:.6rem;
    align-items:baseline; }}
  .check .mark {{ font-size:.7rem; text-transform:uppercase; letter-spacing:.06em;
    font-weight:700; flex:0 0 auto; }}
  .missing .mark {{ color:var(--missing); }}
  .good .mark {{ color:var(--good); }}
  .unknown .mark {{ color:var(--unknown); }}
  .missing {{ border-left:3px solid var(--missing); }}
  .good {{ border-left:3px solid var(--good); }}
  .unknown {{ border-left:3px dashed var(--unknown); }}
  .what {{ font-weight:600; }}
  .body {{ padding:0 .85rem .8rem .85rem; }}
  .why {{ margin:.1rem 0 .5rem; }}
  .ev {{ margin:0; color:var(--soft); font-size:.87rem; }}
  footer {{ margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line);
    color:var(--soft); font-size:.85rem; }}
  @media print {{ .check[open] .body, .check .body {{ display:block; }}
    body {{ background:#fff; }} }}
</style></head>
<body><main>
  <h1>What we found on your website</h1>
  <p class="site">{_e(business_name)}{f' — {_e(url)}' if url else ''}</p>

  <div class="tally">
    <div><b>{len(missing)}</b><span>things to fix</span></div>
    <div><b>{len(good)}</b><span>already working</span></div>
    <div><b>{len(unknown)}</b><span>we could not check</span></div>
  </div>

{sections}

  <footer>
    <p>Every line above says how it was checked. Nothing here is an opinion
    about your business — it is what an automated read of your homepage could
    and could not find{f', on {_e(audited_at)}' if audited_at else ''}.</p>
    <p>Where it says <strong>we could not check</strong>, the check did not
    complete. That is not a fault we found; it is one we cannot claim.</p>
  </footer>
</main></body></html>
"""


def build_health_check(*, business_name: str = "",
                       research: dict | None = None,
                       strengths: tuple[str, ...] = (),
                       business: Business | None = None,
                       **_: Any) -> tuple[dict[str, str], dict]:
    """The four arguments every executor gets, and one usable page out.

    Validated before it is returned. An artefact that has not been checked is
    not a product, and the check is the one that matters commercially: every
    claim carries the evidence behind it.
    """
    research = research or {}
    name = (business_name or (business.name if business else "")).strip()
    if not name:
        raise NothingObserved("a health check has to be about a named business")

    checks = _checks(research)
    validate(checks)

    url = str(research.get("url") or (business.website if business else "") or "")
    page = render(business_name=name, checks=checks, url=url,
                  audited_at=str(research.get("audited_at") or ""))

    return {"index.html": page}, {
        "capability": "offer-health-check",
        "business_name": name,
        "url": url,
        "checks": len(checks),
        "confirmed_absent": sum(1 for c in checks if c.verdict is Verdict.MISSING),
        "confirmed_present": sum(1 for c in checks if c.verdict is Verdict.GOOD),
        "not_verified": sum(1 for c in checks if c.verdict is Verdict.UNKNOWN),
        # Named so a reviewer can see the claims without opening the file.
        "claims": [
            {"feature": c.feature, "verdict": c.verdict.value,
             "evidence": c.evidence} for c in checks],
        "validated": True,
        "self_contained": True,
        "note": ("Built only from this business's own audit. Every claim "
                 "carries the evidence it rests on, and a check that did not "
                 "complete is reported as unchecked rather than as a fault."),
    }


__all__ = ["CATEGORY_MEANING", "CATEGORY_ORDER", "Check", "NothingObserved",
           "Unevidenced", "Verdict", "build_health_check", "render", "validate"]

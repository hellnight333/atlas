#!/usr/bin/env python3
"""Re-test, live, the specific claims an outreach message is about to make.

The stored audit is evidence of what a site looked like on the day it was read.
A message sent from it days later asserts that the site *is* that way now, which
is a different and stronger claim. Sites get fixed. A clinic that reads "your
site doesn't load" about a site that loads has learned only that we are careless.

So this does not re-run a general audit. It re-checks the exact sentences that
would be sent, and reports each one as CONFIRMED, REFUTED or NOT_VERIFIED —
never collapsing the last two, because "we could not reach it" and "it is
broken" are the same observation from our side and opposite claims from theirs.

Two safeguards worth naming:

- **A failed fetch is retried, and a still-failed fetch is NOT_VERIFIED.** One
  client's connectivity is not a fact about a server. Kings' whole audit is two
  zero-byte responses; that may be their site or it may be our egress.
- **HTTPS is checked by asking for HTTPS**, not by reading the stored URL. A
  business listed under `http://` very often serves `https://` perfectly well,
  and "you have no HTTPS" would then be false in the first sentence.

    verify_claims.py --top 8
    verify_claims.py --name Malabar --name Kings
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_kernel.browser import PlaywrightSession  # noqa: E402
from atlas_kernel.opportunity.models import BusinessEvent  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402

from score_prospects import SAMPLE_FOR, load, scored  # noqa: E402

CONFIRMED, REFUTED, UNKNOWN = "CONFIRMED", "REFUTED", "NOT_VERIFIED"

_ARABIC = re.compile(r"[؀-ۿ]")
_WHATSAPP = re.compile(r"wa\.me/|api\.whatsapp\.com|whatsapp://", re.I)
_TEL = re.compile(r'href=["\']tel:', re.I)
_MAPS = re.compile(r"google\.[a-z.]+/maps|goo\.gl/maps|maps\.app\.goo\.gl", re.I)
_HOURS = re.compile(
    r"opening hours|working hours|business hours|hours of operation"
    r"|\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s*[-–—:]\s*",
    re.I,
)
_FORM = re.compile(r"<form\b[^>]*>(?:(?!</form>).)*?<(?:input|textarea)\b", re.I | re.S)
_JSONLD = re.compile(r'type=["\']application/ld\+json', re.I)
_DESC = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'][^"\']{20,}', re.I)
_H1 = re.compile(r"<h1\b[^>]*>\s*\S", re.I)


def _alt_coverage(html: str) -> tuple[int, int]:
    """Content images carrying a non-empty alt, and how many there are."""
    images = re.findall(r"<img\b[^>]*>", html, re.I)
    with_alt = [i for i in images if re.search(r'alt=["\'][^"\']{2,}', i, re.I)]
    return len(with_alt), len(images)


@dataclass
class Claim:
    feature: str
    verdict: str
    note: str


def _host(url: str) -> str:
    return re.sub(r"^https?://", "", url or "").split("/")[0]


def _get(url: str, timeout: int = 20):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Qevik audit)"})
    return urllib.request.urlopen(request, timeout=timeout)


def https_available(url: str) -> tuple[str, str]:
    """Two separate questions, because they carry two different claims.

    "You have no HTTPS" and "your HTTPS is not enforced" are both about the
    padlock, but only one of them is usually true. Two of the first five
    prospects are listed under `http://` and serve HTTPS perfectly well; a
    message telling them they have no certificate would have been false in its
    opening sentence. What *is* true for them is that typing the domain still
    lands on the insecure version, which is what a visitor actually does, and
    which is what the browser labels "Not secure".
    """
    host = _host(url)
    if not host:
        return UNKNOWN, "no host to test"
    secure = f"https://{host}/"
    try:
        with _get(secure) as response:
            if not response.geturl().startswith("https://"):
                return CONFIRMED, f"{secure} redirects away from HTTPS to {response.geturl()}"
            served = f"HTTPS works ({response.status})"
    except ssl.SSLError as error:
        return CONFIRMED, f"no usable certificate — TLS failed: {str(error)[:60]}"
    except urllib.error.HTTPError as error:
        served = f"HTTPS terminates (HTTP {error.code})"
    except Exception as error:  # noqa: BLE001
        return CONFIRMED, f"no HTTPS response: {str(error)[:60]}"

    # HTTPS exists. Does an ordinary visitor ever reach it?
    try:
        with _get(f"http://{host}/") as response:
            landed = response.geturl()
        if landed.startswith("https://"):
            return REFUTED, f"{served} and http:// redirects to it — nothing to raise"
        return CONFIRMED, (f"{served}, but http:// stays on http ({landed[:48]}) — "
                           "visitors who type the domain get the insecure version")
    except Exception as error:  # noqa: BLE001
        return UNKNOWN, f"{served}; could not test the http:// redirect: {str(error)[:50]}"


def fetch(session: PlaywrightSession, url: str, attempts: int = 2) -> tuple[str, int, int, str]:
    """HTML, status, milliseconds, error — retried, because once is not evidence."""
    last = ""
    for attempt in range(attempts):
        started = time.monotonic()
        try:
            page = session.open(url)
            html = session.extract("document.documentElement.outerHTML") or ""
            return html, page.status, int((time.monotonic() - started) * 1000), ""
        except Exception as error:  # noqa: BLE001
            last = str(error).split("\n")[0][:100]
            if attempt + 1 < attempts:
                time.sleep(2)
    return "", 0, 0, last


def check(html: str, status: int, url: str, claims: list[str]) -> list[Claim]:
    """Re-test each intended claim against what the page actually contains."""
    out: list[Claim] = []
    text = html or ""
    for feature in claims:
        if feature == "https":
            verdict, note = https_available(url)
            out.append(Claim(feature, verdict, note))
            continue
        if not text:
            out.append(Claim(feature, UNKNOWN, "page did not load; nothing was read"))
            continue
        if feature == "image_alt_text":
            covered, total = _alt_coverage(text)
            if not total:
                out.append(Claim(feature, UNKNOWN, "no images on the homepage to judge"))
            elif covered < total / 2:
                out.append(Claim(feature, CONFIRMED,
                                 f"{covered} of {total} homepage images have alt text"))
            else:
                out.append(Claim(feature, REFUTED,
                                 f"{covered} of {total} homepage images already have alt text"))
            continue
        pattern = {
            "arabic": _ARABIC, "whatsapp": _WHATSAPP, "click_to_call": _TEL,
            "google_maps": _MAPS, "opening_hours": _HOURS, "contact_form": _FORM,
            "structured_data": _JSONLD, "meta_description": _DESC, "h1": _H1,
        }.get(feature)
        if pattern is None:
            out.append(Claim(feature, UNKNOWN, "no live test implemented for this feature"))
        elif pattern.search(text):
            out.append(Claim(feature, REFUTED, "found on the homepage now"))
        else:
            out.append(Claim(feature, CONFIRMED, "still not on the homepage"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=8)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args(argv)

    ranked = scored(load())
    if args.name:
        wanted = [n.lower() for n in args.name]
        targets = [s for s in ranked if any(w in s.name.lower() for w in wanted)]
    else:
        targets = ranked[: args.top]

    by_id = {c["id"]: c for c in load()}
    repo = OpportunityRepository()
    results = []

    session = PlaywrightSession(headless=True, viewport=(390, 844)).start()
    try:
        for score in targets:
            business = by_id[score.business_id]
            url = business["website"]
            html, status, elapsed, error = fetch(session, url)
            # Test what we would say. For an incomplete audit there is no claim
            # list, so the thing under test is simply whether the site responds.
            intended = list(score.speakable[:6])
            claims = check(html, status, url, intended)

            reachable = bool(html) and bool(status) and status < 400
            if not score.audit_complete:
                claims.insert(0, Claim(
                    "site_loads",
                    REFUTED if reachable else UNKNOWN,
                    f"it does load — HTTP {status} in {elapsed}ms" if reachable
                    else f"still no response after 2 attempts: {error or 'empty'}",
                ))
            if reachable and elapsed >= 6000:
                claims.insert(0, Claim(
                    "slow_homepage", CONFIRMED,
                    f"homepage took {elapsed / 1000:.1f}s to finish loading (measured now)"))

            results.append((score, url, status, elapsed, claims))
            print(f"\n{score.name}   [{score.total}/100]")
            print(f"  {url}")
            print(f"  live: HTTP {status} in {elapsed}ms" + (f"  ({error})" if error else ""))
            if not intended and score.audit_complete:
                print("  (no speakable weakness — nothing to verify)")
            for claim in claims:
                mark = {CONFIRMED: "✓", REFUTED: "✗", UNKNOWN: "?"}[claim.verdict]
                print(f"    {mark} {claim.verdict:<13} {claim.feature:<16} {claim.note}")
    finally:
        session.close()

    print("\n" + "=" * 78)
    print("✓ CONFIRMED   — the stored finding still holds; safe to say")
    print("✗ REFUTED     — they fixed it, or we were wrong. REMOVE from the message")
    print("? NOT_VERIFIED— unknown. Never state it as fact")

    if args.record:
        for score, url, status, elapsed, claims in results:
            repo.record_event(BusinessEvent(
                business_id=score.business_id, factory="sales_experiment",
                kind="claims_verified", actor="verify_claims.py",
                detail={
                    "url": url, "http_status": status, "load_ms": elapsed,
                    "claims": [{"feature": c.feature, "verdict": c.verdict, "note": c.note}
                               for c in claims],
                },
            ))
        print(f"\nrecorded {len(results)} claims_verified events")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

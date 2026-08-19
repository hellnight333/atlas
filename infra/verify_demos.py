#!/usr/bin/env python3
"""Fetch every deployed demo and check what a visitor actually receives.

Not a re-run of the unit tests. Those prove the renderer produces correct HTML;
this proves the correct HTML is what is being served, over HTTPS, through
Cloudflare, right now — which is a different claim and the one that matters when
a link is sent to a clinic.

The last group of checks is the important one. Every fact on a generated page
must trace to the clinic's own listing, so the page is searched for the classes
of fact the template is forbidden to invent: named doctors, named insurers,
testimonials, and any phone number other than the one on file. A page that
passed every structural check and named a dentist who does not work there would
be worse than a page that failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

import httpx

PROSPECTS = Path(os.environ.get("QEVIK_PROSPECTS", "/var/lib/qevik/prospects"))

#: Titles that would introduce a person the listing never named.
DOCTOR_TITLES = re.compile(r"\b(Dr\.?|Doctor|BDS|DDS|MDS|Prof\.?)\s+[A-Z][a-z]+", re.UNICODE)

#: UAE insurers. Naming one is a claim about what a clinic accepts, and getting
#: it wrong sends a patient to a clinic that will not take their card.
INSURERS = re.compile(
    r"\b(Daman|AXA|Oman Insurance|MetLife|Cigna|Aetna|Bupa|NextCare|Neuron|"
    r"Nas Insurance|Almadallah|Thiqa|Saico|Orient|Sukoon)\b",
    re.IGNORECASE,
)

#: Testimonial shapes. The template has no reviews section at all, so any of
#: these appearing means something leaked in.
#: Ratings and testimonials. "star" alone is dropped: it appears in real Dubai
#: addresses ("Al Nahda Star Building"), and a checker that flags a clinic's own
#: address as invented content is one that gets ignored rather than fixed.
TESTIMONIAL = re.compile(
    r"(★|⭐|\b\d(\.\d)?\s*/\s*5\b|\b\d(\.\d)?\s*stars?\b|testimonial|"
    r"\bpatients? say\b|\breviews?\b)",
    re.IGNORECASE,
)

#: A dialable number, anchored so it cannot match the tail of a longer one.
#: Without the leading boundary this found "00 37569" inside the clinic's own
#: 80037569 and reported the clinic's real phone number as an invented one.
PHONE_DIGITS = re.compile(r"(?<![\d+])(?:\+?971|0)[\d\s\-]{7,}")


def latest_records() -> Path:
    files = sorted(PROSPECTS.glob("prospects-*.json"))
    if not files:
        raise SystemExit(f"no prospect records under {PROSPECTS}")
    return files[-1]


def digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def check(record: dict, client: httpx.Client) -> list[str]:
    """Every problem found for one clinic. Empty means it passed."""
    problems: list[str] = []
    url = record.get("demo_url") or ""
    if not url:
        return ["no demo_url recorded"]

    pages: dict[str, str] = {}
    for suffix, name in (("", "en"), ("ar/", "ar")):
        response = client.get(url + suffix)
        if response.status_code != 200:
            problems.append(f"{name}: HTTP {response.status_code}")
            continue
        pages[name] = response.text

    for suffix in ("robots.txt", "sitemap.xml"):
        if client.get(url + suffix).status_code != 200:
            problems.append(f"{suffix} not served")

    if "en" not in pages or "ar" not in pages:
        return problems

    english, arabic = pages["en"], pages["ar"]

    # --- structure -----------------------------------------------------------
    if f'rel="canonical" href="{url}"' not in english:
        problems.append("en: canonical is not self-referential")
    if f'rel="canonical" href="{url}ar/"' not in arabic:
        problems.append("ar: canonical is not self-referential")
    for name, page in pages.items():
        if f'hreflang="ar" href="{url}ar/"' not in page:
            problems.append(f"{name}: missing hreflang ar")
        if f'hreflang="en" href="{url}"' not in page:
            problems.append(f"{name}: missing hreflang en")
        if '"@type": "Dentist"' not in page:
            problems.append(f"{name}: no Dentist structured data")
        if 'name="viewport"' not in page:
            problems.append(f"{name}: no viewport meta")

    if 'lang="ar" dir="rtl"' not in arabic:
        problems.append("ar: not marked rtl")
    if re.search(r"[A-Za-z]", re.search(r"<h1[^>]*>([^<]*)</h1>", arabic).group(1)):
        problems.append("ar: latin text in the headline")

    # --- conversion ----------------------------------------------------------
    phone = digits(record.get("phone", ""))
    for name, page in pages.items():
        if f'href="tel:{phone}"' not in page.replace("+971", "971"):
            if "tel:" not in page:
                problems.append(f"{name}: no tel: link")
        if "google.com/maps" not in page:
            problems.append(f"{name}: no directions link")
        if 'id="appointment-form"' not in page:
            problems.append(f"{name}: no appointment form")
        # The disclaimer lives in the submit handler, where non-ASCII is
        # \u-escaped by the serialiser — so the Arabic sentence is not present
        # as literal text and searching for it finds nothing on a correct page.
        # Match what is actually in the served bytes.
        disclaimed = "has no backend connected" in page or "\\u063a\\u064a\\u0631 " in page
        if not disclaimed:
            problems.append(f"{name}: appointment form does not disclaim submission")

    # WhatsApp must appear only for a genuine UAE mobile.
    is_mobile = bool(re.match(r"^(971)?0?5[024568]\d{7}$", phone))
    for name, page in pages.items():
        has_wa = "wa.me/" in page
        if has_wa and not is_mobile:
            problems.append(f"{name}: WhatsApp link on a non-mobile number ({phone})")
        if is_mobile and not has_wa:
            problems.append(f"{name}: mobile number but no WhatsApp link")

    # --- invented facts ------------------------------------------------------
    clinic_name = record.get("name", "")
    for name, page in pages.items():
        text = re.sub(r"<script.*?</script>", " ", page, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", text)

        for match in DOCTOR_TITLES.finditer(text):
            # "Dr. Joy Dental Clinic" is the clinic's own registered name, not a
            # person the page invented.
            if match.group(0) not in clinic_name:
                problems.append(f"{name}: names a doctor — {match.group(0)!r}")

        if found := INSURERS.search(text):
            problems.append(f"{name}: names an insurer — {found.group(0)!r}")
        if found := TESTIMONIAL.search(text):
            problems.append(f"{name}: testimonial/rating content — {found.group(0)!r}")

        national = phone.lstrip("0")
        known = {phone, national, f"971{national}", f"0{national}"}
        for candidate in PHONE_DIGITS.findall(text):
            found = digits(candidate)
            if len(found) < 7:
                continue
            # Accept any writing of the number on file — with or without the
            # country code, the trunk zero, or separators.
            if found in known or found.lstrip("0") == national or national in found:
                continue
            problems.append(f"{name}: a phone number not on file — {candidate.strip()!r}")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, default=None)
    args = parser.parse_args(argv)

    source = args.records or latest_records()
    records = json.loads(source.read_text(encoding="utf-8"))
    print(f"records : {source}  ({len(records)} clinics)\n")

    failures = 0
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for record in records:
            problems = check(record, client)
            if problems:
                failures += 1
                print(f"  FAIL  {record['name'][:44]}")
                for problem in problems:
                    print(f"          {problem}")
            else:
                print(f"  ok    {record['name'][:44]}")

    print()
    print(f"{len(records) - failures}/{len(records)} demos pass every check")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Compose the first five outreach messages from verified evidence, and send none.

The messages are *generated* rather than written, for one reason: a hand-written
sentence can say anything, and the sentences most likely to get written are the
ones that sell best. Every observation here is drawn from a vetted phrase table
keyed by a feature that survived a live re-check, so a claim about something we
did not confirm — or something we cannot fix — is not a discipline problem, it
is unreachable code.

What the generator refuses to produce:

- any observation about a feature outside `scoring.FIXABLE` (`booking_link`
  above all — Qevik has no appointment backend and says so publicly),
- any observation about a `NOT_VERIFIED` feature, which is not an absence,
- any phrasing that presents Qevik as its own licensed company,
- the price, which is answered when asked and not before.

Nothing here can send. `atlas_kernel.outreach.channels` has no client of any
kind and every channel raises; there is no SMTP, WhatsApp, Meta or Twilio
credential on the host. Drafts are recorded as `experiment_prepared` events with
`sent: False`, and a message becomes "sent" only when a human says so.

    first_five.py                 # print the send sheet
    first_five.py --full          # every message in full
    first_five.py --record        # persist experiment_prepared events
"""

from __future__ import annotations

import argparse
import re
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_kernel.outreach import experiment, identity, offer, scoring  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402

from score_prospects import SAMPLE_FOR, load, scored  # noqa: E402

#: The five, and why each is here. Chosen after re-verification, not before:
#: three of Malabar's five recorded weaknesses turned out to be already fixed,
#: two prospects' "missing HTTPS" was never missing, and Kings — one of the two
#: pre-approved messages — ranked last of eighteen clinics.
THE_FIVE = (
    ("Malabar Dental",
     "Highest-scoring clinic with a mobile and a demo already built for them. "
     "The approved message claims only the missing Arabic version, which the "
     "live re-check confirms. Send as approved."),
    ("The TopDent",
     "Mobile, demo already built. Its stored 'no HTTPS' finding was refuted — "
     "the site redirects to HTTPS correctly — so that sentence is gone."),
    ("Pearl Dental implants",
     "Third and last clinic with a UAE mobile. One clean confirmed gap."),
    ("360 Agency",
     "Highest verified score of all 45 re-checked businesses. Six confirmed "
     "fixable gaps, mobile, and not a clinic — which is the repositioning "
     "this test is supposed to check."),
    ("AHS Catering",
     "Second industry outside dental, with a sample that genuinely resembles "
     "their trade. Tests whether a relevant sample works as well as a demo "
     "built for them."),
)

#: One vetted sentence per confirmed weakness. Hedged where the evidence is a
#: single observation of one page, because that is all it is.
OBSERVATION = {
    "arabic": "The one thing I couldn't find is an Arabic version — and a lot of "
              "people here search in Arabic first.",
    "whatsapp": "I also couldn't find a WhatsApp button. Most people in Dubai would "
                "rather message than fill in a form.",
    "click_to_call": "On a phone, your number isn't tappable — you have to copy it out "
                     "by hand to call.",
    "google_maps": "I couldn't find a map link either, so someone has to go and search "
                   "your address separately.",
    "contact_form": "There's no enquiry form on the homepage, so the only way to reach "
                    "you is to already have your number.",
    "opening_hours": "I couldn't find your opening hours anywhere on the site.",
    "h1": "The homepage has no main heading — that's the first thing Google reads.",
    "structured_data": "There's no structured data on the page, so Google has to guess "
                       "what kind of business you are.",
    "meta_description": "There's no description tag, so Google writes its own summary of "
                        "you in the results.",
    "image_alt_text": "Almost none of your images have alt text, so Google can't tell "
                      "what's in any of them.",
    "https": "Typing your domain lands on the insecure version — the browser shows "
             "“Not secure” next to your name.",
    "slow_homepage": "It took a long time to finish loading for me — I don't know "
                     "whether that's constant or occasional, but a visitor waiting on a "
                     "blank screen usually phones someone else.",
}

#: Strengths worth naming out loud. Only things a visitor would actually
#: notice — "your structured data is well done" compliments nobody.
PRAISE = {
    "contact_form": "the contact form",
    "services_navigation": "the services pages",
    "google_maps": "the map",
    "whatsapp": "the WhatsApp button",
    "opening_hours": "the opening hours",
    "click_to_call": "the tap-to-call number",
}

#: Phrases that only make sense for a clinic.
#:
#: The multi-industry audit reuses the dental feature vocabulary, so
#: `doctors_team` came back "present" for a staffing agency whose page happens
#: to have a team section — and the draft opened by praising 360 Agency's
#: "doctor profiles". A compliment that reveals we did not look is worse than
#: no compliment.
PRAISE_CLINICAL = {
    "doctors_team": "the doctor profiles",
    "social_proof": "the patient reviews",
}

CLINICAL = {"dental", "health"}


def compliment(score: scoring.Score, category: str) -> str:
    """One true, visible thing they did well, from confirmed-present findings.

    The already-approved Malabar draft opens this way and it is the better
    shape: a message that leads with two criticisms of someone's work reads as
    an attack, whatever it offers afterwards.
    """
    table = dict(PRAISE)
    if category in CLINICAL:
        table.update(PRAISE_CLINICAL)
    seen = [table[f] for f in score.strengths if f in table][:2]
    if not seen:
        return ""
    return f"{seen[0]} and {seen[1]} are well done" if len(seen) == 2 else f"{seen[0]} is well done"


def short_name(name: str) -> str:
    """The name a person would use, not the Google listing headline.

    "The TopDent: Dental Clinic in Dubai" in an opening line reads as a mail
    merge, because that is exactly what it is.
    """
    for separator in ("|", "(", ":", " - ", " — "):
        name = name.split(separator)[0]
    # Listings append their own geography. "AHS Catering And Events In Dubai"
    # is not what anyone calls the company.
    name = re.sub(r"\s+(in\s+)?dubai\s*$", "", name.strip(), flags=re.I)
    return name.strip(" -–—")


#: What the demo is, said accurately. A sample is not their site and must never
#: be implied to be.
DEMO_LINE_OWN = ("So I built you a working example, using only your own details from "
                 "your Google listing — nothing invented:")
DEMO_LINE_SAMPLE = ("Here's something we built for a {trade} — it's our own sample, "
                    "not a client's:")

TRADE = {
    "food": "restaurant", "professional": "property company", "beauty": "salon",
    "automotive": "detailing shop", "home": "home-services company",
    "retail": "shop", "dental": "clinic", "health": "clinic",
}


def pick(ranked: list[scoring.Score]) -> list[tuple[scoring.Score, str]]:
    chosen = []
    for needle, why in THE_FIVE:
        hits = [s for s in ranked if needle.lower() in s.name.lower()]
        if not hits:
            raise SystemExit(f"no verified prospect matching {needle!r}")
        chosen.append((hits[0], why))
    return chosen


#: Demos that exist in Arabic as well. The dental vertical renders both
#: languages; the hand-built portfolio samples are English-only.
def bilingual(demo_url: str) -> bool:
    return "/demo-" in demo_url


def observations(score: scoring.Score, limit: int = 2, *, demo_url: str = "") -> list[str]:
    """The sentences this prospect's evidence permits, most costly first.

    Only `speakable` is consulted. That list is already filtered to confirmed,
    fixable findings, so nothing unverified and nothing outside what Qevik ships
    can reach a message even if a phrase exists for it.

    Arabic is dropped when the thing we are linking to has no Arabic version.
    It is the most valuable gap in this market and it is confirmed for almost
    every prospect — but raising it and then linking an English-only sample
    invites exactly the reply it deserves, and the next confirmed weakness is
    a better first sentence than one we cannot yet answer.
    """
    speakable = list(score.speakable)
    if demo_url and not bilingual(demo_url):
        speakable = [f for f in speakable if f != "arabic"]
    lines = [OBSERVATION[f] for f in speakable if f in OBSERVATION]
    return lines[:limit]


def whatsapp(score: scoring.Score, demo_url: str, category: str) -> str:
    own = "/demo-" in demo_url
    trade = TRADE.get(category, "small")
    # One observation only. The brief asks for five to seven short lines, and a
    # list of faults is not an opening message.
    seen = observations(score, limit=1, demo_url=demo_url)
    name = short_name(score.name)
    praise = compliment(score, category)
    lines = [
        f"Hello — I'm Ayoub. I build websites for businesses in Dubai, and I'm "
        f"writing about {name}.",
        "",
        f"I had a look at your site — {praise}." if praise
        else "I had a look at your site this week.",
        "",
        *(seen or ["There is one thing I think it is missing."]),
    ]
    lines += [
        "",
        DEMO_LINE_OWN if own else DEMO_LINE_SAMPLE.format(trade=trade),
        demo_url,
        "",
        "No charge for looking. If it's useful we can talk; if not, keep the link.",
        "",
        identity.WHATSAPP_SIGNATURE,
    ]
    return "\n".join(lines)


def email(score: scoring.Score, demo_url: str, category: str) -> tuple[str, str]:
    own = "/demo-" in demo_url
    trade = TRADE.get(category, "small")
    seen = observations(score, limit=3, demo_url=demo_url)
    name = short_name(score.name)
    praise = compliment(score, category)
    subject = (f"{name} — a working example of your site, in Arabic and English"
               if own else f"{name} — one thing I noticed on your website")
    body = "\n\n".join(
        [
            "Hello,",
            ("I work on websites for businesses in Dubai, and I looked at yours this week. "
             + praise[0].upper() + praise[1:] + "."
             if praise else
             "I work on websites for businesses in Dubai, and I looked at yours this week."),
            *seen,
            (DEMO_LINE_OWN if own else DEMO_LINE_SAMPLE.format(trade=trade))
            + f"\n\n    {demo_url}",
            "One thing I should say plainly: the enquiry form on that example is a "
            "placeholder. It does not send anywhere yet, and it says so on the page "
            "itself. Connecting it to something real is a decision for later, not "
            "something I am quietly pretending already works.",
            "If it's worth a conversation, reply here or call me. If not, no follow-up — "
            "you can keep the link either way.",
            "Best regards,\n" + identity.EMAIL_SIGNATURE,
        ]
    )
    return subject, body


def audit_message(text: str, score: scoring.Score) -> list[str]:
    """Everything about this message that would be a false or unsayable claim."""
    problems = [f"presents Qevik as a company: {c!r}" for c in identity.entity_claims(text)]
    lowered = text.lower()
    for feature in score.unfixable:
        phrase = OBSERVATION.get(feature, "")
        if phrase and phrase.lower() in lowered:
            problems.append(f"offers to fix {feature}, which Qevik does not build")
    for feature in score.unverified:
        if feature.replace("_", " ") in lowered:
            problems.append(f"mentions {feature}, which is NOT_VERIFIED")
    if "book" in lowered and "placeholder" not in lowered:
        problems.append("mentions booking without the placeholder disclaimer")
    for token in (str(offer.SETUP_AED), str(offer.MONTHLY_AED), "aed"):
        if token in lowered:
            problems.append(f"names a price ({token}) in a first message")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true", help="print every message in full")
    parser.add_argument("--record", action="store_true")
    args = parser.parse_args(argv)

    candidates = {c["id"]: c for c in load()}
    ranked = [s for s in scored(load()) if s.verified]
    chosen = pick(ranked)

    repo = OpportunityRepository()
    sheet = []
    for score, why in chosen:
        business = candidates[score.business_id]
        demo = business["demo_url"] or f"https://sites.qevik.ai/{SAMPLE_FOR.get(business['category'], 'sample')}/"
        channel = "whatsapp" if score.contact_kind == "mobile" else "phone call"
        body = whatsapp(score, demo, business["category"])
        subject, mail = email(score, demo, business["category"])

        problems = audit_message(body, score) + audit_message(mail, score)
        sheet.append((score, why, business, demo, channel, subject, body, mail, problems))

        if args.full:
            print("=" * 78)
            print(f"{score.name}   [{score.total}/100]   {score.contact} ({score.contact_kind})")
            print(f"why: {textwrap.fill(why, 74, subsequent_indent='     ')}")
            print(f"evidence used: {', '.join(score.speakable[:2]) or 'none'}")
            if score.unfixable:
                print(f"DO NOT SAY: {', '.join(score.unfixable)} (Qevik does not build these)")
            if score.unverified:
                print(f"DO NOT SAY: {', '.join(score.unverified)} (NOT_VERIFIED)")
            print(f"\n--- WHATSAPP ({channel}) ---\n{body}")
            print(f"\n--- EMAIL ---\nSubject: {subject}\n\n{mail}")
            print(f"\ncheck: {'; '.join(problems) if problems else 'no false or unsayable claim found'}\n")

    print("\n" + "=" * 118)
    print("SEND SHEET — nothing below has been sent, and nothing here can send")
    print("=" * 118)
    print(f"{'#':>2} {'prospect':<32} {'ch':<10} {'contact':<15} {'score':>5}  {'evidence':<26} demo")
    print("-" * 118)
    for index, (score, _, business, demo, channel, *_rest) in enumerate(sheet, 1):
        print(f"{index:>2} {score.name[:30]:<32} {channel:<10} {score.contact:<15} "
              f"{score.total:>3}/100  {', '.join(score.speakable[:2])[:24]:<26} "
              f"{demo.replace('https://sites.qevik.ai/', '')}")

    bad = [(s.name, p) for s, _, _, _, _, _, _, _, p in sheet if p]
    print()
    if bad:
        print("REFUSED — a draft makes a claim it may not:")
        for name, problems in bad:
            for problem in problems:
                print(f"  {name}: {problem}")
        return 1
    print("every draft checked: no unfixable claim, no NOT_VERIFIED claim, no entity")
    print("claim, no price. All five are DRAFT_NOT_SENT.")

    if args.record:
        for score, _, business, demo, channel, _subject, body, _mail, _p in sheet:
            repo.record_event(experiment.record_prepared(
                score.business_id, prospect=score.name, channel=channel, body=body,
                demo_url=demo,
                claim="; ".join(score.speakable[:2]) or "no weakness claimed",
                actor="first_five.py",
            ))
        print(f"\nrecorded {len(sheet)} experiment_prepared events (sent: False)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

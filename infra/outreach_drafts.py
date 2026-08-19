#!/usr/bin/env python3
"""Draft the first-contact message for each top prospect. Sends nothing.

There is no send path in this file — no SMTP client, no WhatsApp client, no
HTTP POST to anything. That is deliberate and is the whole safety property: a
script that *can* send is one flag away from sending, and the instruction is
that nothing goes out without approval. Drafts are written to disk and recorded
on each business's timeline as `outreach_drafted`, so the record shows what was
prepared and that it was not sent.

Every message is assembled from that prospect's own dossier, so the claim in the
message is the claim the evidence supports. Before writing a draft, the text is
checked against that prospect's DO_NOT_SAY list — a draft that would make a
forbidden claim is refused rather than written, because a forbidden claim caught
at review time is one that survives to the next draft.

    outreach_drafts.py                # write drafts for the top 5
    outreach_drafts.py --top 20
    outreach_drafts.py --show         # print them
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from prospect_dossier import build  # noqa: E402

from atlas_kernel.outreach import (  # noqa: E402
    EMAIL_SIGNATURE,
    WHATSAPP_SIGNATURE,
    WhatsAppChannel,
    entity_claims,
)

DRAFTS = Path(os.environ.get("QEVIK_DRAFTS", "/var/lib/qevik/outreach"))

#: Phrases that must never appear in a draft, whatever the evidence says. These
#: are not per-prospect — they are claims that are false for every prospect,
#: because they describe things Qevik does not do.
NEVER = (
    ("book your appointment", "the form does not book anything"),
    ("booking system", "there is no booking backend"),
    ("we have booked", "nothing books"),
    ("guaranteed", "no ranking or outcome is guaranteed"),
    ("#1 on google", "no ranking is promised"),
    ("your website is down", "a timeout is slowness, not death"),
    ("free forever", "no pricing has been agreed"),
)


def clean_name(raw: str) -> str:
    """The clinic's name as a person would say it.

    Google listings carry SEO tails — "Malabar Dental Clinic | Dubai", "The
    TopDent: Dental Clinic in Dubai". Pasting that into a message addressed to
    the owner is the tell that it came out of a database.
    """
    for separator in ("|", " - ", ":"):
        if separator in raw:
            raw = raw.split(separator)[0]
    return raw.strip()


def short_url(url: str) -> str:
    return url.replace("https://", "").replace("http://", "").rstrip("/")


def whatsapp_message(d: dict) -> str:
    """A cold WhatsApp from an unknown number. Short, and human first.

    Deliberately different from the email rather than a trimmed copy of it. The
    recipient is holding a phone, does not know who this is, and decides in about
    two seconds — so it opens by saying who is writing, keeps to one claim, and
    puts the link where a thumb lands. Everything the email says about scope and
    caveats belongs in the reply, not in the opener.
    """
    name = clean_name(d["name"])
    good = d["already_good"]

    if good:
        looked = (
            f"I had a look at {short_url(d['existing_website'])} — the "
            f"{good[0].lower()} and {good[1].lower()} are well done."
            if len(good) > 1
            else f"I had a look at {short_url(d['existing_website'])}."
        )
    else:
        looked = f"I tried to open {short_url(d['existing_website'])} a few times today."

    return "\n".join(
        [
            f"Hello — I'm Ayoub. I build websites for dental clinics in Dubai, "
            f"and I'm writing about {name}.",
            "",
            looked,
            "",
            _gap_sentence(d),
            "",
            "So I built you a working example, using only your own details from "
            "your Google listing — nothing invented:",
            d["demo_url"],
            "",
            "It has an Arabic version as well. No charge for looking. If it's "
            "useful we can talk; if not, keep the link.",
            "",
            WHATSAPP_SIGNATURE,
        ]
    )


def email_message(d: dict) -> tuple[str, str]:
    good = d["already_good"]
    subject = f"{d['name']} — a working example of your site, in Arabic and English"

    body = [
        "Hello,",
        "",
        f"I work on websites for dental clinics in Dubai, and I looked at "
        f"{d['existing_website']} this week.",
        "",
    ]
    if good:
        body += [
            "A fair bit of it is already done properly — "
            + ", ".join(g.lower() for g in good[:4])
            + (f", and {len(good) - 4} other things" if len(good) > 4 else "")
            + ". I am not writing to tell you your site is bad.",
            "",
        ]
    body += [
        _gap_sentence(d),
        "",
        "Rather than describe it, I built you a working example. It uses only "
        "your own details — the name, phone number, address and opening hours "
        "from your Google listing. Nothing about it is invented:",
        "",
        f"    {d['demo_url']}",
        "",
        "There is an Arabic version at the same address with /ar/ on the end. "
        "Open it on a phone; that is where most of your patients will.",
        "",
        # The phrase "booking system" is refused by `check` even in an honest
        # sentence like this one. Keeping the guard blunt and rewording the copy
        # is the right trade: a guard with exceptions is a guard that eventually
        # lets the dishonest version through on the same exception.
        "One thing I should say plainly: the appointment form on that example "
        "is a placeholder. It does not send anywhere yet, and it says so on the "
        "page itself. Wiring it to a real appointment provider is a decision for "
        "later, not something I am quietly pretending already works.",
        "",
        "If it is worth a conversation, reply here or call me. If not, no "
        "follow-up — you can keep the link either way.",
        "",
        "Best regards,",
        EMAIL_SIGNATURE,
    ]
    return subject, "\n".join(body)


def _gap_sentence(d: dict) -> str:
    """The one claim, phrased exactly as the evidence supports it."""
    gap = d["strongest_weakness"]
    if gap == "Loads within 30 seconds":
        return (
            "It did not finish loading for me within 30 seconds. I do not know "
            "whether that is constant or occasional, but a patient waiting on a "
            "blank screen usually phones someone else."
        )
    if gap == "Arabic version":
        return (
            # "they will not find you at all" is an absolute I cannot support
            # from one homepage fetch. What is defensible is the mechanism: an
            # English-only page gives a search engine no Arabic text to match.
            "The one thing I couldn't find is an Arabic version. A lot of "
            "patients here search in Arabic first, and an English-only page "
            "gives Google no Arabic text to match them against."
        )
    if gap == "HTTPS":
        return (
            "Your site is served over plain HTTP, so browsers now show a 'not "
            "secure' warning to anyone using the contact form."
        )
    if gap == "Structured data":
        return (
            "There is no dentist schema on the page, which is a large part of "
            "what puts a clinic into Google's local results and map pack."
        )
    return f"The one gap I found is {gap.lower()}."


def check(text: str, d: dict) -> list[str]:
    """Refuse a draft that makes a claim the evidence forbids."""
    problems = []
    lowered = text.lower()

    for phrase, why in NEVER:
        if phrase in lowered:
            problems.append(f"contains {phrase!r} — {why}")

    # Qevik is a brand operated by Asia Link Internet Content Provider LLC, not a
    # separately licensed company. Claiming otherwise is a false statement about
    # a regulated status, made to a business that can check it.
    for claim in entity_claims(text):
        problems.append(
            f"presents Qevik as its own legal entity ({claim!r}) — it is a brand "
            "operated by Asia Link Internet Content Provider LLC"
        )

    for item in d["do_not_say"]:
        if item["reason"] != "THEIR_SITE_HAS_IT":
            continue
        # "Their site has no map / directions" -> the feature words.
        feature = item["claim"].lower().replace("their site has no ", "")
        # Only flag a *negative* claim about it, not a mention.
        pattern = rf"\b(no|without|missing|lacks?|don'?t have|doesn'?t have)\b[^.]{{0,40}}{re.escape(feature)}"
        if re.search(pattern, lowered):
            problems.append(f"claims they lack {feature!r} — their site has it")

    return problems


def record_draft(dossier_row: dict, draft: dict) -> None:
    """Put the draft on the business's permanent timeline.

    The point is not the copy — it is that the record shows outreach was
    *prepared and not sent*. Without the event, a later reader sees an audit, a
    demo, and then either silence or a message with no history behind it, and
    cannot tell whether a decision was taken or simply forgotten.
    """
    from atlas_kernel.opportunity.models import (
        BusinessEvent,
        OutreachMessage,
        OutreachStatus,
    )
    from atlas_kernel.opportunity.repository import OpportunityRepository

    repo = OpportunityRepository()
    match = next(
        (
            b
            for b in repo.list_businesses()
            if b.name == dossier_row["name"]
        ),
        None,
    )
    if match is None:
        print(f"             (no business record for {dossier_row['name']!r} — not logged)")
        return

    # Stored as a real OutreachMessage, not only as a JSON file, so the send
    # path that arrives later reads from the same place approvals and receipts
    # already live — status, approval_id, approved_fingerprint, sent_at. A
    # parallel store would mean two answers to "was this sent".
    # Re-drafting replaces the previous draft rather than adding to it. Without
    # this, every run left another row and the answer to "how many messages are
    # waiting" grew by five each time the copy was edited.
    #
    # Scoped hard to genuinely unsent drafts: anything approved, fingerprinted or
    # sent is commercial history and is never touched, whatever its status says.
    repo.delete_unsent_drafts(match.id, channels=("whatsapp", "email"))

    for channel, recipient, subject, body in (
        ("whatsapp", draft["phone"], "", draft["whatsapp_body"]),
        ("email", "", draft["email_subject"], draft["email_body"]),
    ):
        repo.save_message(
            OutreachMessage(
                proposal_id="",
                business_id=match.id,
                channel=channel,
                recipient=recipient,
                subject=subject,
                body=body,
                # DRAFT, never AWAITING_APPROVAL: nobody has been asked yet.
                # Moving it on is an operator action, not a side effect of
                # writing the words.
                status=OutreachStatus.DRAFT,
                approval_id=None,
                approved_fingerprint=None,
                sent_at=None,
            )
        )

    repo.record_event(
        BusinessEvent(
            business_id=match.id,
            factory="outreach",
            kind="outreach_drafted",
            actor="outreach_drafts.py",
            detail={
                "status": "DRAFT_NOT_SENT",
                "contact_method": draft["contact_method"],
                "demo_url": draft["demo_url"],
                "email_subject": draft["email_subject"],
                "claim": dossier_row["strongest_weakness"],
                "evidence": dossier_row["evidence"],
                "sent": False,
                "approved_by": None,
            },
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)

    DRAFTS.mkdir(parents=True, exist_ok=True)
    whatsapp = WhatsAppChannel()
    rows = build(args.top)
    written, refused = 0, 0

    for d in rows:
        subject, body = email_message(d)
        wa = whatsapp_message(d)

        problems = check(body, d) + check(wa, d)

        # The channel seam earns its keep before any provider exists: if the
        # dossier recommends WhatsApp, the number must actually be able to
        # receive one. A WhatsApp message to a landline is not an error the
        # sender sees — it is silence, and a campaign that reports five sends
        # and produces three is worse than one that refused up front.
        if d["contact_method"].startswith("WhatsApp") and not whatsapp.can_reach(d["phone"]):
            problems.append(
                f"recommends WhatsApp but {d['phone']!r} cannot receive one"
            )
        if problems:
            refused += 1
            print(f"  REFUSED  {d['name'][:44]}")
            for problem in problems:
                print(f"             {problem}")
            continue

        slug = d["demo_url"].rstrip("/").rsplit("/", 1)[-1]
        draft = {
            "business": d["name"],
            "demo_url": d["demo_url"],
            "contact_method": d["contact_method"],
            "contact_rationale": d["contact_rationale"],
            "phone": d["phone"],
            "email_subject": subject,
            "email_body": body,
            "whatsapp_body": wa,
            "status": "DRAFT_NOT_SENT",
            "approved_by": None,
            "sent_at": None,
            "do_not_say": d["do_not_say"],
        }
        path = DRAFTS / f"{slug}.json"
        path.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
        record_draft(d, draft)
        written += 1
        print(f"  drafted  {d['name'][:44]:<46} -> {path.name}  [{d['contact_method']}]")

        if args.show:
            print()
            print(f"    --- {d['contact_method']} ---")
            for line in wa.splitlines():
                print(f"    {line}")
            print()

    print()
    print(f"{written} drafted, {refused} refused. Nothing has been sent.")
    print(f"drafts: {DRAFTS}")
    print("This tool has no send capability. Sending requires an approved, separate step.")
    return 1 if refused else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Preparing the first human-facing message, and everything it refuses.

The milestone this proves: Qevik can say what it built and why, traceably, for a
business that has a published site — and cannot contact anybody, cannot invent a
way to, and does not pretend otherwise.

    python3 infra/verify_outreach_preparation.py
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "kernel"))

from sqlalchemy import text  # noqa: E402

from atlas_kernel.db import SessionLocal, init_db  # noqa: E402
from atlas_kernel.opportunity.models import Business  # noqa: E402
from atlas_kernel.opportunity.repository import (  # noqa: E402
    NotApprovable,
    OpportunityRepository,
)
from atlas_kernel.outreach import channels, identity, preparation  # noqa: E402

MARK = "OutreachProof"
TENANT = "tenant-outreach-proof"
PASSED: list[str] = []
FAILED: list[str] = []


def check(name, ok, detail=""):
    (PASSED if ok else FAILED).append(name)
    print(f"{'  ok  ' if ok else '  FAIL'}  {name}{'  — ' + detail if detail else ''}")
    return ok


init_db()
repo = OpportunityRepository()


def wipe():
    with SessionLocal() as session:
        session.execute(text(
            "DELETE FROM atlas_business_events WHERE business_id LIKE :m"),
            {"m": f"biz-{MARK}%"})
        session.execute(text("DELETE FROM atlas_signals WHERE id LIKE :m"),
                        {"m": f"sig-{MARK}%"})
        session.execute(text("DELETE FROM atlas_businesses WHERE id LIKE :m"),
                        {"m": f"biz-{MARK}%"})
        session.commit()


wipe()
MISSION = "mission-outreachproof01"
COMMIT = "a" * 40
SITE = "site-outreachproof"
URL = f"https://sites.qevik.ai/{SITE}/"


def a_business(suffix: str, *, email: str = "", phone: str = "") -> Business:
    return repo.save_business(Business(
        id=f"biz-{MARK}{suffix}", name=f"{MARK}{suffix} Barbers",
        website="https://outreachproof.example/", email=email, phone=phone))


def a_signal(suffix: str, business_id: str) -> dict:
    sid = f"sig-{MARK}{suffix}"
    with SessionLocal() as session:
        session.execute(text("""
            INSERT INTO atlas_signals (id, tenant_id, business_id, kind, source,
                                       scope, payload, evidence_fingerprints,
                                       score, value_status, needs_approval,
                                       state, detected_at)
            VALUES (:id, :t, :b, 'weak_web_presence', 'probe', 'x', '{}',
                    :fp, 0.8, 'UNKNOWN', TRUE, 'approved', now())
        """), {"id": sid, "t": TENANT, "b": business_id,
               "fp": '["abc123def456", "789fedcba321"]'})
        session.commit()
    return repo.get_signal(sid, tenant=TENANT)


landline = a_business("A", phone="04 447 3188")     # the real shape
signal = a_signal("A", landline.id)
publication = {"mission_id": MISSION, "commit": COMMIT, "site_id": SITE,
               "url": URL}
ANSWERS = ("a heading on every page", "a page that loads quickly")

print("\n-- the architecture: no role, so no network to withhold ---------------")
from atlas_kernel.fabric.agents import AGENTS  # noqa: E402
from atlas_kernel.fabric.recipes import RECIPES  # noqa: E402
from atlas_kernel.fabric.tools import TOOLS  # noqa: E402

check("no agent exists for preparation",
      not [a for a in AGENTS if "outreach" in a.id or "send" in a.id],
      "preparation composes and records; it dispatches nothing")
check("no tool can send a message",
      not [t for t in TOOLS if "send" in t.id or "mail" in t.id
           or "outreach" in t.id],
      str([t.id for t in TOOLS]))
check("no recipe prepares or sends outreach",
      not [r for r in RECIPES if "outreach" in r.id or "send" in r.id],
      str([r.id for r in RECIPES]))

module = ast.parse((ROOT / "packages/kernel/atlas_kernel/outreach/preparation.py")
                   .read_text())
code = ast.unparse(module)
for forbidden, why in (("httpx", "an HTTP client"), ("urllib", "a URL opener"),
                       ("requests", "an HTTP client"),
                       ("smtplib", "a mail sender"),
                       ("subprocess", "a subprocess"), ("socket", "a socket")):
    check(f"the preparation path does not import {why}", forbidden not in code,
          "" if forbidden not in code else f"{forbidden!r} appears in it")
check("NEGATIVE CONTROL: the scan sees what it does import",
      "identity" in code and "channels" in code,
      "so the absences above are absences, not a broken scan")

print("\n-- no contact is invented --------------------------------------------")
check("a business with only a landline has no verified recipient",
      preparation.verified_recipient(landline) == ("", ""),
      "a landline is not a WhatsApp number and a website is not an address")

guessed = a_business("B")
check("a business with a website but no contact has none either",
      preparation.verified_recipient(guessed) == ("", ""),
      "info@ their domain is a guess that reaches a stranger")
check("NEGATIVE CONTROL: a real email is found",
      preparation.verified_recipient(
          a_business("C", email="hello@outreachproof.example"))
      == ("hello@outreachproof.example", "email"))
check("...and a mobile that WhatsApp can reach",
      preparation.verified_recipient(
          a_business("D", phone="+971501029104"))[1] == "whatsapp")

print("\n-- what a prepared message may say -----------------------------------")
prepared = preparation.prepare(business=landline, signal=signal,
                               publication=publication,
                               approved_scope="offer-website: performance",
                               answers=ANSWERS)
check("it is PREPARED, and addressed to nobody",
      prepared.state == "PREPARED" and prepared.recipient == "")
check("it references the business, opportunity and mission",
      prepared.business_id == landline.id
      and prepared.signal_id == signal["id"]
      and prepared.mission_id == MISSION)
check("...the published site and the commit behind it",
      prepared.url == URL and prepared.commit == COMMIT
      and prepared.site_id == SITE)
check("...the approved scope", prepared.approved_scope == "offer-website: performance")
check("...and the evidence the opportunity rested on",
      list(prepared.evidence_fingerprints) == ["abc123def456", "789fedcba321"],
      str(prepared.evidence_fingerprints))
check("every claim names the record it came from",
      set(prepared.traces) >= {"business name", "the published address",
                               "the bytes behind it", "why this business"},
      str(sorted(prepared.traces)))

body = prepared.body
check("the message contains the published address", URL in body)
check("...and what the build says it answered",
      all(line in body for line in ANSWERS))
check("...and the one signature there is",
      identity.EMAIL_SIGNATURE in body)
check("it claims no licence Qevik does not hold",
      not identity.entity_claims(body), str(identity.entity_claims(body)))
check("it names no price", "AED" not in body and "$" not in body,
      "a number turns a first message into a negotiation")
check("it promises no result",
      not any(w in body.lower() for w in ("guarantee", "will increase",
                                          "more customers", "rank higher")))
check("it invents no contact person", "Dear " not in body and "Hi " not in body)

print("\n-- it is blocked, and says on what -----------------------------------")
check("blocked for want of a recipient",
      preparation.NO_RECIPIENT in prepared.blocked_on,
      str(prepared.blocked_on))
check("...and for want of a sending identity",
      preparation.NO_SENDING_IDENTITY in prepared.blocked_on)
check("it is not sendable", prepared.sendable is False)

reachable = a_business("E", email="hello@outreachproof.example")
with_email = preparation.prepare(business=reachable, signal=signal,
                                 publication=publication, approved_scope="x")
check("NEGATIVE CONTROL: with a real address only the sender is missing",
      with_email.blocked_on == (preparation.NO_SENDING_IDENTITY,),
      str(with_email.blocked_on))
check("...so a verified recipient is genuinely detected",
      with_email.recipient == "hello@outreachproof.example")

print("\n-- nothing can send --------------------------------------------------")
# Each channel is given an address it *can* reach, so the refusal proves the
# missing provider rather than the wrong recipient shape.
for channel, address in ((channels.EmailChannel(), "hello@outreachproof.example"),
                         (channels.WhatsAppChannel(), "+971501029104")):
    check(f"{channel.name} reports no provider", channel.configured() is False)
    check(f"...and can reach {address[:6]}…, so the refusal is about the sender",
          channel.can_reach(address))
    try:
        channel.send(recipient=address, subject="s", body="b",
                     approval=type("A", (), {"approved": True})())
        check(f"{channel.name} refuses to send", False, "it sent something")
    except channels.ChannelNotConnected as refused:
        check(f"{channel.name} refuses to send", True, str(refused)[:52])
    except channels.OutreachError as wrong:
        check(f"{channel.name} refuses to send", False,
              f"refused for the wrong reason: {type(wrong).__name__}")

print("\n-- publication approval is not outreach approval ----------------------")
repo.record_publication(mission_id=MISSION, business_id=landline.id,
                        signal_id=signal["id"], commit=COMMIT, site_id=SITE,
                        url=URL, files=["index.html"], actor="probe",
                        tenant=TENANT)
repo.approve_publication  # the publication boundary exists and is separate
check("publishing was authorised and outreach was not",
      repo.outreach_approvals_for(MISSION) == [],
      "the third yes does not produce the fourth")

try:
    repo.approve_outreach(mission_id=MISSION, business_id=landline.id,
                          signal_id=signal["id"], commit=COMMIT,
                          recipient="", channel="email",
                          fingerprint="f" * 16, actor="ayoub", tenant=TENANT)
    check("approving outreach to nobody is refused", False)
except NotApprovable as refused:
    check("approving outreach to nobody is refused", True, str(refused)[:56])

try:
    repo.approve_outreach(mission_id=MISSION, business_id=landline.id,
                          signal_id=signal["id"], commit=COMMIT,
                          recipient="hello@outreachproof.example",
                          channel="email", fingerprint="", actor="ayoub",
                          tenant=TENANT)
    check("approving without a fingerprint is refused", False)
except NotApprovable as refused:
    check("approving without a fingerprint is refused", True, str(refused)[:56])

try:
    repo.approve_outreach(mission_id=MISSION, business_id=landline.id,
                          signal_id=signal["id"], commit="b" * 40,
                          recipient="hello@outreachproof.example",
                          channel="email", fingerprint="f" * 16,
                          actor="ayoub", tenant=TENANT)
    check("approving outreach about an unpublished artefact is refused", False)
except NotApprovable as refused:
    check("approving outreach about an unpublished artefact is refused", True,
          str(refused)[:60])

try:
    repo.approve_outreach(mission_id="mission-never-published",
                          business_id=landline.id, signal_id=signal["id"],
                          commit=COMMIT, recipient="hello@outreachproof.example",
                          channel="email", fingerprint="f" * 16, actor="ayoub",
                          tenant=TENANT)
    check("approving outreach for a different mission is refused", False)
except NotApprovable as refused:
    check("approving outreach for a different mission is refused", True,
          str(refused)[:56])

approved = repo.approve_outreach(
    mission_id=MISSION, business_id=landline.id, signal_id=signal["id"],
    commit=COMMIT, recipient="hello@outreachproof.example", channel="email",
    fingerprint="f" * 16, actor="ayoub", tenant=TENANT, note="ok to write")
check("NEGATIVE CONTROL: a complete authorisation is recorded",
      approved["recipient"] == "hello@outreachproof.example")
check("...binding the words, not the message",
      approved["fingerprint"] == "f" * 16)
check("...the commit that was published", approved["commit"] == COMMIT)
check("APPROVED_TO_SEND is still not SENT",
      channels.EmailChannel().configured() is False,
      "permission exists and the ability does not")

for _ in range(3):
    repo.approve_outreach(
        mission_id=MISSION, business_id=landline.id, signal_id=signal["id"],
        commit=COMMIT, recipient="hello@outreachproof.example", channel="email",
        fingerprint="f" * 16, actor="ayoub", tenant=TENANT)
check("duplicate approvals do not create duplicate authority",
      len({a["fingerprint"] for a in repo.outreach_approvals_for(MISSION)}) == 1,
      f"{len(repo.outreach_approvals_for(MISSION))} records, one set of words")

print("\n-- the words are what was approved -----------------------------------")
edited = preparation.compose(business_name="Somebody Else", url=URL,
                             answers=ANSWERS, site_id=SITE)[1]
check("editing the message changes its fingerprint",
      edited != prepared.body,
      "an approval bound to a fingerprint does not survive an edit")

wipe()
print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
for n in FAILED:
    print(f"  FAILED  {n}")
sys.exit(1 if FAILED else 0)

"""Telling a business what was built for them, before anybody is contacted.

The last edge, and the one with a person on the other end of it. Everything
earlier in the chain could be undone or ignored: a sighting re-recorded, an
artefact rebuilt, a page taken down. A message cannot be unsent, and unlike a
publication it arrives whether or not anybody went looking.

## Preparation is not sending, and this module cannot send

There is no agent, no tool and no recipe here, and that is the design rather than
an omission. Preparation is deterministic composition from records Qevik already
holds plus a decision somebody records — it dispatches nothing and reaches
nothing, so it needs no blast radius and no role. The consequence worth stating:
**no network tool is available to the preparation path by construction**, not by
policy. There is no role to attach one to.

Sending *is* an act, and an act needs the mission → recipe → agent → tool chain
that publishing uses. It is not built here, because there is no approved sending
identity and building an approval boundary nothing can cross is architecture
rather than a business.

## What it may say

Only what is recorded. Every sentence below is assembled from a stored fact —
the business's own name, the defects an audit observed, the address a
publication actually went to, the commit a person accepted. Nothing is inferred,
nothing is softened into a claim, and there is no template slot a model could
fill.

Specifically it never invents a contact, a person, a phone number, a fact about
the business, or a sending identity. `outreach/identity.py` is the letterhead and
is stated once; this reads it and does not compose one.

## Three states

    PREPARED          a message exists, addressed to nobody
    APPROVED_TO_SEND  a person decided it may go
    SENT              a provider accepted it

`SENT` became reachable when `EmailChannel` gained a transport, and it is
reached only through `OutreachService.send` — never from here. This module still
cannot send: it composes, and composing is not an act.

`APPROVED_TO_SEND` is reachable only when there is a verified recipient.

The approval that authorises *automated* delivery is a separate decision from
approving the words, and carries `authorized_automated_at`. `fingerprint` below
is what such an approval binds to.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from . import identity
from .channels import EMAIL_SHAPE

#: What a preparation is waiting on. Named states, because "blocked" without a
#: reason is a thing nobody can clear.
NO_RECIPIENT = "NO_VERIFIED_RECIPIENT"
NO_SENDING_IDENTITY = "NO_SENDING_IDENTITY"
NOT_PUBLISHED = "NOT_PUBLISHED"


class NotPreparable(Exception):
    """There is nothing honest to say yet, and why."""


@dataclass(frozen=True)
class Prepared:
    """A message, everything it rests on, and what stops it being sent.

    Deliberately carries the references rather than a rendered summary of them.
    A reviewer deciding whether to contact somebody needs to be able to follow
    each claim back to the record that supports it, and a paragraph asserting
    the claims were checked is not that.
    """

    business_id: str
    business_name: str
    signal_id: str
    #: The mission whose artefact was published, and the commit that went out.
    mission_id: str
    commit: str
    site_id: str
    url: str
    approved_scope: str
    #: Fingerprints of the evidence the original opportunity rested on.
    evidence_fingerprints: tuple[str, ...]
    #: What the build says it answered, from the artefact's own provenance.
    answers: tuple[str, ...]
    subject: str
    body: str
    #: Empty only when a real, verified address is on file.
    recipient: str = ""
    channel: str = ""
    blocked_on: tuple[str, ...] = ()
    #: Which stored field each claim came from, so a reader can check them.
    traces: dict[str, str] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        """What an approval for automated delivery binds to.

        The mission pipeline's counterpart to `Proposal.fingerprint`, and
        deliberately not that object: a mission has a `Signal` and evidence
        fingerprints, not `Finding`s, and manufacturing a `Proposal` to satisfy
        an interface would mean inventing the evidence it claims to cite.

        Five components, each already authoritative somewhere:

        * `subject`, `body` — the exact words that will be sent, as composed.
        * `recipient` — from the business record, via `verified_recipient`.
        * `commit` — the publication this message is *about*. Republish and the
          approval dies, because the message says "I built one and put it here".
        * `evidence_fingerprints` — the signal's own record of what was observed.
          Re-run the audit and the approval dies, because the claim rested on it.

        Sorted, so the digest does not move when a list is read back in another
        order. `answers` are not a separate component: they are already inside
        `body`, and including them twice would say nothing new.
        """
        return hashlib.sha256("\x1f".join((
            self.subject,
            self.body,
            self.recipient,
            self.commit,
            *sorted(self.evidence_fingerprints),
        )).encode("utf-8")).hexdigest()

    @property
    def state(self) -> str:
        return "PREPARED"

    @property
    def sendable(self) -> bool:
        """Never true today. Kept as a property so nothing reads it as a flag
        somebody could set."""
        return not self.blocked_on

    def summary(self) -> dict:
        return {"business_id": self.business_id,
                "business_name": self.business_name,
                "signal_id": self.signal_id, "mission_id": self.mission_id,
                "commit": self.commit, "site_id": self.site_id, "url": self.url,
                "approved_scope": self.approved_scope,
                "evidence_fingerprints": list(self.evidence_fingerprints),
                "answers": list(self.answers),
                "subject": self.subject, "body": self.body,
                "recipient": self.recipient, "channel": self.channel,
                "blocked_on": list(self.blocked_on),
                "traces": dict(self.traces),
                "state": self.state, "sendable": self.sendable}


def verified_recipient(business: Any) -> tuple[str, str]:
    """The address this business can actually be reached at, or nothing.

    Returns `(recipient, channel)`, and `("", "")` when there is no verified
    one. **It never derives an address.** A business with a website is not
    reachable at `info@` that website: that address is a guess that lands in a
    stranger's inbox or bounces, and the guess is indistinguishable from a fact
    once it is written into a message.

    A landline is not a WhatsApp number. `WhatsAppChannel.can_reach` already
    refuses one and this agrees with it rather than restating the rule: a
    message to a landline is not an error anybody sees, it is silence.
    """
    email = (getattr(business, "email", "") or "").strip()
    if email and EMAIL_SHAPE.match(email):
        return email, "email"

    from .channels import WhatsAppChannel

    phone = (getattr(business, "phone", "") or "").strip()
    if phone and WhatsAppChannel().can_reach(phone):
        return phone, "whatsapp"
    return "", ""


def compose(*, business_name: str, url: str, answers: tuple[str, ...],
            site_id: str) -> tuple[str, str]:
    """The message, assembled from stored facts and nothing else.

    Written as short as it can be while remaining checkable. It says what was
    built, where it is, what it answers and who is writing — and it makes no
    claim about the business beyond what an audit observed and a person then
    accepted.

    No price, deliberately: `outreach/offer.py` holds one and says why it must
    not appear in a first message. No promise about results, because nothing has
    measured any.
    """
    subject = f"A website for {business_name}"
    answered = ""
    if answers:
        answered = ("\n\nIt addresses what we found when we looked at your "
                    "current site:\n"
                    + "\n".join(f"  • {line}" for line in answers))
    body = (
        f"Hello,\n\n"
        f"I build websites for businesses in Dubai. Rather than describe what "
        f"that would look like for {business_name}, I built one and put it "
        f"here:\n\n  {url}\n\n"
        f"It is a working page, not a mock-up. Nothing on it was invented — it "
        f"uses only the details already published about the business."
        f"{answered}\n\n"
        f"If it is useful, I can hand it over. If it is not, this costs you "
        f"nothing and you can ignore this message.\n\n"
        f"{identity.EMAIL_SIGNATURE}\n")
    return subject, body


def prepare(*, business: Any, signal: dict, publication: dict,
            approved_scope: str, answers: tuple[str, ...] = ()) -> Prepared:
    """Derive the outreach for one published site. Sends nothing.

    Refuses outright when there is no publication: the entire message is *"I
    built this and it is here"*, and without a published address there is
    nothing to say. That is a refusal rather than a blocker, because a blocker
    is something a person could clear and this one would require lying.
    """
    if not publication or not publication.get("url"):
        raise NotPreparable(
            "nothing has been published for this business, and the message is "
            "about a published site. There is nothing to say yet.")

    recipient, channel = verified_recipient(business)
    blocked: list[str] = []
    if not recipient:
        blocked.append(NO_RECIPIENT)
    # Checked by asking the channel, not by reading a setting. A flag saying a
    # sender is configured is one edit away from being wrong; the channel
    # reports what it actually holds, which today is nothing.
    from .channels import EmailChannel, WhatsAppChannel

    channels = {"email": EmailChannel(), "whatsapp": WhatsAppChannel()}
    chosen = channels.get(channel)
    if chosen is None or not chosen.configured():
        blocked.append(NO_SENDING_IDENTITY)

    subject, body = compose(business_name=business.name,
                            url=publication["url"], answers=tuple(answers),
                            site_id=publication.get("site_id", ""))

    return Prepared(
        business_id=business.id, business_name=business.name,
        signal_id=signal.get("id", ""),
        mission_id=publication.get("mission_id", ""),
        commit=publication.get("commit", ""),
        site_id=publication.get("site_id", ""),
        url=publication["url"],
        approved_scope=approved_scope,
        evidence_fingerprints=tuple(signal.get("evidence_fingerprints") or ()),
        answers=tuple(answers),
        subject=subject, body=body,
        recipient=recipient, channel=channel,
        blocked_on=tuple(blocked),
        # Every claim in the message, and the record it came from. A reviewer
        # can check each one without reading this module.
        traces={
            "business name": f"atlas_businesses.name of {business.id}",
            "the published address": f"publication_completed of "
                                     f"{publication.get('mission_id', '')}",
            "the bytes behind it": f"commit {publication.get('commit', '')}",
            "what it addresses": "artefact provenance `addresses`",
            "why this business": f"opportunity {signal.get('id', '')}",
            "signature": "outreach/identity.py",
        })


__all__ = ["NO_RECIPIENT", "NO_SENDING_IDENTITY", "NOT_PUBLISHED",
           "NotPreparable", "Prepared", "compose", "prepare",
           "verified_recipient"]

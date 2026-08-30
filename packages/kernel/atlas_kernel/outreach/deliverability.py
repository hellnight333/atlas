"""Whether qevik.ai can send mail anybody accepts, and receive the reply.

Five settings in the environment make `EmailChannel.configured()` true. They do
not make mail deliverable: a brand-new domain with no SPF and no DMARC sending
cold mail to UAE businesses lands in spam, and with no MX the reply to it
bounces. **Configured and deliverable are different facts** and the operator
needs both — `70_EMAIL_INFRASTRUCTURE.md` measured all four records absent on
2026-08-21, which is why the first commercial test was WhatsApp.

Distinct from `identity.py`, which is *who signs the message*. This is whether
the domain it is sent from proves anything.

**Reads public DNS and nothing else.** It cannot contact a business, takes no
recipient, and asks four questions about our own domain.

The three states are kept apart with more care than usual, because the failure
mode is specific: a resolver that times out looks exactly like a record that is
absent, and reporting the second would send somebody to Cloudflare to create a
record that already exists — or report the domain as unprotected when it is fine.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum

#: The domain Qevik sends as. One place, so this and the Message-ID cannot
#: disagree about who we are.
SENDING_DOMAIN = "qevik.ai"

#: Selectors worth asking about. Google Workspace publishes under `google`; the
#: rest are common defaults. Absent from all of them is evidence of no DKIM, not
#: proof — a selector nobody named cannot be found by guessing.
DKIM_SELECTORS: tuple[str, ...] = ("google", "default", "selector1", "selector2",
                                   "s1", "k1", "mail")


class State(StrEnum):
    """Three states, never two.

    `NOT_VERIFIED` is not a soft `ABSENT`. It means the question was asked and
    no answer came back, and every surface must draw it differently from a
    record that is genuinely missing.
    """

    PRESENT = "CONFIRMED_PRESENT"
    ABSENT = "CONFIRMED_ABSENT"
    UNKNOWN = "NOT_VERIFIED"


@dataclass(frozen=True)
class Record:
    """One DNS question and what came back."""

    name: str
    #: Why it matters, in the terms of the consequence rather than the protocol.
    matters_because: str
    state: State
    values: tuple[str, ...] = ()
    detail: str = ""

    def summary(self) -> dict:
        return {"name": self.name, "matters_because": self.matters_because,
                "state": self.state.value, "values": list(self.values),
                "detail": self.detail}


@dataclass(frozen=True)
class Deliverability:
    """What the domain currently proves about itself."""

    domain: str
    records: tuple[Record, ...]

    @property
    def unreadable(self) -> bool:
        """Nothing could be measured.

        Distinguished from "everything is absent" because the instruction that
        follows is the opposite one: check the resolver, not the DNS zone.
        """
        return all(r.state is State.UNKNOWN for r in self.records)

    @property
    def can_receive_a_reply(self) -> bool:
        """An MX exists. Sending from an address whose replies bounce is worse
        than not sending."""
        return self.state_of("MX") is State.PRESENT

    @property
    def ready_to_send(self) -> bool:
        """Deliberately strict, and deliberately not a synonym for `configured`.

        SPF and DMARC give a receiving server something to authenticate against;
        MX means the conversation can continue. DKIM is reported but not
        required: a provider may sign under a selector this cannot guess, and
        demanding proof the method cannot obtain would hold everything shut for
        a record that is probably fine.
        """
        return all(self.state_of(name) is State.PRESENT
                   for name in ("MX", "SPF", "DMARC"))

    @property
    def missing(self) -> tuple[str, ...]:
        """Records confirmed absent. **Never includes an unmeasured one.**"""
        return tuple(r.name for r in self.records if r.state is State.ABSENT)

    @property
    def unmeasured(self) -> tuple[str, ...]:
        return tuple(r.name for r in self.records if r.state is State.UNKNOWN)

    def state_of(self, name: str) -> State:
        for record in self.records:
            if record.name == name:
                return record.state
        return State.UNKNOWN

    def summary(self) -> dict:
        return {
            "domain": self.domain,
            "records": [r.summary() for r in self.records],
            "unreadable": self.unreadable,
            "can_receive_a_reply": self.can_receive_a_reply,
            "ready_to_send": self.ready_to_send,
            "missing": list(self.missing),
            "unmeasured": list(self.unmeasured),
            "note": ("Configured and deliverable are different facts. Five "
                     "settings make the channel configured; these records "
                     "decide whether anybody accepts the mail."),
        }


def _dig(name: str, kind: str, *, timeout: float = 6.0) -> tuple[str, ...] | None:
    """Answers for one question, or `None` when the question could not be asked.

    `None` is the point of this function. `dig` exits non-zero when it could not
    ask, and exits *zero with no output* for a name that genuinely has no
    record. Telling them apart by the exit code rather than by the emptiness of
    the output is what stops a broken resolver becoming a confident report of an
    unprotected domain.
    """
    if not shutil.which("dig"):
        return None
    try:
        finished = subprocess.run(
            ["dig", "+short", "+time=3", "+tries=2", name, kind],
            capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if finished.returncode != 0:
        return None
    lines = [line.strip() for line in finished.stdout.splitlines() if line.strip()]
    # dig reports its own trouble on stdout and still exits zero. Read as an
    # answer, ";; connection timed out" becomes an MX record named ";;".
    if any(line.startswith(";") for line in lines):
        return None
    return tuple(lines)


def _record(name: str, matters: str, answers: tuple[str, ...] | None, *,
            wanted: str = "") -> Record:
    if answers is None:
        return Record(name=name, matters_because=matters, state=State.UNKNOWN,
                      detail="the resolver did not answer. This is not the "
                             "same as the record being absent.")
    if wanted:
        answers = tuple(a for a in answers if wanted in a.lower())
    if not answers:
        return Record(name=name, matters_because=matters, state=State.ABSENT)
    return Record(name=name, matters_because=matters, state=State.PRESENT,
                  values=answers)


def measure(domain: str = SENDING_DOMAIN) -> Deliverability:
    """Ask DNS what this domain currently proves. Reads only."""
    mx = _record("MX", "Without it a reply to anything we send bounces, and "
                       "outreach nobody can answer is worse than none.",
                 _dig(domain, "MX"))
    spf = _record("SPF", "Without it a receiving server has nothing to "
                         "authenticate against, and cold mail from a new "
                         "domain is filtered rather than delivered.",
                  _dig(domain, "TXT"), wanted="v=spf1")
    dmarc = _record("DMARC", "Without it anybody can forge mail as this domain "
                             "and we are told nothing about it.",
                    _dig(f"_dmarc.{domain}", "TXT"), wanted="v=dmarc1")

    signs = "Signs each message so a receiver can tell it really came from us."
    signed: list[str] = []
    asked = 0
    for selector in DKIM_SELECTORS:
        answers = _dig(f"{selector}._domainkey.{domain}", "TXT")
        if answers is None:
            continue
        asked += 1
        if any("v=dkim1" in a.lower() or "p=" in a for a in answers):
            signed.append(selector)
    if asked == 0:
        dkim = Record(name="DKIM", matters_because=signs, state=State.UNKNOWN,
                      detail="the resolver did not answer for any selector.")
    elif signed:
        dkim = Record(name="DKIM", matters_because=signs, state=State.PRESENT,
                      values=tuple(signed),
                      detail=f"found under {', '.join(signed)}")
    else:
        dkim = Record(name="DKIM", matters_because=signs, state=State.ABSENT,
                      detail=f"none under the {asked} selector(s) this checks. "
                             "A selector nobody named cannot be found by "
                             "guessing, so this is evidence rather than proof.")

    return Deliverability(domain=domain, records=(mx, spf, dmarc, dkim))


__all__ = ["DKIM_SELECTORS", "SENDING_DOMAIN", "Deliverability", "Record",
           "State", "measure"]

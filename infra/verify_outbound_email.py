#!/usr/bin/env python3
"""Proves the outbound half of M1 without sending a single message.

`smtplib.SMTP` is replaced, so the real path runs -- every gate, the header
construction, the transport call -- and nothing leaves the machine. The one
thing this cannot prove is delivery, and that is stated rather than implied:
**a green run here does not mean email works.** Only a message arriving in a
real inbox, with SPF, DKIM and DMARC passing in its headers, means that.

Run:  python3 infra/verify_outbound_email.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "packages/kernel")

from atlas_kernel.outreach import channels
from atlas_kernel.outreach.channels import (
    AlreadySent,
    ChannelNotConnected,
    EmailChannel,
    NotApproved,
    NotReachable,
    OutreachError,
    Unsendable,
    WhatsAppChannel,
    connected,
)

PASSED: list[str] = []
FAILED: list[str] = []

#: Obviously fake. No value here can reach a real server.
FAKE = {
    "QEVIK_SMTP_HOST": "smtp.invalid",
    "QEVIK_SMTP_PORT": "587",
    "QEVIK_SMTP_USER": "nobody@example.invalid",
    "QEVIK_SMTP_PASSWORD": "not-a-real-password",
    "QEVIK_SMTP_FROM": "nobody@example.invalid",
}


def check(label: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))


def raises(exc, fn) -> bool:
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


class Approved:
    approved = True


class Recorder:
    """Stands in for the transport. Records, never connects."""

    steps: list = []

    def __init__(self, host, port, timeout=None):
        Recorder.steps.append(("connect", host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        Recorder.steps.append(("starttls",))

    def login(self, user, password):
        Recorder.steps.append(("login", user, password))

    def send_message(self, message):
        Recorder.steps.append(("send", message))


class Rejects(Recorder):
    def send_message(self, message):
        import smtplib
        raise smtplib.SMTPRecipientsRefused({})


def configure(**over) -> None:
    for name, value in {**FAKE, **over}.items():
        os.environ[name] = value


def unconfigure() -> None:
    for name in channels.SMTP_SETTINGS:
        os.environ.pop(name, None)
    os.environ.pop("QEVIK_SMTP_REPLY_TO", None)


def reset() -> None:
    Recorder.steps = []
    channels._ALREADY_SENT.clear()


real_smtp = channels.smtplib.SMTP
try:
    # ================================================== unconfigured
    print("\n-- with no credential, nothing changed --------------------------------")
    unconfigure()
    check("the channel reports itself unconfigured", not EmailChannel().configured())
    check("...and connected() lists nothing", connected() == [], str(connected()))
    check("...and an otherwise perfect send is refused",
          raises(ChannelNotConnected, lambda: EmailChannel().send(
              recipient="clinic@example.com", subject="s", body="b",
              approval=Approved())),
          "an unconfigured sender fails loudly rather than appearing to work")

    # ================================================== the gates
    print("\n-- the four gates, in order -------------------------------------------")
    configure()
    channels.smtplib.SMTP = Recorder
    reset()
    check("GATE 1 unreachable: a malformed address is refused",
          raises(NotReachable, lambda: EmailChannel().send(
              recipient="not-an-address", subject="s", body="b", approval=Approved())))
    check("...before any connection is attempted", Recorder.steps == [],
          "reachability is a fact about the recipient, not about us")

    reset()
    check("GATE 2 unapproved: no approval is refused",
          all(raises(NotApproved, lambda a=a: EmailChannel().send(
              recipient="clinic@example.com", subject="s", body="b", approval=a))
              for a in (None, object())))
    check("...and still nothing was connected", Recorder.steps == [])

    reset()
    unconfigure()
    check("GATE 3 unconfigured: refused after reachable and approved",
          raises(ChannelNotConnected, lambda: EmailChannel().send(
              recipient="clinic@example.com", subject="s", body="b",
              approval=Approved())))
    configure()

    reset()
    first = EmailChannel().send(recipient="clinic@example.com", subject="s",
                                body="b", approval=Approved())
    check("a complete send is accepted", bool(first.provider_message_id),
          first.provider_message_id)
    check("GATE 4 duplicate: the same message a second time is refused",
          raises(AlreadySent, lambda: EmailChannel().send(
              recipient="clinic@example.com", subject="s", body="b",
              approval=Approved())),
          "one approval is consent to one message")
    check("NEGATIVE CONTROL: a different body is a different message",
          bool(EmailChannel().send(recipient="clinic@example.com", subject="s",
                                   body="different", approval=Approved())
               .provider_message_id),
          "so the guard is the message, not a blanket lock on the recipient")

    reset()
    approval = Approved()
    approval.sent_message_id = "<already@sent>"
    check("...and an approval that already records a send is refused",
          raises(AlreadySent, lambda: EmailChannel().send(
              recipient="clinic@example.com", subject="s", body="b",
              approval=approval)),
          "the durable half, when the caller persists it")

    # ================================================== the wire
    print("\n-- what actually goes on the wire -------------------------------------")
    reset()
    EmailChannel().send(recipient="clinic@example.com", subject="Your website",
                        body="Hello.", approval=Approved())
    names = [step[0] for step in Recorder.steps]
    check("the sequence is connect, starttls, login, send",
          names == ["connect", "starttls", "login", "send"], str(names))
    check("TLS is started before the credential is offered",
          names.index("starttls") < names.index("login"),
          "a password sent before STARTTLS is a password on the wire")
    message = Recorder.steps[-1][1]
    check("the message names the configured identity",
          message["From"] == FAKE["QEVIK_SMTP_FROM"], message["From"])
    check("...carries a Message-ID we chose", bool(message["Message-ID"]),
          "recorded, rather than one a relay invents after we stop looking")
    check("...and no signature was appended here",
          message.get_content().strip() == "Hello.",
          "compose() already ends the body with the licensed entity")

    # ================================================== injection
    print("\n-- header injection ---------------------------------------------------")
    reset()
    check("a newline in the subject is refused",
          raises(Unsendable, lambda: EmailChannel().send(
              recipient="clinic@example.com", subject="s\nBcc: someone@else.com",
              body="b", approval=Approved())),
          "a line break in a header is a second header")
    check("a newline in the recipient is refused",
          raises(NotReachable, lambda: EmailChannel().send(
              recipient="a@b.co\nBcc: x@y.z", subject="s", body="b",
              approval=Approved())),
          "caught even earlier, by the address shape")
    check("...and neither reached the transport", Recorder.steps == [])

    # ================================================== failure handling
    print("\n-- a refusal from the server ------------------------------------------")
    reset()
    channels.smtplib.SMTP = Rejects
    check("a rejected send raises rather than reporting success",
          raises(OutreachError, lambda: EmailChannel().send(
              recipient="clinic@example.com", subject="s", body="b",
              approval=Approved())))
    check("...and is not recorded as sent",
          not channels._ALREADY_SENT,
          "so a person may retry the same approved words")
    channels.smtplib.SMTP = Recorder

    # ================================================== scope
    print("\n-- what M1 did not do -------------------------------------------------")
    check("WhatsApp still cannot send",
          raises(ChannelNotConnected, lambda: WhatsAppChannel().send(
              recipient="0501234567", subject="", body="b", approval=Approved())),
          "not part of M1")
    from atlas_kernel.mission.toolrunner import DISPATCHABLE
    check("`smtp` is still not a dispatchable mission tool",
          "smtp" not in DISPATCHABLE,
          "email leaves this system only through an operator approval")
    check("NEGATIVE CONTROL: the tools that are dispatchable still are",
          {"site-publish", "http-fetch"} <= set(DISPATCHABLE))
finally:
    channels.smtplib.SMTP = real_smtp
    unconfigure()
    channels._ALREADY_SENT.clear()

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
print("\nNOT PROOF OF DELIVERY. No message was sent. Production evidence still "
      "required: a real inbox, with SPF, DKIM and DMARC passing.")
sys.exit(1 if FAILED else 0)

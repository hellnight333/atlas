#!/usr/bin/env python3
"""The exact text to send by hand, with what may not be said alongside it.

For the two prospects reachable on WhatsApp today. It prints the message and
nothing else formatted around it, so it can be selected and pasted without
picking up a heading or a bullet by accident.

Underneath the message it prints the evidence the one claim rests on, and the
claims that must not be made if they reply. That belongs on the same screen as
the message: the DO NOT SAY list is useless in a file nobody opens while
actually talking to someone.

Deliberately has no send path — the point is that a human sends this.

    manual_send.py                    # the WhatsApp-reachable prospects
    manual_send.py --slug demo-x
    manual_send.py --text-only        # just the message, for piping
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from atlas_kernel.outreach import WhatsAppChannel  # noqa: E402

DRAFTS = Path(os.environ.get("QEVIK_DRAFTS", "/var/lib/qevik/outreach"))


def load() -> list[tuple[str, dict]]:
    return [
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(DRAFTS.glob("*.json"))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", default="")
    parser.add_argument("--text-only", action="store_true")
    args = parser.parse_args(argv)

    whatsapp = WhatsAppChannel()
    drafts = load()
    if args.slug:
        drafts = [(s, d) for s, d in drafts if s == args.slug]
        if not drafts:
            raise SystemExit(f"no draft {args.slug!r}")
    else:
        # Only the ones that can actually be sent today. The other three need an
        # email address that Places does not provide, and listing them here as
        # "ready" would be the same overstatement the drafts themselves avoid.
        # Only what has been approved for manual sending. Showing an unapproved
        # draft on the same screen as an approved one is how the wrong message
        # gets pasted into the wrong chat.
        drafts = [
            (s, d)
            for s, d in drafts
            if d.get("status") == "APPROVED_FOR_MANUAL_SEND"
            and whatsapp.can_reach(d.get("phone", ""))
        ]

    for index, (slug, draft) in enumerate(drafts):  # noqa: B007 - slug is printed below
        if args.text_only:
            print(draft["whatsapp_body"])
            if index < len(drafts) - 1:
                print("\n" + "=" * 60 + "\n")
            continue

        print("=" * 72)
        print(f"  {draft['business']}")
        print(f"  send to {draft['phone']} on WhatsApp   ·   status: {draft['status']}")
        print(f"  slug: {slug}")
        print("=" * 72)
        print()
        print(draft["whatsapp_body"])
        print()
        print("-" * 72)
        print("  the claim rests on:")
        for item in draft.get("do_not_say", []):
            if item["reason"] == "NOT_VERIFIED":
                print(f"    ! never say: {item['claim']}")
        print(f"    demo verified live: {draft['demo_url']}")
        print()
        print("  if they reply, do NOT say:")
        shown = 0
        for item in draft.get("do_not_say", []):
            if item["reason"] == "THEIR_SITE_HAS_IT" and shown < 6:
                print(f"    x {item['claim']}")
                shown += 1
        for item in draft.get("do_not_say", []):
            if item["reason"] == "DEMO_DOES_NOT_HAVE_IT":
                print(f"    x {item['claim']}")
        print("    x that the appointment form books anything — it does not")
        print("    x the price, unless they ask first")
        print()
        print("  if they ask, reply with:")
        for question, answer in (draft.get("playbook") or {}).items():
            print(f"    [{question}]")
            for line in answer.splitlines():
                print(f"      {line}" if line else "")
            print()

    if not args.text_only:
        print("=" * 72)
        print(f"{len(drafts)} message(s) ready to send by hand. Nothing is sent by this tool.")
        print("After sending, record it:")
        print("  infra/experiment.py sent --slug <slug> --at 2026-08-19T14:30+04:00")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

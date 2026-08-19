#!/usr/bin/env python3
"""Approve specific drafts for manual sending. Sends nothing, contacts nobody.

The distinction this tool exists to hold: **approved is not sent.** A draft
moving to APPROVED means a person authorised these exact words to this exact
number. It does not mean anyone received them, and nothing here writes a send
time — that is a separate command, run after the operator confirms they actually
pressed send on their phone.

Getting that wrong in the obvious direction would quietly ruin the experiment.
If approval marked a prospect as contacted, the reply rate would be computed
against messages that were never delivered, and the one number this exercise
produces would be wrong in the flattering direction.

The approval is bound to a fingerprint of the message body. Editing the copy
afterwards invalidates it, because consent was to those words and not to the
slot they sat in.

    approve_send.py --slug demo-a --slug demo-b --by ayoub
    approve_send.py --status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.opportunity.models import BusinessEvent, OutreachStatus  # noqa: E402
from atlas_kernel.opportunity.repository import OpportunityRepository  # noqa: E402
from atlas_kernel.outreach import WhatsAppChannel, playbook  # noqa: E402

DRAFTS = Path(os.environ.get("QEVIK_DRAFTS", "/var/lib/qevik/outreach"))


def fingerprint(body: str) -> str:
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def load(slug: str) -> dict:
    path = DRAFTS / f"{slug}.json"
    if not path.exists():
        raise SystemExit(f"no draft {slug!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def save(slug: str, draft: dict) -> None:
    (DRAFTS / f"{slug}.json").write_text(
        json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def business_for(repo: OpportunityRepository, name: str):
    return next((b for b in repo.list_businesses() if b.name == name), None)


def approve(repo: OpportunityRepository, slug: str, by: str) -> int:
    draft = load(slug)
    body = draft["whatsapp_body"]

    # The channel must be able to deliver. Approving a WhatsApp message to a
    # landline authorises something that cannot happen.
    if not WhatsAppChannel().can_reach(draft.get("phone", "")):
        print(f"  REFUSED {slug}: {draft.get('phone')!r} cannot receive WhatsApp")
        return 1

    business = business_for(repo, draft["business"])
    if business is None:
        print(f"  REFUSED {slug}: no business record")
        return 1

    digest = fingerprint(body)
    approval_id = f"manual-{digest[:12]}"

    draft["status"] = "APPROVED_FOR_MANUAL_SEND"
    draft["approved_by"] = by
    draft["approved_at"] = datetime.now(UTC).isoformat()
    draft["approved_fingerprint"] = digest
    # Stays null. Only the operator confirming a real send fills this in.
    draft["sent_at"] = None
    draft["playbook"] = playbook(draft["demo_url"])
    save(slug, draft)

    for message in repo.messages_for(business.id, channel="whatsapp"):
        if message.status is not OutreachStatus.DRAFT:
            continue
        repo.save_message(
            message.model_copy(
                update={
                    "status": OutreachStatus.APPROVED,
                    "approval_id": approval_id,
                    "approved_fingerprint": digest,
                    # Explicitly not set. Approval is not delivery.
                    "sent_at": None,
                }
            )
        )

    repo.record_event(
        BusinessEvent(
            business_id=business.id,
            factory="outreach",
            kind="outreach_approved_for_manual_send",
            actor=by,
            detail={
                "channel": "whatsapp",
                "recipient": draft["phone"],
                "approval_id": approval_id,
                "message_fingerprint": digest,
                "demo_url": draft["demo_url"],
                # Recorded so a later reader knows what was approved was a
                # human pressing send, not a system gaining the ability to.
                "delivery": "manual_by_operator",
                "sent": False,
            },
        )
    )
    print(f"  approved {draft['business'][:42]:<44} -> {draft['phone']}  [{approval_id}]")
    return 0


def status(repo: OpportunityRepository) -> int:
    print(f"{'prospect':<44} {'phone':<16} {'status':<26} sent")
    print("-" * 96)
    for path in sorted(DRAFTS.glob("*.json")):
        draft = json.loads(path.read_text(encoding="utf-8"))
        print(
            f"{draft['business'][:42]:<44} "
            f"{draft.get('phone', '—'):<16} "
            f"{draft['status']:<26} "
            f"{draft.get('sent_at') or 'not sent'}"
        )
    print()
    print("Approved means a person authorised these words. It does not mean anyone")
    print("received them. Record a real send with:")
    print("  infra/experiment.py sent --slug <slug> --at 2026-08-19T14:30+04:00")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slug", action="append", default=[])
    parser.add_argument("--by", default="ayoub")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)

    repo = OpportunityRepository()
    if args.status or not args.slug:
        return status(repo)

    failures = sum(approve(repo, slug, args.by) for slug in args.slug)
    print()
    print(f"{len(args.slug) - failures} approved for manual sending. Nothing was sent.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

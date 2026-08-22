#!/usr/bin/env python3
"""Record and read the first commercial experiment. Sends nothing.

The first contact is made by hand, from a phone. This is how a person tells the
system what happened, and how the result is read back.

    experiment.py prepare                        # log the five drafts as prepared
    experiment.py sent --slug demo-x --at 2026-08-19T14:30+04:00
    experiment.py response --slug demo-x --type interested --says "..."
    experiment.py meeting --slug demo-x --happened --at ...
    experiment.py objection --slug demo-x --says "we already pay someone"
    experiment.py price --slug demo-x --amount 1500 --recurring
    experiment.py outcome --slug demo-x --result won
    experiment.py status                         # the funnel

Every subcommand appends an event. Nothing is overwritten, so a mistake is
corrected by recording what actually happened, not by editing the past.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "kernel"))

from atlas_kernel.opportunity.repository import OpportunityRepository
from atlas_kernel.opportunity.tenancy import ALL_TENANTS  # noqa: E402
from atlas_kernel.outreach import experiment as ex  # noqa: E402

DRAFTS = Path(os.environ.get("QEVIK_DRAFTS", "/var/lib/qevik/outreach"))


def when(value: str | None) -> datetime:
    """Parse a timestamp, insisting on a timezone.

    A naive time here is genuinely ambiguous: the operator is in +04:00 and the
    server records UTC, so "14:30" recorded four hours late silently corrupts
    the one measurement this experiment produces — how long a reply took.
    """
    if not value:
        return datetime.now(UTC)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SystemExit(
            f"{value!r} has no timezone. Write it as 2026-08-19T14:30+04:00 — "
            "a naive time is ambiguous between your clock and the server's."
        )
    return parsed


def drafts() -> dict[str, dict]:
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(DRAFTS.glob("*.json"))
    }


def business_for(repo: OpportunityRepository, name: str):
    return next((b for b in repo.list_businesses(tenant=ALL_TENANTS) if b.name == name), None)


def resolve(repo: OpportunityRepository, slug: str) -> tuple[str, dict]:
    available = drafts()
    draft = available.get(slug)
    if draft is None:
        raise SystemExit(f"no draft {slug!r}. Have: {', '.join(sorted(available))}")
    business = business_for(repo, draft["business"])
    if business is None:
        raise SystemExit(f"no business record for {draft['business']!r}")
    return business.id, draft


def cmd_prepare(repo: OpportunityRepository, args) -> int:
    for draft in drafts().values():
        business = business_for(repo, draft["business"])
        if business is None:
            print(f"  ! no business for {draft['business']!r}")
            continue
        body = draft["whatsapp_body"] if "WhatsApp" in draft["contact_method"] else draft["email_body"]
        repo.record_event(
            ex.record_prepared(
                business.id,
                prospect=draft["business"],
                channel="whatsapp" if "WhatsApp" in draft["contact_method"] else "email",
                body=body,
                demo_url=draft["demo_url"],
                claim=draft.get("email_subject", ""),
            )
        )
        print(f"  prepared  {draft['business'][:44]:<46} {ex.message_version(body)}")
    return 0


def cmd_sent(repo: OpportunityRepository, args) -> int:
    business_id, draft = resolve(repo, args.slug)
    channel = "whatsapp" if "WhatsApp" in draft["contact_method"] else "email"
    body = draft["whatsapp_body"] if channel == "whatsapp" else draft["email_body"]
    repo.record_event(
        ex.record_sent(
            business_id,
            prospect=draft["business"],
            channel=channel,
            body=body,
            sent_at=when(args.at),
        )
    )
    print(f"recorded as sent by hand: {draft['business']} via {channel}")
    return 0


def cmd_response(repo: OpportunityRepository, args) -> int:
    business_id, draft = resolve(repo, args.slug)
    repo.record_event(
        ex.record_response(
            business_id,
            response=ex.Response(args.type),
            at=when(args.at),
            verbatim=args.says or "",
        )
    )
    print(f"recorded response {args.type} for {draft['business']}")
    return 0


def cmd_meeting(repo: OpportunityRepository, args) -> int:
    business_id, draft = resolve(repo, args.slug)
    repo.record_event(
        ex.record_meeting(
            business_id, happened=args.happened, at=when(args.at), note=args.note or ""
        )
    )
    print(f"recorded meeting ({'held' if args.happened else 'not held'}) for {draft['business']}")
    return 0


def cmd_objection(repo: OpportunityRepository, args) -> int:
    business_id, draft = resolve(repo, args.slug)
    repo.record_event(
        ex.record_objection(business_id, objection=args.says, verbatim=args.verbatim or "")
    )
    print(f"recorded objection for {draft['business']}: {args.says}")
    return 0


def cmd_price(repo: OpportunityRepository, args) -> int:
    business_id, draft = resolve(repo, args.slug)
    accepted = None if args.accepted is None else args.accepted
    repo.record_event(
        ex.record_price(
            business_id,
            amount=args.amount,
            currency=args.currency,
            recurring=args.recurring,
            accepted=accepted,
        )
    )
    print(f"recorded price {args.amount} {args.currency} for {draft['business']}")
    return 0


def cmd_outcome(repo: OpportunityRepository, args) -> int:
    business_id, draft = resolve(repo, args.slug)
    repo.record_event(
        ex.record_outcome(business_id, result=ex.Result(args.result), reason=args.reason or "")
    )
    print(f"recorded outcome {args.result} for {draft['business']}")
    return 0


def cmd_status(repo: OpportunityRepository, args) -> int:
    rows = []
    for slug, draft in drafts().items():
        business = business_for(repo, draft["business"])
        if business is None:
            continue
        rows.append((slug, ex.fold(repo.timeline(business.id))))

    print(f"{'prospect':<40} {'channel':<10} {'version':<13} {'sent':<12} {'response':<15} result")
    print("-" * 104)
    for slug, state in rows:
        sent = (state["sent_at"] or "")[:10] or "—"
        print(
            f"{(state['prospect'] or slug)[:38]:<40} "
            f"{state['channel'] or '—':<10} "
            f"{state['message_version'] or '—':<13} "
            f"{sent:<12} "
            f"{state['response']:<15} "
            f"{state['result']}"
        )

    contacted = [s for _, s in rows if s["sent_at"]]
    replied = [s for s in contacted if s["response"] not in ("no_reply", "not_contacted")]
    print()
    print(f"prepared  : {len(rows)}")
    print(f"sent      : {len(contacted)}")
    print(f"replied   : {len(replied)}")
    print(f"meetings  : {sum(1 for s in contacted if s['meeting'])}")
    print(f"won       : {sum(1 for _, s in rows if s['result'] == 'won')}")

    objections: dict[str, int] = {}
    for _, state in rows:
        for objection in state["objections"]:
            objections[objection] = objections.get(objection, 0) + 1
    if objections:
        print("\nobjections, most common first — this is what to change:")
        for objection, count in sorted(objections.items(), key=lambda kv: -kv[1]):
            print(f"  {count:>2}x  {objection}")

    if not contacted:
        print("\nNothing has been sent. The experiment has not started.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("prepare")

    p = sub.add_parser("sent")
    p.add_argument("--slug", required=True)
    p.add_argument("--at", help="ISO 8601 with timezone, e.g. 2026-08-19T14:30+04:00")

    p = sub.add_parser("response")
    p.add_argument("--slug", required=True)
    p.add_argument("--type", required=True, choices=[str(r) for r in ex.Response])
    p.add_argument("--says", help="their words, unsummarised")
    p.add_argument("--at")

    p = sub.add_parser("meeting")
    p.add_argument("--slug", required=True)
    p.add_argument("--happened", action="store_true")
    p.add_argument("--note")
    p.add_argument("--at")

    p = sub.add_parser("objection")
    p.add_argument("--slug", required=True)
    p.add_argument("--says", required=True, help="short label, so it can be counted")
    p.add_argument("--verbatim")

    p = sub.add_parser("price")
    p.add_argument("--slug", required=True)
    p.add_argument("--amount", required=True)
    p.add_argument("--currency", default="AED")
    p.add_argument("--recurring", action="store_true")
    p.add_argument("--accepted", type=lambda v: v.lower() == "true", default=None)

    p = sub.add_parser("outcome")
    p.add_argument("--slug", required=True)
    p.add_argument("--result", required=True, choices=[str(r) for r in ex.Result])
    p.add_argument("--reason")

    sub.add_parser("status")

    args = parser.parse_args(argv)
    repo = OpportunityRepository()
    return {
        "prepare": cmd_prepare,
        "sent": cmd_sent,
        "response": cmd_response,
        "meeting": cmd_meeting,
        "objection": cmd_objection,
        "price": cmd_price,
        "outcome": cmd_outcome,
        "status": cmd_status,
    }[args.command](repo, args)


if __name__ == "__main__":
    raise SystemExit(main())

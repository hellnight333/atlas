"""Persistence for the Opportunity Factory.

Its own repository rather than more methods on ``AtlasRepository``, matching the
Media Factory. Same conventions: parameterised ``text()`` SQL, one
``SessionLocal`` per operation, Pydantic models in and out.

Two things here are not merely storage:

* **The event log is append-only.** Metrics are derived from it, and a mutable
  stage column cannot answer "how many did we contact and hear nothing from".
* **The suppression list and contact history are durable.** Both are no-spam
  guarantees, and a guarantee that evaporates on restart is not one. That is the
  reason this file exists at all rather than the service keeping everything in
  memory.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from ..db import SessionLocal
from .identity import place_id, strong_keys, with_identity
from .models import (
    OPPORTUNITY_FACTORY,
    Business,
    BusinessEvent,
    Evidence,
    Finding,
    Opportunity,
    OutreachMessage,
    Proposal,
    ProposalClaim,
)
from .outreach import ContactHistory, SuppressionList
from .tenancy import (
    TenantId,
)
from .tenancy import (
    predicate as _tenant_predicate,
)
from .tenancy import (
    require as _require_tenant,
)


def _now() -> datetime:
    return datetime.now(UTC)


def _decoded(value: object) -> object:
    """JSONB comes back already decoded; a plain TEXT column would not.

    Tolerating both costs three lines and removes a class of surprise that only
    shows up once a column type changes under a query that looked fine.
    """
    if isinstance(value, str | bytes | bytearray):
        return json.loads(value)
    return value


class OpportunityRepository:
    # -- source layer -----------------------------------------------------

    def resolve_business(self, business: Business) -> tuple[Business, bool]:
        """Find this company or create it. Returns the record and whether it is new.

        The single most important method here. Autonomous discovery means the
        same clinic arrives from Google Maps this week and a directory the next,
        and without resolution the funnel double-counts it, the cooldown guards
        only one copy, and someone eventually receives two proposals from the
        same sender.

        Matching is on strong keys only -- domain, email, phone. A shared name
        and city is *not* enough, however plausible: merging two different
        companies would attach one business's findings to another's proposal,
        which is precisely the failure the evidence rule exists to prevent. A
        missed merge costs a duplicate row; a wrong merge costs the claim.
        """
        stamped = with_identity(business)
        keys = sorted(strong_keys(set(stamped.identity_keys)))
        if keys:
            with SessionLocal() as session:
                rows = (
                    session.execute(
                        text("""
                        SELECT * FROM atlas_businesses
                        WHERE identity_keys ?| :keys
                        ORDER BY first_seen_at, id
                        """),
                        {"keys": keys},
                    )
                    .mappings()
                    .all()
                )
            # A differing place id means a different physical location, and it
            # overrides every other agreement. Branches of one clinic share a
            # domain and a switchboard number, so strong-key matching alone
            # merged twenty audited Dubai clinics into fifteen businesses --
            # Dr. Joy's three branches became one record, and the evidence
            # gathered on one branch's website was attached to another's.
            #
            # Filtered here rather than in `is_same_business` because this is
            # where the decision is actually taken; the pure function is not on
            # this path.
            incoming_place = place_id(stamped)
            if incoming_place:
                rows = [
                    row
                    for row in rows
                    if (row.get("metadata") or {}).get("place_id") in (None, "", incoming_place)
                ]

            if rows:
                # A sighting can match more than one stored record -- a shared
                # switchboard number, or a new record that turns out to bridge
                # two Atlas already had. The oldest wins, deterministically:
                # ordering by (first_seen_at, id) rather than taking whatever
                # the planner returned first means the same input resolves the
                # same way every time, which "LIMIT 1" alone does not guarantee.
                #
                # The others are deliberately **not** folded in. Merging two
                # established customer records is irreversible and would take
                # one company's history into another's; a human decides that.
                # ``find_possible_duplicates`` surfaces them.
                existing = self._business_from_row(rows[0])
                merged = with_identity(existing.merged_with(stamped))
                self.save_business(merged)
                return merged, False

        self.save_business(stamped)
        return stamped, True

    def find_possible_duplicates(self, business: Business, *,
                                 tenant: TenantId | None = None) -> list[Business]:
        """TENANT_SCOPED. Companies sharing a name and place but nothing stronger.

        The most dangerous read in this module. Unscoped it answers "does anyone
        else in the system know this company", which discloses another tenant's
        customer list one probe at a time.

        Surfaced for a human. Never merged automatically -- two branches of one
        clinic and two unrelated companies with a common name look identical
        from here.
        """
        from .identity import normalise_name

        tenant = _require_tenant(tenant, method="find_possible_duplicates")
        where, params = _tenant_predicate(tenant)
        key = f"name:{normalise_name(business.name, business.geography)}"
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(f"SELECT * FROM atlas_businesses WHERE identity_keys ? :key "
                         f"AND {where}"),
                    {"key": key, **params},
                )
                .mappings()
                .all()
            )
        candidates = [self._business_from_row(row) for row in rows if row["id"] != business.id]
        stamped = strong_keys(set(with_identity(business).identity_keys))
        return [
            candidate
            for candidate in candidates
            if not (strong_keys(set(candidate.identity_keys)) & stamped)
        ]

    @staticmethod
    def _business_from_row(row) -> Business:
        payload = dict(row)
        payload["identity_keys"] = list(_decoded(payload.get("identity_keys") or []))
        payload["sources"] = list(_decoded(payload.get("sources") or []))
        payload["metadata"] = dict(_decoded(payload.get("metadata") or {}))
        return Business(**payload)

    def save_business(self, business: Business) -> Business:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_businesses
                    (id, name, geography, website, email, phone, identity_keys,
                     sources, metadata, first_seen_at, last_seen_at)
                VALUES (:id, :name, :geography, :website, :email, :phone,
                        :identity_keys, :sources, :metadata, :first_seen_at,
                        :last_seen_at)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    geography = EXCLUDED.geography,
                    website = EXCLUDED.website,
                    email = EXCLUDED.email,
                    phone = EXCLUDED.phone,
                    identity_keys = EXCLUDED.identity_keys,
                    sources = EXCLUDED.sources,
                    metadata = EXCLUDED.metadata,
                    last_seen_at = EXCLUDED.last_seen_at
                """),
                {
                    **business.model_dump(exclude={"metadata", "identity_keys", "sources"}),
                    "identity_keys": json.dumps(business.identity_keys),
                    "sources": json.dumps(business.sources),
                    "metadata": json.dumps(business.metadata),
                },
            )
            session.commit()
        return business

    def get_business(self, business_id: str, *,
                     tenant: TenantId | None = None) -> Business | None:
        """TENANT_SCOPED. Returns None for another tenant's business.

        None rather than a refusal on purpose: the caller turns it into a 404,
        and a 403 would confirm the record exists.
        """
        tenant = _require_tenant(tenant, method="get_business")
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_businesses WHERE id = :id"), {"id": business_id}
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        from .tenancy import owns
        if not owns(row.get("tenant_id"), tenant):
            return None
        return self._business_from_row(row)

    def list_businesses(self, *, tenant: TenantId | None = None) -> list[Business]:
        """TENANT_SCOPED. Every company *this tenant* knows about.

        Not filtered by niche: a Business has no niche. It is a company, which
        may be qualified under several niches over its life — the niche lives on
        the Opportunity, which is the thing that has one.
        """
        tenant = _require_tenant(tenant, method="list_businesses")
        where, params = _tenant_predicate(tenant)
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(f"SELECT * FROM atlas_businesses WHERE {where} "
                         "ORDER BY first_seen_at DESC"), params)
                .mappings()
                .all()
            )
        return [self._business_from_row(row) for row in rows]

    # ---------------------------------------------------------------- sightings

    def record_sighting(self, sighting, classification, *,
                        tenant: TenantId | None = None) -> bool:
        """Store one observation of one entity. Returns whether it was stored.

        `False` means this exact sighting — same business, same source, same
        source id, same instant — was already recorded, so the scan is being
        replayed. Not an error: a scan re-run after a crash must be safe, and
        the unique index is what makes it so rather than a check that races
        itself the moment two workers scan the same market.

        The classification is stored **as it was at the time** and never
        recomputed. A sighting that was DISCOVERED_BY_QEVIK in August stays
        that, even though the business is KNOWN by September; rewriting it
        would make the history agree with the present.
        """
        payload = {
            "business_id": sighting.business_id,
            "tenant_id": str(tenant or ""),
            "name": sighting.name,
            "source": sighting.source,
            "source_id": sighting.source_id,
            "source_url": sighting.source_url,
            "country": sighting.country,
            "city": sighting.city,
            "origin": sighting.origin.value,
            "state": classification.state.value,
            "because": classification.because,
            "claims": classification.claims_about_the_world,
            "novelty": json.dumps(
                sighting.novelty.model_dump(mode="json")
                if sighting.novelty else None),
            "evidence": json.dumps(
                [e.model_dump(mode="json") for e in sighting.evidence]),
            "observed_at": sighting.observed_at,
        }
        with SessionLocal() as session:
            done = session.execute(
                text("""
                INSERT INTO atlas_sightings (
                    business_id, tenant_id, name, source, source_id, source_url,
                    country, city, origin, state, because,
                    claims_about_the_world, novelty, evidence, observed_at)
                VALUES (
                    :business_id, :tenant_id, :name, :source, :source_id,
                    :source_url, :country, :city, :origin, :state, :because,
                    :claims, :novelty, :evidence, :observed_at)
                ON CONFLICT DO NOTHING
                """),
                payload)
            session.commit()
            return bool(done.rowcount)

    def sightings_for(self, business_id: str, *,
                      tenant: TenantId | None = None) -> list[dict]:
        """Every recorded observation of one entity, oldest first.

        The "previous observations" a discovery record has to carry. Returned
        as dicts because a sighting row is a historical record rather than a
        live model — reconstructing `Sighting` objects would invite somebody to
        edit and save one.
        """
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT * FROM atlas_sightings
                WHERE business_id = :business_id
                  AND (:tenant = '' OR tenant_id = :tenant)
                ORDER BY observed_at, id
                """),
                {"business_id": business_id, "tenant": str(tenant or "")},
            ).mappings().all()
        return [{
            "business_id": row["business_id"], "name": row["name"],
            "source": row["source"], "source_id": row["source_id"],
            "source_url": row["source_url"], "country": row["country"],
            "city": row["city"], "origin": row["origin"],
            "state": row["state"], "because": row["because"],
            "claims_about_the_world": row["claims_about_the_world"],
            "novelty": _decoded(row["novelty"]),
            "evidence": _decoded(row["evidence"]) or [],
            "observed_at": row["observed_at"].isoformat()
            if row["observed_at"] else "",
        } for row in rows]

    def recent_discoveries(self, *, limit: int = 50,
                           tenant: TenantId | None = None) -> list[dict]:
        """The newest sightings that were not already known, newest first.

        `KNOWN` is excluded because a list of things Qevik already had is not a
        discovery feed. The state is returned verbatim so a surface can show
        which of them actually claim anything about the world.
        """
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT * FROM atlas_sightings
                WHERE state <> 'KNOWN'
                  AND (:tenant = '' OR tenant_id = :tenant)
                ORDER BY observed_at DESC, id DESC
                LIMIT :limit
                """),
                {"limit": max(1, min(int(limit), 500)),
                 "tenant": str(tenant or "")},
            ).mappings().all()
        return [{
            "business_id": row["business_id"], "name": row["name"],
            "source": row["source"], "source_url": row["source_url"],
            "country": row["country"], "city": row["city"],
            "state": row["state"], "because": row["because"],
            "claims_about_the_world": row["claims_about_the_world"],
            "observed_at": row["observed_at"].isoformat()
            if row["observed_at"] else "",
        } for row in rows]

    # ---------------------------------------------------------------- signals

    def save_signal(self, signal, ranked, *,
                    tenant: TenantId | None = None) -> bool:
        """Store one detected opportunity. Returns whether it was new.

        `False` means this business already has an open signal of this kind
        from this source, so the nightly scan re-detected something already on
        the operator's list. Not an error, and not an update either: the
        detection that is on the list is the one that was made, and quietly
        overwriting its score and evidence would rewrite what somebody is
        looking at while they look at it.
        """
        payload = {
            "id": signal.id, "tenant_id": str(tenant or ""),
            "business_id": signal.business_id, "kind": signal.kind.value,
            "source": signal.source, "scope": signal.scope,
            "payload": json.dumps(signal.summary()),
            "fingerprints": json.dumps(sorted(
                {f for o in signal.observations for f in o.fingerprints})),
            "score": ranked.score,
            # `None` stays `None`. See the column comment: a DEFAULT 0 here
            # would undo the whole cost_status rule from a schema definition.
            "value_amount": signal.estimated_value,
            "value_status": signal.value_status,
            "needs_approval": not signal.is_actionable_without_a_person,
            "detected_at": signal.created_at,
        }
        with SessionLocal() as session:
            done = session.execute(
                text("""
                INSERT INTO atlas_signals (
                    id, tenant_id, business_id, kind, source, scope, payload,
                    evidence_fingerprints, score, value_amount, value_status,
                    needs_approval, detected_at)
                VALUES (
                    :id, :tenant_id, :business_id, :kind, :source, :scope,
                    :payload, :fingerprints, :score, :value_amount,
                    :value_status, :needs_approval, :detected_at)
                ON CONFLICT DO NOTHING
                """),
                payload)
            session.commit()
            return bool(done.rowcount)

    def open_signals(self, *, limit: int = 25,
                     tenant: TenantId | None = None) -> list[dict]:
        """Detected opportunities, best first. Never demo rows.

        Ordered by score then detected_at, both descending, with the id as the
        final tiebreak so two reads of the same data give the same order.
        """
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT * FROM atlas_signals
                WHERE state = 'open'
                  AND (:tenant = '' OR tenant_id = :tenant)
                ORDER BY score DESC NULLS LAST, detected_at DESC, id
                LIMIT :limit
                """),
                {"limit": max(1, min(int(limit), 200)),
                 "tenant": str(tenant or "")},
            ).mappings().all()
        return [self._signal_from_row(row) for row in rows]

    def get_signal(self, signal_id: str, *,
                   tenant: TenantId | None = None) -> dict | None:
        with SessionLocal() as session:
            row = session.execute(
                text("""
                SELECT * FROM atlas_signals
                WHERE id = :id AND (:tenant = '' OR tenant_id = :tenant)
                """),
                {"id": signal_id, "tenant": str(tenant or "")},
            ).mappings().first()
        return self._signal_from_row(row) if row else None

    @staticmethod
    def _signal_from_row(row) -> dict:
        return {
            "id": row["id"], "business_id": row["business_id"],
            "kind": row["kind"], "source": row["source"], "scope": row["scope"],
            "score": row["score"],
            "evidence_fingerprints": _decoded(row["evidence_fingerprints"]) or [],
            # The four parts, exactly as the signal recorded them.
            "detail": _decoded(row["payload"]) or {},
            "value": {"amount": row["value_amount"],
                      "status": row["value_status"]},
            "needs_approval": row["needs_approval"],
            "state": row["state"],
            "detected_at": row["detected_at"].isoformat()
            if row["detected_at"] else "",
        }

    def save_finding(self, finding: Finding) -> Finding:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_findings
                    (id, business_id, kind, severity, statement, evidence, confidence, detected_at)
                VALUES (:id, :business_id, :kind, :severity, :statement, :evidence,
                        :confidence, :detected_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": finding.id,
                    "business_id": finding.business_id,
                    "kind": finding.kind.value,
                    "severity": finding.severity.value,
                    "statement": finding.statement,
                    "evidence": json.dumps(
                        [item.model_dump(mode="json") for item in finding.evidence]
                    ),
                    "confidence": finding.confidence,
                    "detected_at": finding.detected_at,
                },
            )
            session.commit()
        return finding

    def list_findings(self, business_id: str) -> list[Finding]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT * FROM atlas_findings WHERE business_id = :pid ORDER BY detected_at"
                    ),
                    {"pid": business_id},
                )
                .mappings()
                .all()
            )
        return [
            Finding(
                id=row["id"],
                business_id=row["business_id"],
                kind=row["kind"],
                severity=row["severity"],
                statement=row["statement"],
                evidence=[Evidence(**item) for item in _decoded(row["evidence"])],
                confidence=row["confidence"],
                detected_at=row["detected_at"],
            )
            for row in rows
        ]

    def save_opportunity(self, opportunity: Opportunity) -> Opportunity:
        with SessionLocal() as session:
            for finding in opportunity.findings:
                session.execute(
                    text("""
                    INSERT INTO atlas_findings
                        (id, business_id, kind, severity, statement, evidence, confidence, detected_at)
                    VALUES (:id, :business_id, :kind, :severity, :statement, :evidence,
                            :confidence, :detected_at)
                    ON CONFLICT (id) DO NOTHING
                    """),
                    {
                        "id": finding.id,
                        "business_id": finding.business_id,
                        "kind": finding.kind.value,
                        "severity": finding.severity.value,
                        "statement": finding.statement,
                        "evidence": json.dumps(
                            [item.model_dump(mode="json") for item in finding.evidence]
                        ),
                        "confidence": finding.confidence,
                        "detected_at": finding.detected_at,
                    },
                )
            session.execute(
                text("""
                INSERT INTO atlas_opportunities
                    (id, business_id, niche, stage, score, estimated_value, currency,
                     finding_ids, created_at, updated_at)
                VALUES (:id, :business_id, :niche, :stage, :score, :estimated_value,
                        :currency, :finding_ids, :created_at, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    stage = EXCLUDED.stage,
                    score = EXCLUDED.score,
                    finding_ids = EXCLUDED.finding_ids,
                    updated_at = EXCLUDED.updated_at
                """),
                {
                    "id": opportunity.id,
                    "business_id": opportunity.business_id,
                    "niche": opportunity.niche,
                    "stage": opportunity.stage.value,
                    "score": opportunity.score,
                    "estimated_value": opportunity.estimated_value,
                    "currency": opportunity.currency,
                    "finding_ids": json.dumps([f.id for f in opportunity.findings]),
                    "created_at": opportunity.created_at,
                    "updated_at": _now(),
                },
            )
            session.commit()
        return opportunity

    # -- offer layer ------------------------------------------------------

    def save_proposal(self, proposal: Proposal) -> Proposal:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_proposals
                    (id, business_id, opportunity_id, subject, body, claims, offer,
                     price, currency, findings_fingerprint, generator, generated_at)
                VALUES (:id, :business_id, :opportunity_id, :subject, :body, :claims,
                        :offer, :price, :currency, :findings_fingerprint, :generator,
                        :generated_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    **proposal.model_dump(exclude={"claims"}),
                    "claims": json.dumps([c.model_dump() for c in proposal.claims]),
                },
            )
            session.commit()
        return proposal

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_proposals WHERE id = :id"), {"id": proposal_id}
                )
                .mappings()
                .first()
            )
        if not row:
            return None
        payload = dict(row)
        payload["claims"] = [ProposalClaim(**c) for c in _decoded(payload["claims"])]
        return Proposal(**payload)

    def save_message(self, message: OutreachMessage) -> OutreachMessage:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_outreach_messages
                    (id, proposal_id, business_id, channel, recipient, subject, body,
                     status, approval_id, approved_fingerprint, provider_message_id,
                     detail, created_at, sent_at)
                VALUES (:id, :proposal_id, :business_id, :channel, :recipient, :subject,
                        :body, :status, :approval_id, :approved_fingerprint,
                        :provider_message_id, :detail, :created_at, :sent_at)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    approval_id = EXCLUDED.approval_id,
                    approved_fingerprint = EXCLUDED.approved_fingerprint,
                    provider_message_id = EXCLUDED.provider_message_id,
                    detail = EXCLUDED.detail,
                    sent_at = EXCLUDED.sent_at
                """),
                {**message.model_dump(), "status": message.status.value},
            )
            session.commit()
        return message

    # -- measurement ------------------------------------------------------

    def messages_for(
        self, business_id: str, *, channel: str | None = None
    ) -> list[OutreachMessage]:
        """Every outreach message for one business, oldest first."""
        clause = " AND channel = :c" if channel else ""
        with SessionLocal() as session:
            rows = session.execute(
                text(
                    "SELECT * FROM atlas_outreach_messages"
                    f" WHERE business_id = :b{clause} ORDER BY created_at"
                ),
                {"b": business_id, **({"c": channel} if channel else {})},
            ).mappings()
            return [OutreachMessage(**dict(row)) for row in rows]

    def delete_unsent_drafts(self, business_id: str, *, channels: tuple[str, ...]) -> int:
        """Remove drafts that were never sent, so re-drafting replaces rather than accumulates.

        Deliberately narrow. A row is removable only if it is still a draft *and*
        carries no approval, no fingerprint and no send time — three independent
        signals, because a status column is one edit away from lying and the
        thing being protected is commercial history that cannot be rebuilt.

        Anything approved or sent is left exactly where it is.
        """
        with SessionLocal() as session:
            result = session.execute(
                text(
                    "DELETE FROM atlas_outreach_messages"
                    " WHERE business_id = :b AND channel = ANY(:c)"
                    "   AND status = 'draft'"
                    "   AND sent_at IS NULL"
                    "   AND approval_id IS NULL"
                    "   AND approved_fingerprint IS NULL"
                ),
                {"b": business_id, "c": list(channels)},
            )
            session.commit()
            return result.rowcount or 0

    def record_event(self, event: BusinessEvent) -> BusinessEvent:
        """Append to a business's permanent history.

        Public on purpose: any factory writes here. It is the one call another
        factory needs in order to contribute to the timeline, and it takes a
        business rather than an opportunity precisely so a deployment or a
        support ticket can use it.
        """
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_business_events
                    (id, business_id, factory, kind, opportunity_id, actor, detail, at)
                VALUES (:id, :business_id, :factory, :kind, :opportunity_id, :actor,
                        :detail, :at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": event.id,
                    "business_id": event.business_id,
                    "factory": event.factory,
                    "kind": str(event.kind),
                    "opportunity_id": event.opportunity_id,
                    "actor": event.actor,
                    "detail": json.dumps(event.detail),
                    "at": event.at,
                },
            )
            session.commit()
        return event

    def timeline(self, business_id: str, *, factory: str | None = None) -> list[BusinessEvent]:
        """One company's whole history, oldest first.

        The answer to "what has Atlas ever done with this company" -- outreach,
        and in time deployments, listings, published media and support. Pass
        ``factory`` for one part of Atlas's contribution; omit it for the
        chronology, which is the point of keeping them in one table.
        """
        query = "SELECT * FROM atlas_business_events WHERE business_id = :bid"
        params: dict[str, object] = {"bid": business_id}
        if factory is not None:
            query += " AND factory = :factory"
            params["factory"] = factory
        query += " ORDER BY at, id"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).mappings().all()
        return [self._event_from_row(row) for row in rows]

    @staticmethod
    def _event_from_row(row) -> BusinessEvent:
        return BusinessEvent(
            id=row["id"],
            business_id=row["business_id"],
            factory=row["factory"],
            kind=row["kind"],
            opportunity_id=row["opportunity_id"],
            actor=row["actor"],
            detail=dict(_decoded(row["detail"])),
            at=row["at"],
        )

    def list_events(self, niche: str | None = None, *,
                    tenant: TenantId | None = None) -> list[BusinessEvent]:
        """TENANT_SCOPED. Outreach events, optionally for one niche.

        Scoped through the business, which is where ownership lives — an event
        has no tenant of its own and must not grow one.

        Scoped to this factory. The timeline is shared, and counting a website
        deployment as a funnel stage would corrupt every rate downstream the
        moment a second factory starts writing to it.
        """
        tenant = _require_tenant(tenant, method="list_events")
        where, tenant_params = _tenant_predicate(tenant, alias="b")
        query = ("SELECT e.* FROM atlas_business_events e "
                 "JOIN atlas_businesses b ON b.id = e.business_id")
        params: dict[str, object] = {"factory": OPPORTUNITY_FACTORY, **tenant_params}
        if niche:
            query += (
                " JOIN atlas_opportunities o ON o.id = e.opportunity_id"
                f" WHERE o.niche = :niche AND e.factory = :factory AND {where}"
            )
            params["niche"] = niche
        else:
            query += f" WHERE e.factory = :factory AND {where}"
        query += " ORDER BY e.at, e.id"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).mappings().all()
        return [self._event_from_row(row) for row in rows]

    # -- no-spam guarantees, made durable ---------------------------------

    def suppress(self, entry: str, reason: str = "") -> None:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_outreach_suppressions (entry, reason, created_at)
                VALUES (:entry, :reason, :created_at)
                ON CONFLICT (entry) DO UPDATE SET reason = EXCLUDED.reason
                """),
                {"entry": entry.strip().lower(), "reason": reason, "created_at": _now()},
            )
            session.commit()

    def load_suppression(self) -> SuppressionList:
        with SessionLocal() as session:
            rows = session.execute(text("SELECT entry FROM atlas_outreach_suppressions")).all()
        return SuppressionList(row[0] for row in rows)

    def load_contact_history(self, *, tenant: TenantId | None = None) -> ContactHistory:
        """TENANT_SCOPED. When each business was last successfully contacted.

        Read from sent messages rather than a separate counter, so the cooldown
        cannot drift away from what was actually delivered.

        Scoped, unlike suppression. Contact history describes *a tenant's* own
        activity — who they have written to and when — and one tenant inferring
        another's outreach volume from a shared cooldown would be a disclosure.
        Suppression is the deliberate opposite: see `load_suppression`.
        """
        tenant = _require_tenant(tenant, method="load_contact_history")
        where, params = _tenant_predicate(tenant, alias="b")
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(f"""
                SELECT m.business_id, MAX(m.sent_at) AS last_sent
                FROM atlas_outreach_messages m
                JOIN atlas_businesses b ON b.id = m.business_id
                WHERE m.status = 'sent' AND m.sent_at IS NOT NULL AND {where}
                GROUP BY m.business_id
                """), params
                )
                .mappings()
                .all()
            )
        return ContactHistory({row["business_id"]: row["last_sent"] for row in rows})

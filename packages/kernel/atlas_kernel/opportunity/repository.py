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
from .identity import strong_keys, with_identity
from .models import (
    Business,
    Evidence,
    Finding,
    Opportunity,
    OutreachMessage,
    PipelineEvent,
    Proposal,
    ProposalClaim,
)
from .outreach import ContactHistory, SuppressionList


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

    def find_possible_duplicates(self, business: Business) -> list[Business]:
        """Companies sharing a name and place but nothing stronger.

        Surfaced for a human. Never merged automatically -- two branches of one
        clinic and two unrelated companies with a common name look identical
        from here.
        """
        from .identity import normalise_name

        key = f"name:{normalise_name(business.name, business.geography)}"
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text("SELECT * FROM atlas_businesses WHERE identity_keys ? :key"),
                    {"key": key},
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

    def get_business(self, business_id: str) -> Business | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_businesses WHERE id = :id"), {"id": business_id}
                )
                .mappings()
                .first()
            )
        return self._business_from_row(row) if row else None

    def list_businesses(self) -> list[Business]:
        """Every company Atlas knows about.

        Not filtered by niche: a Business has no niche. It is a company, which
        may be qualified under several niches over its life — the niche lives on
        the Opportunity, which is the thing that has one.
        """
        with SessionLocal() as session:
            rows = (
                session.execute(text("SELECT * FROM atlas_businesses ORDER BY first_seen_at DESC"))
                .mappings()
                .all()
            )
        return [self._business_from_row(row) for row in rows]

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

    def record_event(self, event: PipelineEvent) -> PipelineEvent:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_pipeline_events
                    (id, opportunity_id, business_id, kind, actor, detail, at)
                VALUES (:id, :opportunity_id, :business_id, :kind, :actor, :detail, :at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": event.id,
                    "opportunity_id": event.opportunity_id,
                    "business_id": event.business_id,
                    "kind": event.kind.value,
                    "actor": event.actor,
                    "detail": json.dumps(event.detail),
                    "at": event.at,
                },
            )
            session.commit()
        return event

    def list_events(self, niche: str | None = None) -> list[PipelineEvent]:
        query = "SELECT e.* FROM atlas_pipeline_events e"
        params: dict[str, object] = {}
        if niche:
            query += " JOIN atlas_opportunities o ON o.id = e.opportunity_id WHERE o.niche = :niche"
            params["niche"] = niche
        query += " ORDER BY e.at"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).mappings().all()
        return [
            PipelineEvent(
                id=row["id"],
                opportunity_id=row["opportunity_id"],
                business_id=row["business_id"],
                kind=row["kind"],
                actor=row["actor"],
                detail=_decoded(row["detail"]),
                at=row["at"],
            )
            for row in rows
        ]

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

    def load_contact_history(self) -> ContactHistory:
        """When each business was last successfully contacted.

        Read from sent messages rather than a separate counter, so the cooldown
        cannot drift away from what was actually delivered.
        """
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text("""
                SELECT business_id, MAX(sent_at) AS last_sent
                FROM atlas_outreach_messages
                WHERE status = 'sent' AND sent_at IS NOT NULL
                GROUP BY business_id
                """)
                )
                .mappings()
                .all()
            )
        return ContactHistory({row["business_id"]: row["last_sent"] for row in rows})

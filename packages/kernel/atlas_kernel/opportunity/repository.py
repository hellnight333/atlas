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
from .models import (
    Evidence,
    Finding,
    Opportunity,
    OutreachMessage,
    PipelineEvent,
    Proposal,
    ProposalClaim,
    Prospect,
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

    def save_prospect(self, prospect: Prospect) -> Prospect:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_prospects
                    (id, name, niche, geography, website, email, phone, source,
                     metadata, discovered_at)
                VALUES (:id, :name, :niche, :geography, :website, :email, :phone,
                        :source, :metadata, :discovered_at)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    website = EXCLUDED.website,
                    email = EXCLUDED.email,
                    phone = EXCLUDED.phone,
                    metadata = EXCLUDED.metadata
                """),
                {
                    **prospect.model_dump(exclude={"metadata"}),
                    "metadata": json.dumps(prospect.metadata),
                },
            )
            session.commit()
        return prospect

    def get_prospect(self, prospect_id: str) -> Prospect | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_prospects WHERE id = :id"), {"id": prospect_id}
                )
                .mappings()
                .first()
            )
        return Prospect(**dict(row)) if row else None

    def list_prospects(self, niche: str | None = None) -> list[Prospect]:
        query = "SELECT * FROM atlas_prospects"
        params: dict[str, object] = {}
        if niche:
            query += " WHERE niche = :niche"
            params["niche"] = niche
        query += " ORDER BY discovered_at DESC"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).mappings().all()
        return [Prospect(**dict(row)) for row in rows]

    def save_finding(self, finding: Finding) -> Finding:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_findings
                    (id, prospect_id, kind, severity, statement, evidence, detected_at)
                VALUES (:id, :prospect_id, :kind, :severity, :statement, :evidence, :detected_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": finding.id,
                    "prospect_id": finding.prospect_id,
                    "kind": finding.kind.value,
                    "severity": finding.severity.value,
                    "statement": finding.statement,
                    "evidence": json.dumps(
                        [item.model_dump(mode="json") for item in finding.evidence]
                    ),
                    "detected_at": finding.detected_at,
                },
            )
            session.commit()
        return finding

    def list_findings(self, prospect_id: str) -> list[Finding]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT * FROM atlas_findings WHERE prospect_id = :pid ORDER BY detected_at"
                    ),
                    {"pid": prospect_id},
                )
                .mappings()
                .all()
            )
        return [
            Finding(
                id=row["id"],
                prospect_id=row["prospect_id"],
                kind=row["kind"],
                severity=row["severity"],
                statement=row["statement"],
                evidence=[Evidence(**item) for item in _decoded(row["evidence"])],
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
                        (id, prospect_id, kind, severity, statement, evidence, detected_at)
                    VALUES (:id, :prospect_id, :kind, :severity, :statement, :evidence, :detected_at)
                    ON CONFLICT (id) DO NOTHING
                    """),
                    {
                        "id": finding.id,
                        "prospect_id": finding.prospect_id,
                        "kind": finding.kind.value,
                        "severity": finding.severity.value,
                        "statement": finding.statement,
                        "evidence": json.dumps(
                            [item.model_dump(mode="json") for item in finding.evidence]
                        ),
                        "detected_at": finding.detected_at,
                    },
                )
            session.execute(
                text("""
                INSERT INTO atlas_opportunities
                    (id, prospect_id, niche, stage, score, estimated_value, currency,
                     finding_ids, created_at, updated_at)
                VALUES (:id, :prospect_id, :niche, :stage, :score, :estimated_value,
                        :currency, :finding_ids, :created_at, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    stage = EXCLUDED.stage,
                    score = EXCLUDED.score,
                    finding_ids = EXCLUDED.finding_ids,
                    updated_at = EXCLUDED.updated_at
                """),
                {
                    "id": opportunity.id,
                    "prospect_id": opportunity.prospect_id,
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
                    (id, prospect_id, opportunity_id, subject, body, claims, offer,
                     price, currency, findings_fingerprint, generator, generated_at)
                VALUES (:id, :prospect_id, :opportunity_id, :subject, :body, :claims,
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
                    (id, proposal_id, prospect_id, channel, recipient, subject, body,
                     status, approval_id, approved_fingerprint, provider_message_id,
                     detail, created_at, sent_at)
                VALUES (:id, :proposal_id, :prospect_id, :channel, :recipient, :subject,
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
                    (id, opportunity_id, prospect_id, kind, actor, detail, at)
                VALUES (:id, :opportunity_id, :prospect_id, :kind, :actor, :detail, :at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": event.id,
                    "opportunity_id": event.opportunity_id,
                    "prospect_id": event.prospect_id,
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
                prospect_id=row["prospect_id"],
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
        """When each prospect was last successfully contacted.

        Read from sent messages rather than a separate counter, so the cooldown
        cannot drift away from what was actually delivered.
        """
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text("""
                SELECT prospect_id, MAX(sent_at) AS last_sent
                FROM atlas_outreach_messages
                WHERE status = 'sent' AND sent_at IS NOT NULL
                GROUP BY prospect_id
                """)
                )
                .mappings()
                .all()
            )
        return ContactHistory({row["prospect_id"]: row["last_sent"] for row in rows})

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

from uuid import uuid4

from ..db import SessionLocal
from .identity import place_id, strong_keys, with_identity


class UnknownSignal(Exception):
    """No opportunity by that id. Never resolved to a similar one."""


class NotApprovable(Exception):
    """This opportunity cannot be approved, and why."""

#: The timeline entry that records a person approving one opportunity.
#:
#: On the shared business timeline rather than in a column of its own, because
#: "who said yes to what, and when" is exactly the kind of fact a state column
#: cannot hold: a column knows the answer is `approved` and not who decided it.
#: `atlas_signals.state` is the index for finding them; this is the record.
APPROVED_EVENT = "opportunity_approved"

#: The timeline entry that records a person's decision about what was built.
#:
#: Beside `APPROVED_EVENT` on the same timeline, for the same reason: a review
#: is a decision a person made about a specific thing at a specific time, and
#: the only honest home for that is an append-only record naming all three. A
#: mutable `reviewed` column would answer "was it accepted" and lose "by whom,
#: when, and what did they say".
#:
#: Append-only also means a second look is a second entry rather than an
#: overwrite. Somebody who accepts an artefact and changes their mind has done
#: two things, and the record should say so.
REVIEWED_EVENT = "artefact_reviewed"

#: What a review may conclude. A closed set, because a free-text decision is one
#: nothing downstream can act on — and the next milestone after this one reads
#: it to decide whether anything may be published.
REVIEW_DECISIONS: frozenset[str] = frozenset({"accepted", "rejected"})

#: The timeline entry that records a person authorising a publication.
#:
#: A **third** decision, and deliberately not a reuse of either earlier one.
#: `opportunity_approved` answered "should Qevik do this work?" before anything
#: existed. `artefact_reviewed` answered "is what was built any good?" about a
#: finished thing. This answers "may this exact bundle go in front of
#: strangers?", which the same person can answer differently from both — and
#: unlike either, it cannot be taken back once a visitor has read the page.
#:
#: Nothing is published because an artefact was accepted. Acceptance says the
#: work is good; this says it may leave the building.
PUBLICATION_EVENT = "publication_approved"

#: The timeline entry a verification pass writes for every site it attempted.
#: One name, used by the query that orders the backlog and by the pass that
#: marks it — a second spelling would silently stop the rotation, and the run
#: would still report success.
VERIFIED_EVENT = "website_verified"
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
    ALL_TENANTS,
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

    def approve_signal(self, signal_id: str, *, actor: str,
                       tenant: TenantId | None = None) -> dict:
        """Record that a person approved this specific opportunity.

        Refuses anything that is not an open opportunity awaiting a person. In
        particular it refuses one already approved: approving twice would let
        one decision produce two deliveries, and the second would be work
        nobody asked for wearing the first one's authorisation.

        The state change and the timeline entry are one transaction. Two writes
        that can half-happen would leave either an approval nobody can attribute
        or a decision that never took effect.
        """
        found = self.get_signal(signal_id, tenant=tenant)
        if found is None:
            raise UnknownSignal(
                f"no opportunity {signal_id!r}. Approval names a specific "
                "opportunity; there is no approving a kind of them.")
        if found["state"] != "open":
            raise NotApprovable(
                f"{signal_id} is {found['state']}, not open. An opportunity is "
                "approved once, and a second approval would authorise a second "
                "delivery on the strength of one decision.")
        if not found["needs_approval"]:
            raise NotApprovable(
                f"{signal_id} suggests nothing that needs a person — its "
                "actions stay inside Qevik. There is nothing here to approve.")

        with SessionLocal() as session:
            moved = session.execute(
                text("""
                UPDATE atlas_signals SET state = 'approved'
                WHERE id = :id AND state = 'open'
                  AND (:tenant = '' OR tenant_id = :tenant)
                """),
                {"id": signal_id, "tenant": str(tenant or "")})
            if not moved.rowcount:
                # Somebody else approved it between the read and the write.
                session.rollback()
                raise NotApprovable(
                    f"{signal_id} was approved by another request first")
            session.execute(
                text("""
                INSERT INTO atlas_business_events
                    (id, business_id, factory, kind, opportunity_id, actor,
                     detail, at)
                VALUES (:id, :business_id, :factory, :kind, :opportunity_id,
                        :actor, :detail, :at)
                """),
                {"id": f"evt-{uuid4().hex[:12]}",
                 "business_id": found["business_id"],
                 "factory": "opportunity", "kind": APPROVED_EVENT,
                 "opportunity_id": signal_id, "actor": actor,
                 "detail": json.dumps({
                     "kind": found["kind"], "score": found["score"],
                     "scope": found["scope"],
                     "action": ((found["detail"].get("actions") or [{}])[0]
                                .get("statement", "")),
                     "capability": ((found["detail"].get("actions") or [{}])[0]
                                    .get("capability", "")),
                     "evidence_fingerprints": found["evidence_fingerprints"]}),
                 "at": datetime.now(UTC)})
            session.commit()
        return self.get_signal(signal_id, tenant=tenant)

    def record_review(self, *, mission_id: str, business_id: str,
                      signal_id: str, decision: str, actor: str,
                      note: str = "", commit: str = "",
                      tenant: TenantId | None = None) -> dict:
        """Record what a person decided about a delivered artefact.

        `commit` is the object id the reviewer was looking at, stored with the
        decision. Without it the record says an artefact was accepted and not
        *which* artefact — and a mission branch can be rebuilt, so "accepted"
        with no commit would silently come to mean the newest one.

        Nothing is published, sent or promoted by this. It records a decision;
        acting on it is a separate act with its own boundary.
        """
        if decision not in REVIEW_DECISIONS:
            raise NotApprovable(
                f"{decision!r} is not a review decision. Known: "
                f"{', '.join(sorted(REVIEW_DECISIONS))}.")
        if not actor.strip():
            raise NotApprovable(
                "a review must name who made it; a decision nobody signed is "
                "one nobody can be asked about")
        entry = {"id": f"evt-{uuid4().hex[:12]}", "business_id": business_id,
                 "factory": "opportunity", "kind": REVIEWED_EVENT,
                 "opportunity_id": signal_id, "actor": actor.strip(),
                 "detail": json.dumps({"decision": decision,
                                       "mission_id": mission_id,
                                       "commit": commit,
                                       "note": note.strip()[:2000]}),
                 "at": datetime.now(UTC)}
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_business_events
                    (id, business_id, factory, kind, opportunity_id, actor,
                     detail, at)
                VALUES (:id, :business_id, :factory, :kind, :opportunity_id,
                        :actor, :detail, :at)
                """), entry)
            session.commit()
        return {"id": entry["id"], "decision": decision, "actor": entry["actor"],
                "mission_id": mission_id, "signal_id": signal_id,
                "commit": commit, "note": note.strip()[:2000],
                "at": entry["at"].isoformat()}

    def awaiting_publication(self, *, limit: int = 50,
                             tenant: TenantId | None = None) -> list[dict]:
        """Artefacts a person accepted, that nothing has acted on yet.

        Derived, not stored. There is no `awaiting_publication` table and there
        must not be one: acceptance is a decision somebody made, the timeline
        already holds it, and a second copy is a second thing that can disagree
        with the first. This reads the decisions and folds them.

        **Latest decision per mission wins.** The timeline is append-only, so a
        mission can carry several — three identical ones from three runs of a
        gate, or an acceptance somebody later withdrew. `DISTINCT ON` takes the
        most recent and the filter is applied *after* it, so a mission accepted
        and then rejected is absent rather than present twice.

        **The commit comes from the decision, never from the branch.** A mission
        branch can be rebuilt; reading `mission/<id>` here would present whatever
        is on it now under an acceptance given for something else. The queue
        shows what was actually reviewed or it shows nothing.

        **Tenancy runs through the opportunity.** `atlas_business_events` has no
        tenant column — it is one shared timeline per business, by design — so
        the scope comes from the signal the review names, which does have one. A
        review whose opportunity belongs to another tenant is not this tenant's
        work to see.

        Nothing here is "not yet acted on" in any enforced sense **yet**: no
        outward act exists to record. When publishing lands it records its own
        event, and the filter for it belongs in the `WHERE` below — one clause,
        beside the one that is already here.
        """
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT * FROM (
                    SELECT DISTINCT ON (event.detail->>'mission_id')
                        event.detail->>'mission_id' AS mission_id,
                        event.detail->>'commit'     AS commit,
                        event.detail->>'decision'   AS decision,
                        event.detail->>'note'       AS note,
                        event.actor                 AS actor,
                        event.at                    AS decided_at,
                        event.opportunity_id        AS signal_id,
                        event.business_id           AS business_id,
                        signal.scope                AS scope,
                        signal.kind                 AS signal_kind
                    FROM atlas_business_events AS event
                    JOIN atlas_signals AS signal
                      ON signal.id = event.opportunity_id
                    WHERE event.kind = :kind
                      AND (:tenant = '' OR signal.tenant_id = :tenant)
                    ORDER BY event.detail->>'mission_id', event.at DESC
                ) AS latest
                WHERE latest.decision = 'accepted'
                ORDER BY latest.decided_at DESC
                LIMIT :limit
                """),
                {"kind": REVIEWED_EVENT, "tenant": str(tenant or ""),
                 "limit": max(1, min(int(limit), 200))},
            ).mappings().all()

        found = []
        for row in rows:
            business = self.get_business(row["business_id"],
                                         tenant=ALL_TENANTS)
            found.append({
                "mission_id": row["mission_id"],
                # What was reviewed. Not a path, not a branch, not a status.
                "commit": row["commit"] or "",
                "signal_id": row["signal_id"],
                "business_id": row["business_id"],
                "business_name": business.name if business else "",
                "scope": row["scope"] or "",
                "accepted_by": row["actor"],
                "accepted_at": (row["decided_at"].isoformat()
                                if row["decided_at"] else ""),
                "note": row["note"] or "",
                # Said out loud so a surface cannot render this as done. The
                # artefact has been accepted and nothing has taken it anywhere.
                "state": "AWAITING_PUBLICATION",
            })
        return found

    def approve_publication(self, *, mission_id: str, business_id: str,
                            signal_id: str, commit: str, site_id: str,
                            actor: str, note: str = "",
                            tenant: TenantId | None = None) -> dict:
        """Record that a person authorised publishing one exact bundle.

        Every field is part of the authorisation, not context around it. The
        commit says *which bytes*; the site says *which address*; the mission
        and opportunity say *whose work and why*. A publication that matched
        four of them and not the fifth is a different act, and the executing
        side re-checks all five rather than trusting that this wrote them.

        Refuses an artefact nobody accepted. Acceptance is a precondition of
        this decision and not a substitute for it: somebody must have looked at
        the thing, and then somebody must say it may go out.
        """
        if not commit.strip():
            raise NotApprovable(
                "a publication must name the commit it publishes. Without one "
                "this authorises whatever the branch holds when it runs.")
        if not actor.strip():
            raise NotApprovable("a publication must name who authorised it")

        accepted = [r for r in self.reviews_for(mission_id, tenant=tenant)]
        if not accepted or accepted[-1]["decision"] != "accepted":
            raise NotApprovable(
                f"{mission_id} has no accepted review"
                + (f" — the last decision was {accepted[-1]['decision']!r}"
                   if accepted else "")
                + ". Nothing is published because it exists; a person looks at "
                  "it first.")
        if accepted[-1]["commit"] != commit.strip():
            raise NotApprovable(
                f"the accepted artefact is {accepted[-1]['commit'][:12]} and "
                f"this would publish {commit.strip()[:12]}. A publication goes "
                "out as the bytes somebody reviewed or it does not go out.")

        entry = {"id": f"evt-{uuid4().hex[:12]}", "business_id": business_id,
                 "factory": "opportunity", "kind": PUBLICATION_EVENT,
                 "opportunity_id": signal_id, "actor": actor.strip(),
                 "detail": json.dumps({"mission_id": mission_id,
                                       "commit": commit.strip(),
                                       "site_id": site_id,
                                       "note": note.strip()[:2000]}),
                 "at": datetime.now(UTC)}
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_business_events
                    (id, business_id, factory, kind, opportunity_id, actor,
                     detail, at)
                VALUES (:id, :business_id, :factory, :kind, :opportunity_id,
                        :actor, :detail, :at)
                """), entry)
            session.commit()
        return {"id": entry["id"], "mission_id": mission_id,
                "signal_id": signal_id, "commit": commit.strip(),
                "site_id": site_id, "actor": entry["actor"],
                "note": note.strip()[:2000],
                "at": entry["at"].isoformat()}

    def publication_approvals_for(self, mission_id: str, *,
                                  tenant: TenantId | None = None) -> list[dict]:
        """Every publication a person authorised for this mission, oldest first."""
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, actor, opportunity_id, business_id, detail, at
                FROM atlas_business_events
                WHERE kind = :kind AND detail->>'mission_id' = :mission
                ORDER BY at
                """),
                {"kind": PUBLICATION_EVENT, "mission": mission_id},
            ).mappings().all()
        found = []
        for row in rows:
            detail = _decoded(row["detail"]) or {}
            found.append({"id": row["id"], "actor": row["actor"],
                          "signal_id": row["opportunity_id"],
                          "business_id": row["business_id"],
                          "mission_id": detail.get("mission_id", ""),
                          "commit": detail.get("commit", ""),
                          "site_id": detail.get("site_id", ""),
                          "note": detail.get("note", ""),
                          "at": row["at"].isoformat() if row["at"] else ""})
        return found

    def reviews_for(self, mission_id: str, *,
                    tenant: TenantId | None = None) -> list[dict]:
        """Every decision recorded about this mission's artefact, oldest first.

        A list, not a latest: the point of an append-only record is that a
        reviewer who changed their mind is visible as two decisions rather than
        as one that was always what it now says.
        """
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT id, actor, opportunity_id, detail, at
                FROM atlas_business_events
                WHERE kind = :kind AND detail->>'mission_id' = :mission
                ORDER BY at
                """),
                {"kind": REVIEWED_EVENT, "mission": mission_id},
            ).mappings().all()
        found = []
        for row in rows:
            detail = _decoded(row["detail"]) or {}
            found.append({"id": row["id"], "actor": row["actor"],
                          "signal_id": row["opportunity_id"],
                          "decision": detail.get("decision", ""),
                          "note": detail.get("note", ""),
                          "commit": detail.get("commit", ""),
                          "at": row["at"].isoformat() if row["at"] else ""})
        return found

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

    def businesses_by_website(self, *, limit: int = 40,
                              tenant: TenantId | None = None
                              ) -> dict[str, Business]:
        """The websites Qevik has evidence for, and whose they are.

        Both halves of verification come from here. The fetch needs the
        addresses; the audit needs to know which business each response belongs
        to, and a finding attributed to the wrong company is worse than no
        finding at all.

        They are one query for that reason. Two — a list of URLs to fetch and a
        separate lookup to attribute them — is the shape that drifts: they
        would be taken at different moments, ordered differently, and bounded
        differently, and the run would quietly audit forty sites and attribute
        thirty-eight.

        **Least recently verified first, never-verified before all of them.**
        That ordering is the whole reason a nightly run works through a backlog
        instead of re-reading the same sites for ever.

        It was not the ordering. `DISTINCT ON (website)` requires the query to
        sort by `website`, so a `LIMIT` on it took the alphabetically first
        forty — every night, the same forty, while the docstring claimed oldest
        first. With 359 recorded sites and 40 a night, 319 of them would never
        have been fetched at all, and nothing would have reported a problem: the
        run would have succeeded nightly and re-audited the letter A.

        So the de-duplication and the ordering are now two steps, and the
        ordering is over `VERIFIED_EVENT`, which `mission/toolrunner.py` records
        for every site a verification pass **attempted** — not only for the ones
        that answered. A site that refuses robots or times out has still had its
        turn, and leaving it unmarked would let it hold up the queue for ever.
        """
        with SessionLocal() as session:
            rows = session.execute(
                text("""
                SELECT site.* FROM (
                    SELECT DISTINCT ON (website) *
                    FROM atlas_businesses
                    WHERE website IS NOT NULL AND website <> ''
                    ORDER BY website, first_seen_at
                ) AS site
                LEFT JOIN (
                    SELECT business_id, max(at) AS last_at
                    FROM atlas_business_events
                    WHERE kind = :verified
                    GROUP BY business_id
                ) AS seen ON seen.business_id = site.id
                ORDER BY seen.last_at ASC NULLS FIRST, site.first_seen_at
                LIMIT :limit
                """),
                {"limit": max(1, min(int(limit), 200)),
                 "verified": VERIFIED_EVENT},
            ).mappings().all()
        found: dict[str, Business] = {}
        for row in rows:
            website = str(row["website"] or "")
            # A scheme-less or `mailto:` value is something a source recorded,
            # not something the fetcher may be handed. Dropped here rather than
            # normalised: guessing `https://` in front of an address a directory
            # typed by hand is how a fetch reaches a host nobody recorded.
            if not website.startswith(("http://", "https://")):
                continue
            found[website] = self._business_from_row(row)
        return found

    def recorded_websites(self, *, limit: int = 40,
                          tenant: TenantId | None = None) -> list[str]:
        """The allow-list a verification recipe fetches.

        Every address here came from an evidenced sighting, which is what makes
        "the targets come from memory" a safety property rather than a
        convenience: nothing can put a URL in this list except a source Qevik
        actually read.

        Derived from `businesses_by_website` rather than queried again, so the
        set that is fetched and the set that can be attributed are the same set
        by construction.
        """
        return list(self.businesses_by_website(limit=limit, tenant=tenant))

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

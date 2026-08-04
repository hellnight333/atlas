"""Persistence for the Website Factory.

Its own repository, matching Media and Opportunity. Same conventions:
parameterised ``text()`` SQL, one ``SessionLocal`` per operation, Pydantic models
in and out.

One thing here is not merely storage. **The build files are stored, not
referenced** — the artifact lives in Atlas's database, which is the literal
mechanism behind "rebuild from Business memory" and behind moving a customer
between hosts without a migration. A row pointing at a directory on somebody's
laptop would satisfy every type in this package and none of the invariants.

``stored_fingerprint`` exists so a rebuild can be checked rather than trusted:
the fingerprint is written once at save time and compared against a fresh
computation on the way out. Storing it and recomputing it is redundant by design
— that redundancy is the check.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from ..db import SessionLocal
from ..opportunity.models import BusinessEvent
from ..opportunity.repository import OpportunityRepository
from .models import Deployment, DeploymentStatus, Site, SiteBuild


def _now() -> datetime:
    return datetime.now(UTC)


def _decoded(value: object) -> object:
    """JSONB comes back decoded; TEXT would not. Tolerating both is three lines."""
    if isinstance(value, str | bytes | bytearray):
        return json.loads(value)
    return value


class WebsiteRepository:
    """Storage for sites, builds and deployments.

    Timeline writes are delegated to the Opportunity repository rather than
    reimplemented. ``atlas_business_events`` is Atlas's memory of a company, not
    the Opportunity Factory's table — a second writer would be a second
    implementation of an append-only log, and they would drift.
    """

    def __init__(self, events: OpportunityRepository | None = None) -> None:
        self._events = events or OpportunityRepository()

    # -- sites ------------------------------------------------------------

    def save_site(self, site: Site) -> Site:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_sites
                    (id, business_id, name, domain, content, created_at, updated_at)
                VALUES (:id, :business_id, :name, :domain, :content, :created_at, :updated_at)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    domain = EXCLUDED.domain,
                    content = EXCLUDED.content,
                    updated_at = EXCLUDED.updated_at
                """),
                {
                    **site.model_dump(exclude={"content"}),
                    "content": json.dumps(site.content),
                    "updated_at": _now(),
                },
            )
            session.commit()
        return site

    def get_site(self, site_id: str) -> Site | None:
        with SessionLocal() as session:
            row = (
                session.execute(text("SELECT * FROM atlas_sites WHERE id = :id"), {"id": site_id})
                .mappings()
                .first()
            )
        if not row:
            return None
        payload = dict(row)
        payload["content"] = dict(_decoded(payload.get("content") or {}))
        return Site(**payload)

    def list_sites(self, business_id: str | None = None) -> list[Site]:
        query = "SELECT * FROM atlas_sites"
        params: dict[str, object] = {}
        if business_id:
            query += " WHERE business_id = :bid"
            params["bid"] = business_id
        query += " ORDER BY created_at"
        with SessionLocal() as session:
            rows = session.execute(text(query), params).mappings().all()
        return [
            Site(**{**dict(row), "content": dict(_decoded(row["content"] or {}))}) for row in rows
        ]

    # -- builds -----------------------------------------------------------

    def save_build(self, build: SiteBuild) -> SiteBuild:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_site_builds
                    (id, site_id, business_id, files, fingerprint, status, generator,
                     provenance, created_at)
                VALUES (:id, :site_id, :business_id, :files, :fingerprint, :status,
                        :generator, :provenance, :created_at)
                ON CONFLICT (id) DO NOTHING
                """),
                {
                    "id": build.id,
                    "site_id": build.site_id,
                    "business_id": build.business_id,
                    "files": json.dumps(build.files),
                    # Written once, recomputed on read. The redundancy is the check.
                    "fingerprint": build.fingerprint,
                    "status": build.status.value,
                    "generator": build.generator,
                    "provenance": json.dumps(build.provenance),
                    "created_at": build.created_at,
                },
            )
            session.commit()
        return build

    def get_build(self, build_id: str) -> SiteBuild | None:
        row = self._build_row(build_id)
        if not row:
            return None
        return SiteBuild(
            id=row["id"],
            site_id=row["site_id"],
            business_id=row["business_id"],
            files=dict(_decoded(row["files"])),
            status=row["status"],
            generator=row["generator"],
            provenance=dict(_decoded(row["provenance"] or {})),
            created_at=row["created_at"],
        )

    def stored_fingerprint(self, build_id: str) -> str | None:
        row = self._build_row(build_id)
        return row["fingerprint"] if row else None

    def _build_row(self, build_id: str):
        with SessionLocal() as session:
            return (
                session.execute(
                    text("SELECT * FROM atlas_site_builds WHERE id = :id"), {"id": build_id}
                )
                .mappings()
                .first()
            )

    def list_builds(self, site_id: str) -> list[SiteBuild]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT id FROM atlas_site_builds WHERE site_id = :sid ORDER BY created_at"
                    ),
                    {"sid": site_id},
                )
                .mappings()
                .all()
            )
        return [build for row in rows if (build := self.get_build(row["id"])) is not None]

    # -- deployments ------------------------------------------------------

    def save_deployment(self, deployment: Deployment) -> Deployment:
        with SessionLocal() as session:
            session.execute(
                text("""
                INSERT INTO atlas_site_deployments
                    (id, build_id, site_id, business_id, target, status, remote_id,
                     preview_url, live_url, build_fingerprint, gate_findings, detail,
                     created_at, promoted_at)
                VALUES (:id, :build_id, :site_id, :business_id, :target, :status,
                        :remote_id, :preview_url, :live_url, :build_fingerprint,
                        :gate_findings, :detail, :created_at, :promoted_at)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    remote_id = EXCLUDED.remote_id,
                    preview_url = EXCLUDED.preview_url,
                    live_url = EXCLUDED.live_url,
                    gate_findings = EXCLUDED.gate_findings,
                    detail = EXCLUDED.detail,
                    promoted_at = EXCLUDED.promoted_at
                """),
                {
                    **deployment.model_dump(exclude={"gate_findings"}),
                    "status": deployment.status.value,
                    "gate_findings": json.dumps(deployment.gate_findings),
                },
            )
            session.commit()
        return deployment

    def get_deployment(self, deployment_id: str) -> Deployment | None:
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("SELECT * FROM atlas_site_deployments WHERE id = :id"),
                    {"id": deployment_id},
                )
                .mappings()
                .first()
            )
        return self._deployment(row) if row else None

    def live_deployment(self, site_id: str, target: str | None = None) -> Deployment | None:
        """What Atlas believes is serving.

        Atlas's record rather than the host's: an answer read back from a
        provider's API depends on an account that can be closed and an API that
        can change.
        """
        query = "SELECT * FROM atlas_site_deployments WHERE site_id = :sid AND status = :status"
        params: dict[str, object] = {"sid": site_id, "status": DeploymentStatus.LIVE.value}
        if target:
            query += " AND target = :target"
            params["target"] = target
        query += " ORDER BY promoted_at DESC NULLS LAST, created_at DESC LIMIT 1"
        with SessionLocal() as session:
            row = session.execute(text(query), params).mappings().first()
        return self._deployment(row) if row else None

    def previous_deployment(self, site_id: str, target: str) -> Deployment | None:
        """The version rollback should return to.

        The most recently superseded deployment on this target — the one that
        was live before whatever is live now. Failed and gate-blocked
        deployments are excluded: they never served anyone, so going "back" to
        one would be going somewhere new.
        """
        with SessionLocal() as session:
            row = (
                session.execute(
                    text("""
                    SELECT * FROM atlas_site_deployments
                    WHERE site_id = :sid AND target = :target AND status = :status
                    ORDER BY promoted_at DESC NULLS LAST, created_at DESC
                    LIMIT 1
                    """),
                    {
                        "sid": site_id,
                        "target": target,
                        "status": DeploymentStatus.SUPERSEDED.value,
                    },
                )
                .mappings()
                .first()
            )
        return self._deployment(row) if row else None

    def supersede_live(self, site_id: str, target: str, *, except_id: str) -> None:
        with SessionLocal() as session:
            session.execute(
                text("""
                UPDATE atlas_site_deployments
                SET status = :superseded
                WHERE site_id = :sid AND target = :target AND status = :live
                  AND id <> :except_id
                """),
                {
                    "sid": site_id,
                    "target": target,
                    "live": DeploymentStatus.LIVE.value,
                    "superseded": DeploymentStatus.SUPERSEDED.value,
                    "except_id": except_id,
                },
            )
            session.commit()

    def list_deployments(self, site_id: str) -> list[Deployment]:
        with SessionLocal() as session:
            rows = (
                session.execute(
                    text(
                        "SELECT * FROM atlas_site_deployments WHERE site_id = :sid "
                        "ORDER BY created_at"
                    ),
                    {"sid": site_id},
                )
                .mappings()
                .all()
            )
        return [self._deployment(row) for row in rows]

    @staticmethod
    def _deployment(row) -> Deployment:
        payload = dict(row)
        payload["gate_findings"] = list(_decoded(payload.get("gate_findings") or []))
        return Deployment(**payload)

    # -- the shared timeline ----------------------------------------------

    def record_event(self, event: BusinessEvent) -> BusinessEvent:
        return self._events.record_event(event)

    def timeline(self, business_id: str, *, factory: str | None = None) -> list[BusinessEvent]:
        return self._events.timeline(business_id, factory=factory)

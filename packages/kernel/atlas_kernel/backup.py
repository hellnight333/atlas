from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .config import AtlasConfig
    from .repository import AtlasRepository

#: Bumped when the archive layout changes. Restore refuses a newer version.
BACKUP_FORMAT_VERSION = 1


class BackupScope(StrEnum):
    PROJECT = "project"
    WORKSPACE = "workspace"
    ORGANIZATION = "organization"
    SETTINGS = "settings"


class BackupError(RuntimeError):
    pass


class BackupManifest(BaseModel):
    format_version: int = BACKUP_FORMAT_VERSION
    scope: BackupScope
    scope_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    atlas_profile: str = "development"
    #: section -> row count, so a restore can be sanity-checked before applying.
    counts: dict[str, int] = Field(default_factory=dict)
    checksum: str = ""


class BackupArchive(BaseModel):
    manifest: BackupManifest
    data: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    manifest: BackupManifest | None = None


class RestoreResult(BaseModel):
    restored: dict[str, int] = Field(default_factory=dict)
    skipped: dict[str, int] = Field(default_factory=dict)
    dry_run: bool = False


class BackupService:
    """Exports and restores kernel state as verifiable JSON archives.

    Asset *metadata* is backed up, never asset bytes: those live in the asset
    store and are content-addressed. A backup is therefore small and portable,
    and restoring one never fabricates media that is not there.
    """

    def __init__(self, repository: AtlasRepository, config: AtlasConfig) -> None:
        self.repository = repository
        self.config = config

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_project(self, project_id: str) -> BackupArchive:
        project = self.repository.get_project(project_id)
        if project is None:
            raise BackupError(f"Project not found: {project_id}")

        data = {
            "projects": [project.model_dump(mode="json")],
            "assets": [
                a.model_dump(mode="json")
                for a in self.repository.list_assets(project_id=project_id)
            ],
            "workflows": [
                w.model_dump(mode="json") for w in self.repository.list_workflows(project_id)
            ],
            "chat_conversations": [
                c.model_dump(mode="json")
                for c in self.repository.list_chat_conversations(project_id)
            ],
            "research_sessions": [
                r.model_dump(mode="json")
                for r in self.repository.list_research_sessions(project_id)
            ],
            "review_sessions": [
                r.model_dump(mode="json") for r in self.repository.list_review_sessions(project_id)
            ],
            "agents": [a.model_dump(mode="json") for a in self.repository.list_agents(project_id)],
            "automation_rules": [
                r.model_dump(mode="json")
                for r in self.repository.list_automation_rules(project_id=project_id)
            ],
            "graph_nodes": [
                n.model_dump(mode="json")
                for n in self.repository.list_graph_nodes(project_id=project_id)
            ],
        }
        return self._archive(BackupScope.PROJECT, project_id, data)

    def export_workspace(self, workspace_id: str) -> BackupArchive:
        projects = self.repository.list_projects(workspace_id=workspace_id)
        data: dict[str, list[dict[str, Any]]] = {
            "projects": [p.model_dump(mode="json") for p in projects],
            "assets": [],
            "workflows": [],
            "agents": [],
        }
        for project in projects:
            data["assets"].extend(
                a.model_dump(mode="json")
                for a in self.repository.list_assets(project_id=project.id)
            )
            data["workflows"].extend(
                w.model_dump(mode="json") for w in self.repository.list_workflows(project.id)
            )
            data["agents"].extend(
                a.model_dump(mode="json") for a in self.repository.list_agents(project.id)
            )
        return self._archive(BackupScope.WORKSPACE, workspace_id, data)

    def export_organization(self, organization_id: str) -> BackupArchive:
        organization = self.repository.get_organization(organization_id)
        if organization is None:
            raise BackupError(f"Organization not found: {organization_id}")

        data = {
            "organizations": [organization.model_dump(mode="json")],
            "teams": [
                t.model_dump(mode="json")
                for t in self.repository.list_teams(organization_id=organization_id)
            ],
            "roles": [
                r.model_dump(mode="json")
                for r in self.repository.list_roles()
                if r.organization_id == organization_id
            ],
            "memberships": [
                m.model_dump(mode="json")
                for m in self.repository.list_memberships(organization_id=organization_id)
            ],
            "policy_sets": [
                p.model_dump(mode="json")
                for p in self.repository.list_policy_sets(organization_id=organization_id)
            ],
            # Audit is append-only and exported for the record, never restored.
            "audit_records": [
                a.model_dump(mode="json")
                for a in self.repository.list_audit_records(
                    organization_id=organization_id, limit=10_000
                )
            ],
        }
        return self._archive(BackupScope.ORGANIZATION, organization_id, data)

    def export_settings(self) -> BackupArchive:
        data = {
            "approval_policies": [
                p.model_dump(mode="json") for p in self.repository.list_approval_policies()
            ],
            "workers": [w.model_dump(mode="json") for w in self.repository.list_workers()],
            "roles": [r.model_dump(mode="json") for r in self.repository.list_roles()],
            "identities": [i.model_dump(mode="json") for i in self.repository.list_identities()],
        }
        return self._archive(BackupScope.SETTINGS, None, data)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self, archive: BackupArchive) -> str:
        return json.dumps(archive.model_dump(mode="json"), indent=2, sort_keys=True)

    def from_json(self, raw: str) -> BackupArchive:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BackupError(f"Archive is not valid JSON: {exc}") from exc
        try:
            return BackupArchive.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - surfaced as a BackupError
            raise BackupError(f"Archive does not match the backup schema: {exc}") from exc

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self, archive: BackupArchive) -> ValidationResult:
        """Checked before any restore is offered, so a corrupt or foreign
        archive is rejected with a reason rather than half-applied."""
        errors: list[str] = []
        warnings: list[str] = []

        if archive.manifest.format_version > BACKUP_FORMAT_VERSION:
            errors.append(
                f"Archive format {archive.manifest.format_version} is newer than this build "
                f"supports ({BACKUP_FORMAT_VERSION})"
            )

        expected = self._checksum(archive.data)
        if archive.manifest.checksum and archive.manifest.checksum != expected:
            errors.append("Checksum mismatch: the archive has been modified or truncated")

        for section, count in archive.manifest.counts.items():
            actual = len(archive.data.get(section, []))
            if actual != count:
                errors.append(
                    f"Section '{section}' declares {count} record(s) but contains {actual}"
                )

        for section in archive.data:
            if section not in archive.manifest.counts:
                warnings.append(f"Section '{section}' is not declared in the manifest")

        if not archive.data:
            warnings.append("Archive contains no data")

        return ValidationResult(
            valid=not errors, errors=errors, warnings=warnings, manifest=archive.manifest
        )

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def restore(self, archive: BackupArchive, dry_run: bool = False) -> RestoreResult:
        """Restore is additive and idempotent: existing rows are left alone.

        Audit records are never restored — rewriting history through a backup
        would defeat the append-only guarantee.
        """
        validation = self.validate(archive)
        if not validation.valid:
            raise BackupError("; ".join(validation.errors))

        restored: dict[str, int] = {}
        skipped: dict[str, int] = {}

        handlers = self._restore_handlers()
        for section, rows in archive.data.items():
            if section == "audit_records":
                skipped[section] = len(rows)
                continue
            handler = handlers.get(section)
            if handler is None:
                skipped[section] = len(rows)
                continue
            applied = 0
            for row in rows:
                if dry_run or handler(row):
                    applied += 1
            restored[section] = applied

        return RestoreResult(restored=restored, skipped=skipped, dry_run=dry_run)

    def _restore_handlers(self) -> dict[str, Any]:
        from .cluster.models import WorkerNode
        from .models import (
            Asset,
            AutomationRule,
            ChatConversation,
            KnowledgeNode,
            Project,
            ResearchSession,
            ReviewSession,
            Workflow,
        )
        from .organization.models import Identity, Membership, Organization, PolicySet, Role, Team

        def restore_model(model: Any, getter: Any, saver: Any) -> Any:
            def handler(row: dict[str, Any]) -> bool:
                parsed = model.model_validate(row)
                identifier = getattr(parsed, "id", None)
                if identifier is not None and getter(identifier) is not None:
                    return False
                saver(parsed)
                return True

            return handler

        repo = self.repository
        return {
            "projects": restore_model(Project, repo.get_project, repo.create_project),
            "assets": restore_model(Asset, repo.get_asset, repo.create_asset),
            "workflows": restore_model(Workflow, repo.get_workflow, repo.create_workflow),
            "chat_conversations": restore_model(
                ChatConversation, repo.get_chat_conversation, repo.create_chat_conversation
            ),
            "research_sessions": restore_model(
                ResearchSession, repo.get_research_session, repo.create_research_session
            ),
            "review_sessions": restore_model(
                ReviewSession, repo.get_review_session, repo.create_review_session
            ),
            "automation_rules": restore_model(
                AutomationRule, repo.get_automation_rule, repo.create_automation_rule
            ),
            "graph_nodes": restore_model(
                KnowledgeNode, repo.get_graph_node, repo.create_graph_node
            ),
            "organizations": restore_model(
                Organization, repo.get_organization, repo.upsert_organization
            ),
            "teams": restore_model(Team, repo.get_team, repo.upsert_team),
            "roles": restore_model(Role, repo.get_role, repo.upsert_role),
            "memberships": restore_model(Membership, repo.get_membership, repo.upsert_membership),
            "policy_sets": restore_model(PolicySet, repo.get_policy_set, repo.upsert_policy_set),
            "identities": restore_model(Identity, repo.get_identity, repo.upsert_identity),
            "workers": restore_model(WorkerNode, repo.get_worker, repo.upsert_worker),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _archive(
        self, scope: BackupScope, scope_id: str | None, data: dict[str, list[dict[str, Any]]]
    ) -> BackupArchive:
        manifest = BackupManifest(
            scope=scope,
            scope_id=scope_id,
            atlas_profile=self.config.profile.value,
            counts={section: len(rows) for section, rows in data.items()},
            checksum=self._checksum(data),
        )
        return BackupArchive(manifest=manifest, data=data)

    def _checksum(self, data: dict[str, list[dict[str, Any]]]) -> str:
        canonical = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

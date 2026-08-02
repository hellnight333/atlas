from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .event_bus import AssetCreated, AssetDeleted, AssetUpdated, AssetVersionCreated, EventBus
from .models import Asset, AssetCreate, Job
from .repository import AtlasRepository
from .storage import StorageBackend


class AssetService:
    def __init__(
        self,
        repository: AtlasRepository,
        bus: EventBus,
        storage_backend: StorageBackend,
    ) -> None:
        self.repository = repository
        self.bus = bus
        self.storage_backend = storage_backend

    def create_asset(self, asset: Asset, payload: bytes | None = None) -> Asset:
        stored = self.storage_backend.store(asset.uri, payload)
        asset.uri = stored.uri
        if asset.file_size is None:
            asset.file_size = stored.file_size
        if asset.mime_type is None:
            asset.mime_type = stored.mime_type
        if asset.content_hash is None:
            asset.content_hash = stored.content_hash
        asset.updated_at = datetime.now(UTC)
        asset = self.repository.create_asset(asset)
        if asset.job_id is not None:
            self.repository.add_asset_to_job(asset.job_id, asset.id)
        if asset.run_id is not None:
            self.repository.add_asset_to_run(asset.run_id, asset.id)
        self.bus.publish(
            AssetCreated(
                asset_id=asset.id,
                run_id=asset.run_id or "",
                job_id=asset.job_id or "",
                type=asset.type,
            )
        )
        return asset

    def create_asset_from_request(
        self, request: AssetCreate, payload: bytes | None = None
    ) -> Asset:
        asset = Asset(
            type=request.type,
            project_id=request.project_id,
            workflow_id=request.workflow_id,
            run_id=request.run_id,
            job_id=request.job_id,
            parent_asset_id=request.parent_asset_id,
            version=request.version,
            uri=request.uri,
            mime_type=request.mime_type,
            file_size=request.file_size,
            content_hash=request.content_hash,
            metadata=request.metadata,
            tags=request.tags,
            source_asset_ids=request.source_asset_ids,
            thumbnail_uri=request.thumbnail_uri,
            preview_uri=request.preview_uri,
            search_index=request.search_index,
            vector_index=request.vector_index,
            embeddings=request.embeddings,
            ocr_text=request.ocr_text,
            transcript=request.transcript,
            ai_summary=request.ai_summary,
        )
        return self.create_asset(asset, payload=payload)

    def update_asset(self, asset_id: str, updates: dict[str, Any]) -> Asset | None:
        existing = self.repository.get_asset(asset_id)
        if existing is None:
            return None
        updated = existing.model_copy(update=updates)
        updated.updated_at = datetime.now(UTC)
        saved = self.repository.update_asset(updated)
        self.bus.publish(AssetUpdated(asset_id=saved.id))
        return saved

    def delete_asset(self, asset_id: str) -> None:
        self.repository.delete_asset(asset_id)
        self.bus.publish(AssetDeleted(asset_id=asset_id))

    def create_asset_version(
        self, asset_id: str, updates: dict[str, Any] | None = None
    ) -> Asset | None:
        parent = self.repository.get_asset(asset_id)
        if parent is None:
            return None
        next_version = parent.version + 1
        version_payload = parent.model_dump()
        version_payload.update(updates or {})
        version_payload["id"] = str(uuid.uuid4())
        version_payload["parent_asset_id"] = parent.id
        version_payload["version"] = next_version
        version_payload["created_at"] = datetime.now(UTC)
        version_payload["updated_at"] = datetime.now(UTC)
        child = Asset(**version_payload)
        created = self.create_asset(child)
        self.bus.publish(
            AssetVersionCreated(
                asset_id=created.id, parent_asset_id=parent.id, version=created.version
            )
        )
        return created

    def create_asset_for_job(self, job: Job, output: dict[str, Any]) -> Asset | None:
        uri = output.get("uri") or f"atlas://runs/{job.run_id}/jobs/{job.id}/outputs/{job.action}"
        run = self.repository.get_run(job.run_id)
        project_id = run.project_id if run is not None and run.project_id else "project-unassigned"
        workflow_id = run.workflow_id if run is not None else None

        asset_type = self._deduce_asset_type(job.action)
        parent_asset_id = job.payload.get("parent_asset_id")
        requested_version = job.payload.get("version")

        metadata: dict[str, Any] = dict(output)
        if job.action == "image.generate":
            # Capture reproducibility fields directly on the generated image asset.
            for key in (
                "prompt",
                "negative_prompt",
                "seed",
                "steps",
                "cfg",
                "resolution",
                "sampler",
                "provider",
                "workflow",
                "model",
                "prompt_version",
                "prompt_history",
                "styles",
                "template",
                "variables",
                "execution_time_ms",
            ):
                if key in job.payload:
                    metadata[key] = job.payload.get(key)

        asset = Asset(
            id=str(uuid.uuid4()),
            project_id=project_id,
            workflow_id=workflow_id,
            run_id=job.run_id,
            job_id=job.id,
            parent_asset_id=str(parent_asset_id) if parent_asset_id else None,
            version=int(requested_version) if requested_version is not None else 1,
            type=asset_type,
            uri=uri,
            content_hash=(output.get("hash") if isinstance(output.get("hash"), str) else None),
            metadata=metadata,
            source_asset_ids=(
                list(job.payload.get("input_asset_ids", []))
                if isinstance(job.payload.get("input_asset_ids"), list)
                else []
            ),
            thumbnail_uri=(uri if asset_type == "image" else None),
        )
        return self.create_asset(asset)

    def _deduce_asset_type(self, action: str) -> str:
        if action.startswith("image."):
            return "image"
        if action.startswith("text."):
            return "text"
        if action.startswith("code."):
            return "code"
        return "asset"

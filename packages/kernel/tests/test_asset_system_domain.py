from __future__ import annotations

import uuid

from atlas_kernel.asset_system import AssetService
from atlas_kernel.event_bus import (
    AssetCreated,
    AssetDeleted,
    AssetUpdated,
    AssetVersionCreated,
    EventBus,
)
from atlas_kernel.models import Asset, AssetCreate
from atlas_kernel.repository import AtlasRepository
from atlas_kernel.storage import PassthroughStorageBackend


def test_asset_creation_metadata_and_backward_compatibility():
    repository = AtlasRepository()
    service = AssetService(repository, EventBus(), PassthroughStorageBackend())

    legacy_asset = Asset(
        id=f"legacy-{uuid.uuid4()}",
        run_id=f"run-{uuid.uuid4()}",
        job_id=f"job-{uuid.uuid4()}",
        type="image",
        uri="atlas://legacy/asset.png",
        metadata={"width": 1024, "height": 768, "seed": 42},
    )
    created_legacy = service.create_asset(legacy_asset)
    assert created_legacy.project_id == "project-unassigned"

    created = service.create_asset_from_request(
        AssetCreate(
            type="video",
            project_id=f"project-{uuid.uuid4()}",
            uri="atlas://projects/video/clip.mp4",
            mime_type="video/mp4",
            metadata={"fps": 24, "duration": 3.2, "codec": "h264"},
            tags=["draft", "benchmark"],
            source_asset_ids=[created_legacy.id],
        )
    )

    persisted = repository.get_asset(created.id)
    assert persisted is not None
    assert persisted.mime_type == "video/mp4"
    assert persisted.metadata.get("fps") == 24
    assert persisted.tags == ["draft", "benchmark"]
    assert created_legacy.id in persisted.source_asset_ids


def test_asset_versioning_and_parent_child_lineage():
    repository = AtlasRepository()
    service = AssetService(repository, EventBus(), PassthroughStorageBackend())

    base = service.create_asset_from_request(
        AssetCreate(
            type="prompt",
            project_id=f"project-{uuid.uuid4()}",
            uri="atlas://prompts/base",
            metadata={"text": "original prompt"},
            tags=["draft"],
        )
    )

    version_2 = service.create_asset_version(
        base.id, {"metadata": {"text": "revised prompt"}, "tags": ["approved"]}
    )
    assert version_2 is not None
    assert version_2.version == 2
    assert version_2.parent_asset_id == base.id

    children = repository.list_child_assets(base.id)
    assert any(item.id == version_2.id for item in children)


def test_asset_events_create_update_delete_and_version():
    repository = AtlasRepository()
    bus = EventBus()
    service = AssetService(repository, bus, PassthroughStorageBackend())

    created_events: list[AssetCreated] = []
    updated_events: list[AssetUpdated] = []
    deleted_events: list[AssetDeleted] = []
    version_events: list[AssetVersionCreated] = []

    bus.subscribe(AssetCreated, lambda event: created_events.append(event))
    bus.subscribe(AssetUpdated, lambda event: updated_events.append(event))
    bus.subscribe(AssetDeleted, lambda event: deleted_events.append(event))
    bus.subscribe(AssetVersionCreated, lambda event: version_events.append(event))

    asset = service.create_asset_from_request(
        AssetCreate(
            type="document",
            project_id=f"project-{uuid.uuid4()}",
            uri="atlas://docs/note.md",
            metadata={"title": "note"},
        )
    )

    updated = service.update_asset(
        asset.id, {"metadata": {"title": "updated note"}, "tags": ["approved"]}
    )
    assert updated is not None
    assert updated.metadata.get("title") == "updated note"

    new_version = service.create_asset_version(asset.id, {"metadata": {"title": "v2"}})
    assert new_version is not None

    service.delete_asset(asset.id)

    assert any(event.asset_id == asset.id for event in created_events)
    assert any(event.asset_id == asset.id for event in updated_events)
    assert any(event.parent_asset_id == asset.id for event in version_events)
    assert any(event.asset_id == asset.id for event in deleted_events)

# Atlas Asset System

## Objective

Assets are first-class domain objects in Atlas. They represent every artifact created, imported, or managed by the platform.

Assets are not plain files. They are versioned entities with lineage, metadata, and workflow context.

## Asset Identity

Each asset includes:

- UUID (`id`)
- Asset type (`type`)
- Project ID (`project_id`)
- Workflow ID (`workflow_id`, optional)
- Run ID (`run_id`, optional)
- Parent Asset ID (`parent_asset_id`, optional)
- Version (`version`)
- Created At (`created_at`)
- Updated At (`updated_at`)

## Storage Model

Asset storage is abstract.

- URI (`uri`)
- MIME type (`mime_type`)
- File size (`file_size`)
- Content hash (`content_hash`)

The asset system does not depend on local filesystem access.

Current abstraction:

- `StorageBackend` interface
- `PassthroughStorageBackend` default implementation

## Metadata and Extensibility

Assets support flexible metadata and tags:

- `metadata: dict[str, Any]`
- `tags: list[str]`

Examples include image dimensions, video FPS/duration, audio sample rate, code language/repository/commit.

## Relationships and Lineage

Assets support lineage through:

- `parent_asset_id`
- `source_asset_ids`
- child assets query support
- derived assets query support

This enables chains like prompt -> image -> upscaled image -> video -> edited video.

## Future-Ready Fields

Reserved fields currently supported:

- `embeddings`
- `thumbnail_uri`
- `preview_uri`
- `search_index`
- `vector_index`
- `ocr_text`
- `transcript`
- `ai_summary`

## Events

Asset system emits typed events via internal event bus:

- `AssetCreated`
- `AssetUpdated`
- `AssetDeleted`
- `AssetVersionCreated`

Subscribers are optional; core business logic does not depend on specific subscribers.

## Integration

- Worker execution outputs are materialized as assets.
- Runs track produced assets (`Run.produced_asset_ids`).
- Jobs track produced assets (`Job.produced_asset_ids`).
- Existing APIs remain backward compatible while adding new asset fields/endpoints.

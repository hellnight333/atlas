# ADR-0005 Asset System

## Status

Accepted

## Context

Atlas requires a first-class asset domain to support long-term workflow lineage, reproducibility, and project-level organization. Treating outputs as plain files prevents scalable lifecycle management.

## Decision

Adopt an Asset System with:

- Strong asset identity (UUID, type, project/workflow/run linkage, versioning)
- Abstract storage contract (`StorageBackend`)
- Flexible metadata and tags
- Explicit lineage (`parent_asset_id`, `source_asset_ids`)
- Event emissions (`AssetCreated`, `AssetUpdated`, `AssetDeleted`, `AssetVersionCreated`)
- Run/job produced-asset references

## Consequences

- Assets become queryable domain objects rather than incidental side effects.
- Future storage backends can be introduced without changing business logic.
- Workflow traceability and version chains are preserved.
- Existing API contracts remain additive and backward compatible.

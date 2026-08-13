# Atlas → Qevik

## Current policy
Brand/product is Qevik; internal code still contains Atlas-era names.

## Do not broad-refactor yet
A full rename would touch:
- `atlas_kernel`
- roughly 50 table names
- desktop app
- documentation
- migrations/integrations

Current policy:
- new environment variables use `QEVIK_`
- new user-facing branding uses Qevik
- preserve working Atlas internals
- defer package/schema/database migration

A future rename must be treated as a migration project with inventory, migration strategy, tests and rollback.

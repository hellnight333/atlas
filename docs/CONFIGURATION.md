# Atlas Configuration

Configuration is declarative. Resolution order is:

```
field default  →  profile default  →  environment variable
```

Environment always wins, so an operator can override any profile decision
without editing a profile. All parsing happens in one place (`config.py`); no
other module reads the environment.

## Profiles

| Profile | Intent | Notable defaults |
|---|---|---|
| `development` | local work | debug logging, human-readable output |
| `staging` | pre-production | JSON logging, integrity checks on startup |
| `production` | live | JSON logging, integrity checks, 120s runtime timeout |
| `portable` | run from a folder | state in `./atlas-data` |
| `offline` | no network | cloud providers refused |

```bash
ATLAS_PROFILE=production python -m uvicorn atlas_kernel.api:app
```

Adding a profile means adding an entry to `PROFILE_DEFAULTS` — a data change,
never a logic change.

## Environment variables

| Variable | Type | Default |
|---|---|---|
| `ATLAS_PROFILE` | profile name | `development` |
| `ATLAS_DATABASE_URL` | string | `postgresql+psycopg://atlas:atlas@localhost:5432/atlas` |
| `ATLAS_LOG_LEVEL` | `debug`/`info`/`warning`/`error` | per profile |
| `ATLAS_LOG_JSON` | boolean | per profile |
| `ATLAS_OFFLINE` | boolean | `false` |
| `ATLAS_ALLOW_CLOUD_PROVIDERS` | boolean | `true` |
| `ATLAS_HEARTBEAT_TIMEOUT_SECONDS` | int | `90` |
| `ATLAS_LEASE_SECONDS` | int | `120` |
| `ATLAS_RUNTIME_TIMEOUT_SECONDS` | float | `30.0` |
| `ATLAS_DATA_DIR` | path | `./.atlas` |
| `ATLAS_BACKUP_DIR` | path | `./.atlas/backups` |
| `ATLAS_SCHEMA_VALIDATION` | boolean | `true` |
| `ATLAS_INTEGRITY_CHECK` | boolean | per profile |

Booleans accept `1/true/yes/on` and `0/false/no/off`, case-insensitively. An
unparseable value raises `ConfigError` naming the variable — a typo fails loudly
at startup rather than silently selecting a default.

An empty string is treated as unset, so `ATLAS_LEASE_SECONDS=` falls back to the
default rather than erroring.

## Inspecting the resolved configuration

```bash
curl localhost:8000/configuration
```

Returns the resolved values plus every profile's defaults. **The database URL is
never included** — it can carry credentials. The report says
`database_configured: true` instead.

## Logging

One logger per subsystem: `runtime`, `scheduler`, `worker`, `cluster`,
`automation`, `approval`, `organization`, `graph`, `repository`, `api`.

```python
from atlas_kernel.logging_setup import get_logger
get_logger("cluster").warning("worker offline", extra={"worker_id": "w1"})
```

With `log_json=true` each record is one JSON object with `extra=` fields
inlined — ready for a log shipper. Otherwise a readable single line with
`key=value` extras. Reconfiguring replaces handlers rather than stacking them,
so calling `configure_logging` twice does not double every line.

Raise the level on one subsystem without drowning in the rest:

```python
import logging
logging.getLogger("atlas.cluster").setLevel(logging.DEBUG)
```

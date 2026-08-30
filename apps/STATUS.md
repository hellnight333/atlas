# Which of these are running, and which are parked

Source-file count is not product progress. `apps/desktop` is the largest tree
here and nothing runs it.

| App | Status | Evidence |
|---|---|---|
| `control` | **live** | The Qevik operator console at app.qevik.ai. Shipped by `infra/deploy_control.sh` and `infra/deploy_console.sh` to `/srv/qevik-control`, served by Caddy over TLS. |
| `public` | **live** | The public site and published samples. |
| `samples` | **live** | Portfolio samples, frozen at 13 — see `00_PROJECT_STATE.md`. |
| `desktop` | **parked** | Tauri shell, last touched 2026-08-04. No deploy path ships it. Zero references to Qevik or to any control-plane endpoint in its source. Its packaging tests still pass in the gate. |
| `web` | **parked** | Next.js surface, last touched 2026-07-31. Same: no deploy path, no Qevik wiring. |
| `prototype` | **parked** | Last touched 2026-08-02. Same. |

## What "parked" means here, and what it does not

Parked: the code is intact, its tests still run in the gate, and nothing
deploys it or depends on it at runtime. It is Atlas-era work that the Qevik
product does not currently use.

Parked is **not** retired. Nothing in this repository records a decision to end
these surfaces, so claiming one would be inventing a decision. Reviving any of
them is a product decision for the owner, not a repair — and the honest
starting point is that none of them has ever been connected to the running
system.

**There is no current Qevik desktop application.** `apps/desktop` is the only
Tauri shell in the repository and it is parked. The operator surface is
`apps/control`, a web console. If a desktop product is wanted, that is a new
decision, not a resumption.

## How this is kept true

`packages/kernel/tests/test_app_composition.py` asserts that every app has a
row here, that no parked app is shipped by a deploy script, and that
`apps/control` is not marked parked. A new app with no row fails the gate,
which is what stops this table becoming a stale README.

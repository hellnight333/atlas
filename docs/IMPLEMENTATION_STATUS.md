# What Atlas actually does today

The honest inventory, for version 0.12.0-alpha.1.

Everything on this page was verified against the running application, not
against a plan. If something is missing here, it is not built. Every other
document and every website page is written from this list, so there is one
place to correct when reality changes.

## Built and working

These run today, on a fresh install, with no configuration.

| Capability | What it does | Where |
|---|---|---|
| **Orchestration** | Workspaces, projects, runs, steps, jobs, and the DAG that connects them | `orchestrator.py` |
| **Scheduler & runtime** | Queues work, enforces timeouts, records every execution | `agents/scheduler.py`, `agents/runtime.py` |
| **Automation engine** | Declarative rules: triggers, conditions, actions. Dry-run before enabling | `automation_engine.py` |
| **Approvals & governance** | Policies that pause execution *before* a job exists and wait for a person | `approval/` |
| **Worker cluster** | Registry, heartbeats, placement, reservations, leases, recovery | `cluster/` |
| **Knowledge graph** | Nodes, edges, lineage, project context | `graph_service.py` |
| **Organizations** | Teams, roles, permissions, identity, membership with expiry | `organization/` |
| **Audit** | Append-only. No update or delete path exists anywhere | `organization/` |
| **Diagnostics** | Health, environment, dependency and component reports | `diagnostics.py` |
| **Backup & restore** | Checksummed archives, validation, additive restore | `backup.py` |
| **Crash recovery** | Requeues orphaned work, expires leases, releases reservations | `recovery.py` |
| **Telemetry** | Off by default, allow-listed fields, no server to send to | `telemetry.py` |
| **Update checking** | Reports that a release exists. Never downloads or installs | `updates.py` |
| **First run** | Seven-step setup, stored per installation | `onboarding.py` |
| **Demo projects** | Five, installed as real records | `demos.py` |
| **Packaging** | Windows, macOS and Linux installers with PostgreSQL bundled | `infra/packaging/` |

## Built, with a limit worth knowing

**Model providers are not implemented.** This is the most important line on
this page.

Atlas registers two adapters, `local-flux` and `local-text`. **Both are
simulations.** They wait briefly and return placeholder structures so the
orchestration pipeline can be exercised end to end. They do not load a model
and they do not call an API.

There is no Anthropic adapter, no OpenAI adapter, no Google adapter, no
ComfyUI adapter and no Ollama adapter. The executor layer names
`ComfyExecutor`, `OllamaExecutor`, `CloudExecutor` and others — these are
**placement categories**, deciding *where* work would run. They are not
integrations.

What this means in practice: everything Atlas does to *coordinate* work is
real and complete. Nothing it does to *generate* content is connected yet.
That is why the demo projects mark each step as running now or needing a
provider, and why Automation Studio — which needs no provider at all — is the
one that runs end to end.

**Studios are screens, not a system.** The desktop has working screens for
Image, Research, Review, Agent, Automation, Approvals, Cluster, Organizations
and Diagnostics. The `/studios` endpoint returns fixed sample data rather than
a registry. The six-studio structure in `CLAUDE.md` is the design intent, not
the current state.

**The kernel API has no authentication.** It binds to localhost and assumes a
single trusted operator on the machine. The organization and permission system
governs actions *inside* Atlas; it is not a network authentication layer.

## Not built — roadmap

Named here so nobody has to guess whether they missed a setting.

| Item | Status |
|---|---|
| Real provider adapters (Anthropic, OpenAI, Google, ComfyUI, Ollama) | Planned, next priority |
| Recipes as versioned, benchmarked artifacts | Designed, not implemented |
| Plugin SDK | Interface only; no loader, no marketplace |
| Remote worker daemon | Cluster models exist; no agent to run on another machine |
| Video, Audio, Coding and Business studios | Not started |
| Vector memory / semantic search | Not started |
| Auto-update | Deliberately excluded — see `updates.py` |
| Mobile, cloud/SaaS, billing | Explicitly out of scope |

## Deliberately excluded

Not oversights. These are decisions:

- **No auto-updater.** Software that can replace its own code without being
  asked is a security property nobody agreed to.
- **No telemetry by default**, and no Atlas server to receive any.
- **No autonomous execution.** Anything irreversible stops for a human.
- **No account, no cloud, no sign-in.** Atlas has no idea who you are.

## How to check this yourself

```bash
curl localhost:8000/version          # what you are running
curl localhost:8000/health/report    # component-by-component health
curl localhost:8000/diagnostics      # full export, safe to share
curl localhost:8000/demos            # which demo steps need a provider
```

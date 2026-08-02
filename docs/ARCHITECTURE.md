# Atlas Architecture

## Layer model

```
┌──────────────────────────────────────────────────────────────┐
│ SURFACES     Web (Next.js) · Telegram · CLI · REST API       │
├──────────────────────────────────────────────────────────────┤
│ STUDIOS      Coding · Image · Video · Audio · Business ·      │
│              Research        — plugins, no direct provider    │
│                                access, ever                   │
├──────────────────────────────────────────────────────────────┤
│ KERNEL       Orchestrator (run/step DAG) · State Machine      │
│              Job Queue · Scheduler · Provider Router          │
│              Action Registry · Plugin Manager · Event Bus     │
│              Asset Library · Memory (pgvector) · Recipes      │
│              Observability (traces·metrics·cost) · Benchmarks │
│              Vault · Auth / Tenancy · Agent Loop              │
├──────────────────────────────────────────────────────────────┤
│ PROVIDERS    local  ComfyUI · vLLM · FLUX · Wan · LTX ·       │
│                     Kokoro · F5-TTS                           │
│              cloud  Claude · Gemini · Seedance · Runway ·     │
│                     Higgsfield                                │
└──────────────────────────────────────────────────────────────┘
```

## Kernel components

### Orchestrator — runs, steps, dependencies
A single flat job cannot express real work. *"Product shot → 5s video from that image →
add music → assemble"* is a dependency graph.

A `Run` owns an ordered set of `Step`s with `depends_on` edges. A step becomes eligible
only when its parents complete; outputs flow along edges as inputs.

**The graph lives in the schema from day one; the planner that populates it arrives in
Phase 2.** Retrofitting `depends_on` after six studios enqueue flat jobs is brutal — an
LLM that authors DAGs can be added at any time.

Atlas now includes a dedicated Workflow Engine that executes declarative DAG definitions,
builds immutable execution plans, validates cycles, and schedules independent branches in
parallel while delegating node execution through kernel, executor, and provider layers.
See `docs/WORKFLOW_ENGINE.md`.

### Execution State Machine
Status is an explicit machine with transitions enforced by the kernel, never a free-text
column:

```
queued → running → { completed | failed | cancelled }
         ↕ paused        ↳ retrying → running
```

Illegal transitions raise rather than silently corrupt state.

**Cancellation reaches running GPU work** via the existing heartbeat: the response carries
`should_cancel`, the worker aborts, releases the lease and cleans up partial output.
Nearly free on day one; expensive to bolt onto a live fleet later.

### Observability
First-class, and **Phase 0** — trace context must be threaded from the first line of kernel
code, since retrofitting it means touching every call site.

- `trace_id` / `span_id` propagated ingress → run → step → job → worker → provider call
- structured JSON logs, never free text
- metrics: queue depth, lease age, job duration p50/p95, GPU utilisation per node,
  failure rate per provider
- **structured failure reasons** (enum + detail) so "why did this fail" is a query
- cost per job — cloud spend in currency, local in GPU-seconds — rolled up per run,
  studio, provider and day. This is what makes "local first" measurable, not aspirational.

### Plugin Manager
A studio declares a manifest: name, version, required kernel API version, actions,
recipes, UI route. The kernel discovers, validates and enables plugins, and refuses to
load a studio built against an incompatible kernel API version.

Deliberately lightweight — no sandboxing, no hot-loading, no separate processes. That
would be over-engineering for a single-operator system.

### Action Registry
The typed capability catalog. Every operation Atlas can perform is a registered action
with a name, JSON schema, handler and permission scope. The agent loop's tool list is
generated from it — adding an action makes it available to the agent, the API, the CLI
and the UI simultaneously. Studios register actions at import time.

### Capability Layer
The Capability Layer is the semantic boundary between workflow intent and execution
implementation.

Workflow nodes declare WHAT is needed via a capability and requirement metadata.
They do not declare provider, model, API, executor, or GPU.

```
Workflow -> Capability -> Recipe -> Execution Policy -> Executor -> Provider -> Model
```

The capability registry is provider-agnostic and stores:

- capability metadata and version
- recipes per capability
- compatible provider lookup
- compatible executor lookup

Selection is delegated to policy and executor/provider layers. The capability layer does
not execute jobs and does not embed model logic.

See `docs/CAPABILITY_LAYER.md`.

### Execution Policy Engine
The Execution Policy Engine is a pure decision service.

It consumes capability intent, optional recipe selection, capability requirements, registry
inventory, and runtime context, and produces one immutable `ExecutionDecision`.

```
Workflow -> Capability -> Recipe -> Execution Policy -> Execution Decision -> Executor -> Provider -> Model
```

It does not execute jobs, schedule jobs, or communicate with providers directly.
Its responsibility is deterministic selection and machine-readable explanation.

See `docs/EXECUTION_POLICY.md`.

### Job Queue & Scheduler
Postgres-backed (`SELECT … FOR UPDATE SKIP LOCKED`). A `Job` carries:

```
action · payload · capability_req
execution_decision_id · priority · status · attempts · worker_id · lease_expires_at
```

Execution Policy produces the `execution_decision_id`; execution location is handled by the
Executor layer, not providers. See `docs/EXECUTOR_LAYER.md`.
the routing policy. Leases expire so a dead worker's job returns to the queue.
No Redis, no Celery — revisit only under measured load.

### Routing policy
```
prefer_local → fallback_cloud
```
Each provider declares `cost_per_unit`, `p50_latency`, `quality_score`, `is_local`,
`vram_gb`. The router picks the cheapest provider meeting the recipe's quality floor,
preferring local. Every routing decision is logged so it can be audited and benchmarked.

### Recipe Registry
The primitive that makes "Atlas decides, not the operator" real.

```yaml
# recipes/image/product-shot.v3.yaml
name: product-shot
version: 3
modality: image
provider: comfyui
capability_req: { vram_gb: 16 }
graph: graphs/product_shot_v3.json     # versioned ComfyUI API workflow
pins:
  checkpoint: flux1-dev.safetensors
  vae: ae.safetensors
  loras: [{ name: product-detail, weight: 0.6 }]
  controlnet: { type: depth, weight: 0.55 }
  sampler: { name: euler, steps: 28, cfg: 3.5 }
quality_score: 0.87        # populated by the benchmark harness
```

The LLM selects a recipe **by name**. It never authors node graphs.
Recipes are git artifacts: versioned, diffable, reviewable, benchmarked.

### Asset Library
Content-addressed storage (MinIO on the NAS, S3 API). Every artifact from every studio
lands here with full lineage: `parent_asset_id`, the recipe and version that produced it,
the exact resolved parameters, and the operator's verdict. "Make another like the third
one" resolves by DB lookup, not by re-describing.

Atlas now treats assets as first-class, versioned domain objects with project/workflow
context, storage metadata, tags, and lineage references. See `docs/ASSET_SYSTEM.md`.

### Event Bus
Typed topics with declared schemas; subscribers register by decorator. Studios communicate
through events, never by importing each other. This is what keeps them replaceable.

Implementation details and event contract are documented in `docs/EVENT_BUS.md`.

### Composition Root and dependency graph
Runtime wiring now happens in one place: `packages/kernel/atlas_kernel/composition_root.py`.

Rules:

- Core subsystems are constructor-injected and do not instantiate one another directly.
- Defaults are allowed only in the composition root.
- A single shared `EventBus` instance is passed to orchestrator, worker, executor,
  asset service, and workflow engine.
- API and worker entrypoints bootstrap through `create_runtime()`.

This removes hidden local defaults, prevents event-bus fragmentation, and makes runtime
topology explicit and testable. See `docs/COMPOSITION_ROOT.md`.

### Memory
Postgres + pgvector. Three tiers: **brand** (tone, palette, do/don't), **project**,
**asset**. Injected into the agent loop as context, not stuffed into prompts by hand.

## Core domain entities

Atlas now models the control plane with explicit core domain entities:

- `Workspace`: a top-level organization boundary that owns projects and namespaces assets.
- `Project`: a scoped collection of work inside a workspace, useful for campaigns and iterative design.
- `Workflow`: a reusable execution template with a studio, default action, and capability requirements.
- `Run`: an execution instance of a workflow or a studio request, owning steps, jobs, and results.
- `Job`: a schedulable unit of work with routing metadata and provider execution state.
- `Asset`: the content produced by a completed job, stored with lineage and metadata.

These concepts are implemented in the kernel with new tables and optional run metadata to preserve the current execution surface while making the domain explicit.

## Compute topology

```
        ┌───────────────────────────────┐
        │  Hetzner 204.168.249.69       │  control plane, always-on
        │  Postgres · Queue · Web · API │
        └───────────────┬───────────────┘
                        │  Tailscale — workers dial OUT, no inbound ports
        ┌───────────────┼───────────────┬──────────────────┐
        │               │               │                  │
┌───────▼────────┐ ┌────▼──────────┐ ┌──▼──────────────┐   │
│ HP Z8          │ │ Lenovo i9     │ │ cloud adapters  │   │
│ Ubuntu 24.04   │ │ Ubuntu 24.04  │ │ Claude · Gemini │   │
│ GPU 0 … GPU N  │ │ GPU 0         │ │ Seedance · …    │   │
│ ComfyUI · vLLM │ │ ComfyUI·vLLM  │ └─────────────────┘   │
└───────┬────────┘ └────┬──────────┘                       │
        └───────┬───────┘                                  │
        ┌───────▼─────────────┐                            │
        │ NAS — MinIO (S3)    │◄───────────────────────────┘
        │ content-addressed   │
        └─────────────────────┘
```

## Fleet

Both GPU nodes run an **identical** Ubuntu 24.04 LTS Server build — one OS, one image,
one playbook, one set of bugs. Homogeneity is a deliberate choice; a mixed fleet doubles
every operational surface for no benefit.

Provision with `infra/provision_node.sh`. It runs in two stages (the NVIDIA driver needs a
reboot between them) and is idempotent — safe to re-run.

**Only the NVIDIA driver is installed on the host. CUDA is not.** CUDA ships inside the
containers, so different workloads pin different CUDA versions without fighting each other
and the host stays clean across driver upgrades.

The scheduler routes purely on declared capability, so adding a third node is a
provisioning task, not a code change:

```
job.capability_req{vram_gb: 48} → only nodes advertising ≥48GB are eligible
job.capability_req{vram_gb: 12} → any node; cheapest/idlest wins
```

Workers **poll**; the control plane never connects inward. No port forwarding, no NAT
traversal, no dynamic-DNS fragility. A worker that goes offline simply stops leasing.

## Worker protocol

1. `POST /v1/workers/register` → advertise `{gpu, vram_gb, model_families, runtimes}`
2. `POST /v1/workers/lease` → long-poll for a matching job, receive a lease
3. `POST /v1/jobs/{id}/heartbeat` → extend lease while running
4. `POST /v1/jobs/{id}/complete` → upload asset, report resolved params + timings
5. Lease expiry → job returns to queue, `attempts += 1`

## Repository layout

```
atlas/
  CLAUDE.md                 master context — read first
  docs/
    ARCHITECTURE.md         this file
    ROADMAP.md              phases and exit criteria
    LESSONS_FROM_NAML.md    production bugs already paid for once
    decisions/              ADRs
  packages/
    kernel/                 registry, queue, scheduler, bus, library, memory, recipes
    providers/              uniform adapters, one module each
  studios/
    image/                  first studio
  workers/
    gpu/                    Z8 worker agent
  apps/
    web/                    Next.js control surface
  recipes/
    image/                  versioned recipe YAML + ComfyUI API graphs
  infra/                    compose files, Tailscale, MinIO, migrations
```

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
│ KERNEL       Action Registry · Job Queue · Scheduler          │
│              Event Bus · Asset Library · Memory (pgvector)    │
│              Agent Loop · Recipe Registry · Benchmarks        │
│              Vault · Auth / Tenancy                           │
├──────────────────────────────────────────────────────────────┤
│ PROVIDERS    local  ComfyUI · vLLM · FLUX · Wan · LTX ·       │
│                     Kokoro · F5-TTS                           │
│              cloud  Claude · Gemini · Seedance · Runway ·     │
│                     Higgsfield                                │
└──────────────────────────────────────────────────────────────┘
```

## Kernel components

### Action Registry
The typed capability catalog. Every operation Atlas can perform is a registered action
with a name, JSON schema, handler and permission scope. The agent loop's tool list is
generated from it — adding an action makes it available to the agent, the API, the CLI
and the UI simultaneously. Studios register actions at import time.

### Job Queue & Scheduler
Postgres-backed (`SELECT … FOR UPDATE SKIP LOCKED`). A `Job` carries:

```
kind · payload · capability_req{vram_gb, model_family, modality}
priority · status · attempts · worker_id · lease_expires_at
```

The scheduler matches `capability_req` against registered workers and assigns work under
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

### Event Bus
Typed topics with declared schemas; subscribers register by decorator. Studios communicate
through events, never by importing each other. This is what keeps them replaceable.

### Memory
Postgres + pgvector. Three tiers: **brand** (tone, palette, do/don't), **project**,
**asset**. Injected into the agent loop as context, not stuffed into prompts by hand.

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

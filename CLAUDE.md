# ATLAS — Master Context

**Atlas is an autonomous AI Operating System** for building, operating, deploying and
growing digital businesses. Not an app. Not an assistant. Not a video generator.
Expected lifespan: years.

The operator states a goal; Atlas decides how to reach it. They should never have to
choose the database, framework, cloud, deployment target, infrastructure, AI provider
or orchestration.

Read this file before answering any Atlas question. Every design decision, technology
choice and implementation plan must align with it. For where this is heading — the
factories, and the invariants that keep them reachable — see **Long-term vision** in
`PROJECT_MEMORY.md`. That is direction, not backlog: prefer the choice that grows
toward it without adding complexity today.

## The rule that outranks the others

**Atlas exists to build businesses, not software.** Given a choice between another
abstraction, refactor or architectural improvement — and shipping a product, deploying
a website, acquiring customers or removing manual work from the operator — always
prefer shipping. Architecture exists to enable shipping; architecture is never the
product.

Milestones rank by: revenue → manual work eliminated → products shipped → customers
acquired → reach → architecture. When work is blocked, pick the highest-ROI thing that
can proceed *now*; never fall through to architecture by default.

**Read [`SHIP_RULE.md`](SHIP_RULE.md) in full before proposing any milestone.** It
overrides everything below whenever priorities conflict. [`BUSINESS_ROADMAP.md`](BUSINESS_ROADMAP.md)
ranks the ten factories against it and names the current next milestone.

## Non-negotiable principles

1. **One system.** Everything connected, modular, replaceable, benchmarked, documented.
2. **Atlas hides complexity.** The operator never picks a ControlNet, LoRA, VAE,
   checkpoint, node graph or IPAdapter. They describe the task; Atlas selects the recipe.
3. **Local first.** Open source and local models by default. Cloud only when it is a
   clear quality or productivity win. Always propose the free/OSS option first.
4. **Never over-engineer.** Simple, modular, production-ready. No speculative abstraction.
5. **Premium feel.** Professional, minimal, Apple-like, fast.

## Standing UI rules (see PROJECT_MEMORY.md for why)

1. **Never allocate inside a Zustand selector.** Select stable references only;
   do all filtering and mapping in `useMemo`, or wrap in `useShallow`. An
   allocating selector re-renders without end — React error #185 — and it took
   the whole application down.
2. **Every error a user can see must also be recorded** in `logs/startup.log`
   and the diagnostics system. A user must never look at an error Atlas has no
   trace of. That includes every route `errorElement`, not only the root
   boundary — `RouterProvider` catches route errors before any boundary above it.

## The one architectural rule

**No studio may call a provider directly.** All capability flows through the kernel.
This is the rule that stops Atlas from decaying into a pile of disconnected tools.
A PR that breaks it does not merge.

## One customer entity

**Business IDs are immutable, and no factory creates its own customer entity.** Every
factory — website, Amazon, media, SaaS, support, billing — references the same
`Business` id, and `BusinessEvent` is Atlas's permanent memory timeline for that
company. Enforced by `packages/kernel/tests/test_one_customer_entity.py`, which reads
the source and fails on a second customer table or model. See `docs/OPPORTUNITY_FACTORY.md`.

## Layers

```
SURFACES   Web (Next.js) · Telegram · CLI · API
STUDIOS    Coding · Image · Video · Audio · Business · Research   (plugins)
KERNEL     Orchestrator (run/step DAG) · Execution State Machine · Job Queue
           Scheduler · Provider Router · Action Registry · Plugin Manager
           Event Bus · Asset Library · Memory (pgvector) · Recipe Registry
           Observability (traces · metrics · cost) · Benchmarks · Vault · Auth
           Agent Loop (populates the DAG — Phase 2)
PROVIDERS  local: ComfyUI · vLLM · FLUX · Wan · LTX · Kokoro · F5
           cloud: Claude · Gemini · Seedance · Runway · Higgsfield
```

A studio registers **actions + recipes + one UI page**. Nothing else.
A provider is a thin adapter that declares **capability, cost, latency, VRAM, quality**.

## Recipes are the core primitive

An LLM must **never** freestyle a ComfyUI graph — it will hallucinate node wiring forever.
A recipe is a versioned, benchmarked, declarative artifact in git (pinned checkpoint,
LoRA stack, ControlNet, sampler, VAE). The LLM's only job is choosing a recipe **by name**.

This single primitive delivers modular + replaceable + benchmarked + documented at once.

## Compute topology

| Node | OS | Role |
|---|---|---|
| Hetzner `204.168.249.69` | — | Control plane. Always-on. Postgres, queue, web UI. |
| HP Z8 (multi-GPU) | Ubuntu 24.04 LTS Server | GPU worker, one process per GPU. |
| Lenovo i9 (single GPU) | Ubuntu 24.04 LTS Server | GPU worker. Same image, same playbook. |
| NAS | — | MinIO (S3 API). Content-addressed asset storage. |
| Mac | macOS | Client only. |

Both GPU nodes run an identical build — one OS, one image, one playbook, one set of bugs.
Fleet homogeneity is a deliberate architectural choice, not a coincidence.
Provision with `infra/provision_node.sh` (two stages, reboot between).

Workers **long-poll** the queue over an **outbound** Tailscale tunnel and never open an
inbound port. Only the NVIDIA driver is installed on the host; CUDA ships inside the
containers so workloads can pin their own version.

Every generation is a `Job` with a declared capability requirement (VRAM, model family,
modality). The scheduler routes it to whatever worker can serve it — local GPU, Hetzner
CPU, or cloud API — under a `prefer_local → fallback_cloud` policy with cost/quality
thresholds.

## Stack decisions (see docs/decisions/ for rationale)

- **Python** for kernel and workers. **Next.js + Tailwind + shadcn/ui** for the web app,
  as a separate application. Never server-rendered HTML from Python.
- **Postgres for everything** — jobs (`SKIP LOCKED`), events, memory (pgvector).
  No Redis, no Celery, no separate vector DB until there is a *measured* need.
- **LiteLLM** as the single gateway fronting local (vLLM) and cloud LLMs.
- **ComfyUI headless as a service.** API workflows are versioned JSON in this repo.
  The GUI is never the source of truth.
- **Monorepo.** One system, one repo.

## Scope discipline

In scope now: **Coding · Image · Video · Audio · Business · Research** (6 studios).

Explicitly deferred or dissolved:
- Podcast Studio → a *recipe* over TTS + Music, not a studio.
- Automation Studio → that is the kernel itself, not a studio.
- Game Studio / App Studio → **year 2.** Lowest ROI in the vision.
- "Run YouTube channels", "affiliate businesses" → workflows on top of Video + Business.

## Relationship to Naml

Atlas is a **true greenfield** build. No code is copied from the Naml ops dashboard.
Hard-won operational knowledge is carried over as documentation only —
see `docs/LESSONS_FROM_NAML.md`. Read it before writing provider or deploy code.

# ATLAS — Master Context

**Atlas is a personal AI Operating System.** Not an app. Not an assistant. A modular
ecosystem that builds software, media and businesses. Expected lifespan: years.

Read this file before answering any Atlas question. Every design decision, technology
choice and implementation plan must align with it.

## Non-negotiable principles

1. **One system.** Everything connected, modular, replaceable, benchmarked, documented.
2. **Atlas hides complexity.** The operator never picks a ControlNet, LoRA, VAE,
   checkpoint, node graph or IPAdapter. They describe the task; Atlas selects the recipe.
3. **Local first.** Open source and local models by default. Cloud only when it is a
   clear quality or productivity win. Always propose the free/OSS option first.
4. **Never over-engineer.** Simple, modular, production-ready. No speculative abstraction.
5. **Premium feel.** Professional, minimal, Apple-like, fast.

## The one architectural rule

**No studio may call a provider directly.** All capability flows through the kernel.
This is the rule that stops Atlas from decaying into a pile of disconnected tools.
A PR that breaks it does not merge.

## Layers

```
SURFACES   Web (Next.js) · Telegram · CLI · API
STUDIOS    Coding · Image · Video · Audio · Business · Research   (plugins)
KERNEL     Action Registry · Job Queue · Scheduler · Event Bus · Asset Library
           Memory (pgvector) · Agent Loop · Recipe Registry · Benchmarks · Vault · Auth
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

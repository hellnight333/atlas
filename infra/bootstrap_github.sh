#!/usr/bin/env bash
# One-time GitHub bootstrap for Atlas.
# Creates the private repo, labels, milestones, the Phase 0-3 issue backlog,
# and an "Atlas Roadmap" project board.
#
# Prereq:  gh auth login   (interactive — must be run by the repo owner)
# Usage:   bash infra/bootstrap_github.sh
set -euo pipefail

REPO_NAME="${REPO_NAME:-atlas}"

command -v gh >/dev/null || { echo "gh not installed"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Not authenticated. Run: gh auth login"; exit 1; }

OWNER="$(gh api user --jq .login)"
REPO="$OWNER/$REPO_NAME"
echo "==> Target repo: $REPO"

# ---------------------------------------------------------------- repo
if gh repo view "$REPO" >/dev/null 2>&1; then
  echo "==> Repo already exists, reusing"
else
  gh repo create "$REPO" --private \
    --description "Atlas — a personal AI Operating System. Local-first, modular, benchmarked."
  echo "==> Created $REPO"
fi

git remote get-url origin >/dev/null 2>&1 || \
  git remote add origin "https://github.com/$REPO.git"

# ---------------------------------------------------------------- labels
label() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force >/dev/null; }
echo "==> Labels"
label kernel          "5319E7" "Kernel: registry, queue, scheduler, bus, library, recipes"
label providers       "0E8A16" "Provider adapters, local and cloud"
label infra           "B60205" "Hosts, networking, storage, deploys"
label "studio:image"  "1D76DB" "Image Studio"
label "studio:video"  "1D76DB" "Video Studio"
label "studio:audio"  "1D76DB" "Audio Studio"
label "studio:business" "1D76DB" "Business Studio"
label "studio:research" "1D76DB" "Research Studio"
label "studio:coding" "1D76DB" "Coding Studio"
label web             "C2E0C6" "Next.js control surface"
label agent           "FBCA04" "Agent loop, planning, memory"
label benchmark       "D4C5F9" "Benchmark harness and scoring"
label docs            "CCCCCC" "Documentation and ADRs"
label blocked         "000000" "Blocked on an external dependency"

# ---------------------------------------------------------------- milestones
ms() {
  gh api "repos/$REPO/milestones" -X POST -f title="$1" -f description="$2" >/dev/null 2>&1 \
    || echo "    (milestone '$1' exists)"
}
echo "==> Milestones"
ms "Phase 0 — Kernel + vertical slice" \
   "Exit: prompt in web UI -> job queue -> Z8 GPU worker over Tailscale -> ComfyUI recipe -> asset in Library with lineage, surviving a worker killed mid-job."
ms "Phase 1 — Recipes, benchmarks, routing" \
   "Exit: same prompt resolves to a different provider by changing routing policy alone, no code change. Three recipes scored on a fixed eval set."
ms "Phase 2 — Agent loop + LLM tier" \
   "Exit: a single plain-language brief produces an approved plan and executes it, on local Qwen via LiteLLM with cloud fallback."
ms "Phase 3 — Video Studio" \
   "Exit: t2v and i2v both run through the recipe system; local (Wan/LTX) and cloud (Seedance) selectable by policy alone."

# ---------------------------------------------------------------- issues
issue() { # issue <milestone> <labels> <title> <body>
  gh issue create --repo "$REPO" --milestone "$1" --label "$2" --title "$3" --body "$4" >/dev/null
  echo "    + $3"
}

echo "==> Phase 0 issues"
P0="Phase 0 — Kernel + vertical slice"

issue "$P0" "kernel,docs" "Repo tooling: uv, ruff, pytest, pre-commit, CI" \
"Python toolchain for the monorepo.

- uv for dependency management, workspace layout across \`packages/*\`
- ruff (lint + format), mypy on \`packages/kernel\` only to start
- pytest with a \`tests/\` root per package
- pre-commit running ruff + secret scanning
- GitHub Actions: lint + test on PR

**Done when:** a fresh clone reaches green tests with two commands."

issue "$P0" "kernel,infra" "Postgres schema and Alembic migrations" \
"Foundational schema: jobs, workers, assets, events, recipes, actions, tenants.

Schema rules (see docs/LESSONS_FROM_NAML.md):
- lowercase enums, \`id\` as the key everywhere, no JSON-in-TEXT columns
- set \`idle_in_transaction_session_timeout\` at the database level
- never pair UNIQUE with a non-null default on a generated column

**Done when:** \`alembic upgrade head\` builds the schema from empty, and downgrade works."

issue "$P0" "kernel" "Job queue: enqueue, lease, complete, expire" \
"Postgres-backed queue using \`SELECT … FOR UPDATE SKIP LOCKED\`. No Redis, no Celery.

Job carries: \`kind\`, \`payload\`, \`capability_req{vram_gb, model_family, modality}\`, \`priority\`, \`status\`, \`attempts\`, \`worker_id\`, \`lease_expires_at\`.

- leases expire so a dead worker's job returns to the queue
- \`attempts\` increments on requeue; a max-attempts job goes to \`failed\` with a reason
- all DB access context-managed; no manual commit in business logic

**Done when:** a concurrency test with N workers shows zero double-processing, and a killed worker's job is re-leased after expiry."

issue "$P0" "kernel" "Worker protocol REST API" \
"Endpoints backing the poll-based worker model:

- \`POST /v1/workers/register\` — advertise \`{gpu, vram_gb, model_families, runtimes}\`
- \`POST /v1/workers/lease\` — long-poll for a matching job
- \`POST /v1/jobs/{id}/heartbeat\` — extend the lease
- \`POST /v1/jobs/{id}/complete\` — upload asset, report resolved params and timings
- \`POST /v1/jobs/{id}/fail\` — structured failure reason

Workers dial out only. The control plane never connects inward."

issue "$P0" "kernel" "Action Registry" \
"The typed capability catalog. Every operation Atlas can perform is registered with a name, JSON schema, handler and permission scope.

Studios register actions at import time. The agent tool list, REST API, CLI and UI are all generated from the registry — adding an action exposes it everywhere at once.

**Done when:** a studio can register an action and it is callable via REST with schema validation, with no other wiring."

issue "$P0" "kernel" "Event Bus with declared topic schemas" \
"Typed topics, schema-declared, subscribers registered by decorator.

Studios communicate through events and never import each other. This boundary is what makes studios genuinely replaceable.

**Done when:** publishing to a topic with a payload that violates its schema fails loudly at publish time, not at the subscriber."

issue "$P0" "kernel,infra" "Vault and secrets loading" \
"Single secrets interface for the kernel. Provider adapters request credentials by name; nothing reads env vars directly.

- no secret ever committed (\`.gitignore\` + pre-commit scanning already in place)
- missing credential fails at provider registration, not at first job"

issue "$P0" "kernel,infra" "Asset Library on MinIO, content-addressed" \
"MinIO (S3 API) on the NAS. Every artifact from every studio lands here.

Each asset records full lineage: \`parent_asset_id\`, the recipe name and version that produced it, the exact resolved parameters, and the operator's verdict.

**Done when:** 'make another like the third one' is answerable by DB lookup alone, and identical content stored twice occupies one object."

issue "$P0" "kernel" "Recipe Registry: schema, loader, validation" \
"The primitive that makes 'Atlas decides, not the operator' real.

A recipe is versioned declarative YAML in git pinning checkpoint, LoRA stack, ControlNet, sampler and VAE, bound to a ComfyUI API graph. See docs/ARCHITECTURE.md for the shape.

The LLM selects a recipe **by name** and never authors node graphs.

**Done when:** an invalid recipe fails at load with a precise error, and every recipe resolves to a concrete provider + capability requirement."

issue "$P0" "providers" "Provider adapter interface and capability declaration" \
"Uniform base every adapter implements. Each declares \`cost_per_unit\`, \`p50_latency\`, \`quality_score\`, \`is_local\`, \`vram_gb\`, supported modalities.

Each adapter owns a **validator** that rejects impossible payloads locally, before spending a network call or a credit — provider constraints are encoded as validation, never as comments. See docs/LESSONS_FROM_NAML.md.

**Done when:** a second adapter can be added without touching the scheduler."

issue "$P0" "providers" "ComfyUI headless provider adapter" \
"Run ComfyUI as a service. API workflows are versioned JSON in \`recipes/\`; the GUI is never the source of truth.

- submit graph, poll progress, retrieve outputs
- map recipe pins onto graph inputs deterministically
- surface node-level errors as structured failures, not raw tracebacks"

issue "$P0" "infra" "Provision the GPU fleet: HP Z8 and Lenovo i9" \
"Both nodes run an **identical** Ubuntu 24.04 LTS Server build — one OS, one image, one playbook, one set of bugs. Fleet homogeneity is deliberate.

\`infra/provision_node.sh\` handles it in two idempotent stages (NVIDIA driver needs a reboot between them): base packages, headless NVIDIA driver, Docker CE, NVIDIA Container Toolkit, Tailscale.

Only the driver goes on the host — **CUDA ships inside containers** so workloads pin their own version and the host stays clean across driver upgrades.

**Done when:** \`docker run --rm --gpus all …  nvidia-smi -L\` lists every GPU on both nodes."

issue "$P0" "infra" "Tailscale mesh: Hetzner control plane <-> GPU fleet" \
"Outbound-only connectivity from every worker. No port forwarding, no NAT traversal, no dynamic DNS.

**Done when:** both GPU nodes reach the control plane API with no inbound firewall rule on their side, and survive a router reboot without manual intervention."

issue "$P0" "infra,providers" "GPU worker agent" \
"One worker process per GPU, running on both the Z8 and the Lenovo. Registers, long-polls for a matching job, heartbeats, executes via a local runtime, uploads to MinIO, reports resolved params and timings.

- \`CUDA_VISIBLE_DEVICES\` pinned per process
- advertises real capability (\`vram_gb\`, model families, runtimes) so the scheduler routes on facts, not hostnames
- clean shutdown releases the lease immediately rather than waiting for expiry
- all dependencies baked into the image; nothing pip-installed at runtime

**Done when:** adding a third node requires provisioning only — zero code changes."

issue "$P0" "studio:image,kernel" "Image Studio plugin" \
"The first studio, and the reference implementation of the plugin contract: it registers **actions + recipes + one UI page**, and nothing else.

**The hard rule: no studio may call a provider directly.** All capability flows through the kernel. A change that breaks this does not merge."

issue "$P0" "studio:image" "First recipe: product-shot v1 on FLUX" \
"End-to-end proof that the recipe system carries a real generation.

Pins checkpoint, VAE, LoRA stack, ControlNet and sampler. Versioned as \`product-shot.v1.yaml\` with its ComfyUI API graph committed alongside."

issue "$P0" "web" "Next.js control surface: shell, generate page, live job pane" \
"Next.js + Tailwind + shadcn/ui as a separate application. Never server-rendered HTML from Python.

- app shell and navigation
- generate page: prompt in, recipe auto-selected
- live job pane: running / queued / finished with thumbnails streaming in
- **long-running buttons show synchronous visible feedback before the first await**

Professional, minimal, Apple-like, fast."

issue "$P0" "kernel" "Auth and tenancy" \
"Operator accounts, sessions, and a tenant boundary on every kernel table from day one. Retrofitting multi-tenancy later is far more expensive than carrying it from the start."

issue "$P0" "kernel,infra" "E2E smoke test and worker-kill resilience test" \
"The Phase 0 exit criterion, encoded as an automated test.

1. Submit a prompt through the web API
2. Assert the job is queued, leased by the Z8 worker, and completed
3. Assert the asset exists in MinIO with correct lineage
4. Kill the worker mid-job; assert the job is re-leased and completes

**Phase 0 is not done until this passes in CI against a real worker.**"

echo "==> Phase 1 issues"
P1="Phase 1 — Recipes, benchmarks, routing"

issue "$P1" "benchmark" "Benchmark harness and fixed evaluation set" \
"A frozen prompt set and scoring pipeline so recipes and providers are comparable over time. Scores write back to the recipe's \`quality_score\`.

'Everything benchmarked' stops being a slogan here."

issue "$P1" "kernel" "Routing policy engine" \
"\`prefer_local -> fallback_cloud\` as the default policy, with \`prefer_quality\` and \`prefer_cost\` alternatives.

Picks the cheapest provider meeting the recipe's quality floor, preferring local. Every routing decision is logged so it can be audited.

**Done when:** the same prompt resolves to a different provider by changing policy alone, with no code change."

issue "$P1" "providers,benchmark" "Provider scorecards" \
"Continuously maintained cost, p50/p95 latency, quality and VRAM figures per provider, fed from real job telemetry rather than declared constants."

issue "$P1" "providers" "Balance preflight for paid providers" \
"Exhausted prepaid credit previously surfaced as a generic 402 or a mystery 502 rather than 'you are out of money'.

Every paid adapter exposes \`check_balance()\`; the scheduler preflights it so a job fails with *'provider X out of credit'*."

issue "$P1" "kernel,docs" "Recipe versioning and promotion workflow" \
"How a recipe moves from draft to default: benchmark against the incumbent, require a score improvement, promote by version bump. Recipes are git artifacts — diffable, reviewable, revertible."

issue "$P1" "infra" "Zero-downtime deploys" \
"A naive restart previously meant 30-90s of 502s, and hot-reloading multi-worker processes left workers desynced on stale code.

Atlas rule: **workers are replaced, never reloaded.** The job queue makes this straightforward since in-flight work survives in Postgres.

**Done when:** a deploy under sustained load drops zero requests and loses zero jobs."

echo "==> Phase 2 issues"
P2="Phase 2 — Agent loop + LLM tier"

issue "$P2" "agent,providers" "LiteLLM gateway for local and cloud LLMs" \
"One OpenAI-compatible endpoint fronting local vLLM (Qwen, GLM, DeepSeek) and cloud (Claude, Gemini). Collapses the entire LLM tier into a single interface."

issue "$P2" "agent" "Agent loop: plan -> ask -> act -> observe" \
"Conversational, not a rigid state machine. Tools come from the Action Registry, so the agent gains capability automatically as studios register actions.

Plans are proposed for approval before execution."

issue "$P2" "agent,kernel" "Memory: brand / project / asset tiers on pgvector" \
"Postgres + pgvector, no separate vector database. Injected into the agent loop as structured context rather than hand-stuffed into prompts."

issue "$P2" "web,agent" "Plan approval UI" \
"Numbered plan showing which provider each step will hit, with per-step edit and approve. The operator approves rather than types parameters."

echo "==> Phase 3 issues"
P3="Phase 3 — Video Studio"

issue "$P3" "studio:video" "Video Studio plugin" \
"Second studio, and the real test of the plugin contract. If it needs a kernel change, the kernel was wrong — fix the kernel rather than special-casing the studio."

issue "$P3" "providers,studio:video" "Local video providers: Wan and LTX" \
"Local-first video generation on the Z8, exposed through recipes exactly like image."

issue "$P3" "providers,studio:video" "Seedance cloud provider with payload validator" \
"Cloud video fallback. The adapter's validator must encode the provider's real constraints locally, before spending a call:

- \`first_frame_url\` and \`images\`/\`videos\` are mutually exclusive, not additive
- a reference video longer than the requested output is rejected — trim before submitting

See docs/LESSONS_FROM_NAML.md."

# ---------------------------------------------------------------- project board
echo "==> Project board"
if gh project create --owner "$OWNER" --title "Atlas Roadmap" >/dev/null 2>&1; then
  echo "    created 'Atlas Roadmap'"
else
  echo "    (project exists, or 'project' scope missing — run: gh auth refresh -s project,read:project)"
fi

echo
echo "Done. Repo: https://github.com/$REPO"
echo "Next:  git push -u origin main"

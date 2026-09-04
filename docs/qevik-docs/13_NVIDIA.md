# NVIDIA — what to use, what to build toward, and what to leave alone

Researched 2026-09-04 against the live sources: `github.com/NVIDIA/skills` (350
skills, read directly), the AI-Q, RAG and VSS blueprint repositories, and the
**NVIDIA API Trial Terms of Service**.

The catalogue is large and free and it is tempting to let it set the
architecture. It should not. Read this before adding an NVIDIA dependency.

---

## The finding that decides most of it

**NVIDIA's hosted API — `build.nvidia.com` / `integrate.api.nvidia.com` — is
contractually a trial. It may not be used in production.**

From the API Trial Terms of Service, verbatim:

> **§1.4** "You must have a separate service subscription … to use the API
> Service in production or to use the API Service after you have used your
> available Credits. **Unless you purchase a Subscription from NVIDIA or a
> Service Provider (as applicable), you may only use the API Service for
> internal testing and evaluation purposes, not in production.**"

Four more clauses matter specifically for what Qevik does:

| Clause | What it says | Why it bites here |
|---|---|---|
| §3.3(iv) | NVIDIA may use your content and the generated content "to improve NVIDIA products and services, including AI models" | A customer's documents would train somebody else's model |
| §4.2 | You may not distribute or make available to others any portion of the Generated Content | A generated website *is* content given to somebody else |
| §4.3 | No personal, financial, health or governmental information | A CRM is personal information by definition |
| §4.6 | No unsolicited automated bulk communications | Outreach is exactly that shape |

Self-hosting NIM does not solve it either. NVIDIA's NIM FAQ grants Developer
Program members a licence "for research, application development, and
experimentation on up to 16 GPUs", and defines the boundary explicitly:
production use is "any use of NIM for purposes other than development, testing,
research or evaluation **such as conducting business transactions**". The paid
path is NVIDIA AI Enterprise at **$4,500 per GPU per year**, licensed per GPU
*installed*, not per GPU used. (75% off for Inception members — worth checking
eligibility before assuming the list price.)

Three of the technologies below — **DALI, cuDF, cuOpt** — are Apache-2.0 and sit
outside both gates entirely. cuOpt was open-sourced in June 2025 and the old
"production requires AI Enterprise" language in indexed documentation is stale.

### The operational limits, separately from the legal ones

- **~40 requests per minute**, and an NVIDIA moderator has confirmed on the
  forums that there is "no official way to circumvent this rate limit or to
  receive a rate limit increase on that same tier".
- **No `Retry-After` header, no `X-RateLimit-*` headers, no usage endpoint.**
  All rate accounting is client-side and blind.
- 429s fire below 40 RPM on some models. The trigger is *concurrency*, not
  volume — which is precisely the shape of an agent platform that fans out.
- The credits system was removed in early 2025. Any guide mentioning "1,000 free
  credits" is out of date.

Measured here, and worth knowing before anybody runs a survey: **a burst of six
concurrent requests got this machine's IP blocked at the edge** — `403 Forbidden`
as an nginx HTML page for every request, from every model, while the same key
worked fine from another address a second later. An HTML 403 is an abuse
response; this API's authentication failures are JSON.

### What Qevik does about it

`ModelSpec.terms` carries `PRODUCTION` or `EVALUATION_ONLY`, and
`ModelRegistry.resolve` will not select an evaluation-only model unless the
caller says `evaluating=True`. Naming one explicitly is refused too, because a
model selection is data an operator edits.

This is enforced rather than documented for one reason: **a free tier is the
cheapest thing in any catalogue, and the registry picks cheapest-capable.** The
failure guarded against is not somebody deciding to break the terms — it is
nobody deciding anything at all.

---

## The catalogue is not an inventory

`GET /v1/models` returns 81 models for this key. Most of them cannot be called:
404 "Function not found", 410 "Gone", 503 "temporarily overloaded". A page built
from that listing would present offerings nobody has tried.

So Qevik measures instead. `llm/benchmark.py` calls each registered model
through the same adapter production uses and records REACHED / REFUSED /
NOT_VERIFIED, with latency and cost. The Models page shows it. Nothing scores
quality: one trivial prompt cannot, and a number that looked like a quality
score would be believed.

---

## The decision

### USE NOW

**NVIDIA models, for evaluation only** — comparing a candidate against Qwen
before committing to it, and reaching model families nobody else hosts. Free,
no GPU, one key. Bounded by `Terms.EVALUATION_ONLY`, which means the CRM, the
outreach and the customer-website work cannot reach it. That is the point.

**`nemo-retriever` (the skill and its CLI)** — indexes a folder of PDFs,
images, Office documents, HTML, audio and video into LanceDB and serves vector
search over it. This is the `knowledge/embeddings` layer of the architecture,
available today, and the skill's own instruction is the right one: *do not write
a custom RAG.*

Installed at `~/.claude/skills/nemo-retriever`. One caveat that decides what it
may be pointed at: **without a local GPU it needs a remote embedding endpoint**,
and the one to hand is the trial API. So it is right for *our* corpora —
competitor sites, market documents, our own research — and wrong for a
customer's files, because §4.3 forbids sending personal or financial information
and §3.3(iv) lets NVIDIA train on what arrives. The moment a GPU exists, the
bundled `llama-nemotron-embed-1b-v2` runs locally and that constraint
disappears.

**SkillSpector** — NVIDIA's scanner for agent skills (prompt injection,
exfiltration, supply-chain risk). Useful against *any* third-party skill,
including ones that have nothing to do with NVIDIA. Cheap insurance the moment
a skill from outside this repository is installed.

**`nvidia-skill-finder`** — a router that recommends which of the 350 skills
fits a request. One skill, no infrastructure. Worth having so the catalogue is
searchable without installing it.

### ARCHITECT FOR LATER

**Video understanding.** VSS is the right destination and the wrong thing to
build against today: 1–3 GPUs for a dev profile, validated only on H100 / L40S /
RTX PRO 6000, Docker pinned to a version range, and *"NVIDIA AI Enterprise
developer licence required to local host NVIDIA NIM"*. The move is to define a
`video.understand` capability in the media registry now — one interface, a cloud
VLM behind it — so that swapping in VSS when a GPU box exists is a provider
registration and not a rewrite. That is the same shape the media provider
registry already uses.

**Deep research.** AI-Q is genuinely the closest fit to what Qevik is, and it
runs with **zero GPUs** against NVIDIA-hosted inference — but that inference is
the trial tier, so a research report generated through it is Generated Content
under §4.2. Architect the research capability against Qevik's own recipes and
agent registry, which already exist, and treat AI-Q as a reference
implementation to read rather than a service to depend on.

**RAG at scale.** The full blueprint wants 3 GPUs on Docker and 8 on Kubernetes.
`nemo-retriever` covers the same ground at this size. Revisit when the corpus
outgrows one machine, not before.

**cuOpt.** Apache-2.0, no licence gate, and genuinely useful the day Qevik does
routing or scheduling for a customer — logistics, field-service, delivery
windows. Nothing today needs it. Its container ships with **no authentication**,
which is a deployment fact to remember rather than discover.

### REJECT — for now, and with reasons

**DeepStream.** Real-time multi-stream video analytics on local GPUs. The
runtime is proprietary and may not be redistributed as part of a product. Qevik
has no camera feeds and no GPU. Nothing here is about the technology being poor.

**DALI.** A GPU data-loading library for training. Qevik trains nothing.

**cuDF.** GPU DataFrames, needs compute capability 7.0+. Qevik's largest table
is 59 businesses. Postgres is not the bottleneck and will not be for a long
time.

**TAO, Jetson (38 skills), DOCA (61 skills), Holoscan, Isaac, Megatron-Core,
PhysicsNeMo, Earth2Studio.** Model training, embedded devices, DPU programming,
medical imaging, robotics, weather. Excellent, and about a different business.

**AI Enterprise, today.** $4,500/GPU/year buys production rights to things Qevik
does not yet run. The order is: have the workload, then buy the licence.

---

## If the free tier ever becomes the plan

There is no self-serve paid tier on `build.nvidia.com`. The routes are:

1. **NVIDIA Cloud Functions (NVCF)** on DGX Cloud — serverless, bring your own
   container. Probably the cheapest legitimate hosted path.
2. **Serverless NIM on Hugging Face**, pay-per-use — NVIDIA's own suggestion.
3. **NVIDIA AI Enterprise**, $4,500/GPU/year.
4. **Self-host NIM** on owned GPUs, which still needs (3) for production.

Qwen through DashScope is already a paid, production-licensed provider that
works, and is roughly two orders of magnitude cheaper than Claude per draft.
Nothing about NVIDIA changes that; it adds a bench, not a foundation.

---

## What was verified, and what was not

Read first-hand: the skills repository and all 350 `SKILL.md` files; the licence
files of AI-Q, RAG, VSS, DALI, cuDF, cuOpt and DeepStream; the API Trial Terms
of Service PDF in full; the NIM FAQ; the forum threads on credits and rate
limits. The 81-model catalogue and the edge-block behaviour were measured here,
against this key.

Not read directly: `docs.nvidia.com`, `developer.nvidia.com` and
`build.nvidia.com` return 403 to automated fetches. The VSS GPU profile table,
the RAG support matrix and the AI Enterprise price all came through search
snippets — consistent across independent sources, but not eyeballed at source.

The ~40 RPM figure is user-reported and corroborated across many threads; what
*is* confirmed by an NVIDIA moderator is that no increase is available on that
tier.

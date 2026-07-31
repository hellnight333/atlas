# Atlas Roadmap

Phases are gated by **exit criteria**, not by dates. A phase is not done until its
criterion demonstrably passes.

---

## Phase 0 — Kernel + the vertical slice

> **Exit criterion:** an operator types a prompt in the web UI on Hetzner; a job enters the
> Postgres queue; the HP Z8 GPU worker leases it over Tailscale; ComfyUI runs a versioned
> recipe against FLUX; the resulting asset lands in the Library on the NAS with full
> lineage — and the whole thing survives a worker being killed mid-job.

This is the whole ballgame. If this thread works end to end, every later studio is a
plugin. If the kernel is wrong here, all six studios rot on top of it.

Deliberately included: exactly **one** studio, **one** provider, **one** recipe.
Deliberately excluded: agent loop, LLM routing, memory, benchmarks, any second studio.

## Phase 1 — Recipes, benchmarks, routing

> **Exit criterion:** the same prompt resolves to a different provider when the routing
> policy changes from `prefer_local` to `prefer_quality`, with no code change — and the
> benchmark harness has scored at least three recipes on a fixed evaluation set.

This is where "everything benchmarked" and "everything replaceable" stop being slogans.

## Phase 2 — Agent loop + LLM tier

> **Exit criterion:** "make a product shot of this, then a 5s video from it" completes from
> a single plain-language brief, with a plan shown for approval before execution, running
> against a local Qwen through LiteLLM and falling back to Claude on complexity.

## Phase 3 — Video Studio

> **Exit criterion:** text-to-video and image-to-video both run through the recipe system,
> local (Wan / LTX) and cloud (Seedance) selectable by policy alone.

## Phase 4 — Audio, Business, Research studios

Each is a plugin against a kernel that is now stable. If any of them requires a kernel
change, that is a signal the kernel was wrong — fix the kernel, don't special-case.

## Phase 5 — Coding Studio

Deliberately last. It is the highest-leverage studio but also the one where existing
tools (Claude Code, Codex CLI) are already excellent. Atlas should orchestrate them, not
replace them.

---

## Deferred to year 2

**Game Studio · App Studio.** Lowest ROI in the vision. AI-built games are a demo, not a
business. Revisit only when the six core studios are in daily use.

## Dissolved (not built as studios)

| Originally scoped as | Actually is |
|---|---|
| Podcast Studio | A recipe over TTS + Music |
| Automation Studio | The kernel itself |
| "Run YouTube channels" | A workflow over Video + Business |
| "Affiliate businesses" | A workflow over Business + Research |

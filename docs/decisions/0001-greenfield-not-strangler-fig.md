# ADR 0001 — Atlas is a true greenfield build

**Status:** Accepted · 2026-07-31

## Context

The Naml ops dashboard already implements a large fraction of what Atlas needs: an action
registry, an event bus, a plan→act agent loop, YAML skills, tiered memory, model routing,
an asset library and multi-user auth. Three paths were considered:

1. **Strangler-fig extraction** — new kernel, Naml becomes Atlas's first app, modules
   migrate one at a time.
2. **True greenfield** — build Atlas from zero, ignoring the Naml codebase.
3. **Refactor Naml in place** — rename and restructure the existing system.

## Decision

**True greenfield.**

The architect's recommendation was (1). The owner chose (2) with the trade-off stated
explicitly. This ADR records that the choice was deliberate, not accidental.

## Rationale for the choice

The Naml codebase carries structural properties Atlas must not inherit: a ~30k-line
monolithic module, server-rendered HTML from Python, and a deploy model with a 30-90s
outage window. Options (1) and (3) both keep that code alive inside Atlas's boundary,
where it exerts gravity on new design. A clean kernel with a hard studio/provider
boundary is only genuinely clean if nothing is grandfathered past it.

## Consequences

**Accepted cost:** every provider quirk, schema trap and operational failure mode
solved in Naml must be solved again in Atlas.

**Mitigation:** that knowledge is carried over as *documentation*, not code —
[`docs/LESSONS_FROM_NAML.md`](../LESSONS_FROM_NAML.md). This preserves the learning while
keeping the codebase genuinely greenfield. It is required reading before writing provider,
queue, schema or deploy code.

**Naml continues to run untouched.** It is not migrated, wrapped or deprecated by this
decision. Atlas does not depend on it and does not replace it on any fixed timeline.

## Revisit if

Phase 0 slips materially because kernel primitives that already exist in Naml are being
rebuilt slowly. In that case, reconsider (1) for the *remaining* modules only — the kernel
itself stays greenfield regardless.

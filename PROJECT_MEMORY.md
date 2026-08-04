# Project memory

Where Atlas is going, things it learned the expensive way, and the rules that
came out of them.

Not a changelog — the changelog says what changed. This says what to never do
again, and why, so the reasoning survives the people who were there.

---

## Long-term vision

**Recorded 2026-08-04. This is direction, not backlog.** Nothing below is
scheduled. It exists so that a decision made today does not quietly foreclose
it. Development continues milestone by milestone against the current roadmap.

### What Atlas is

Atlas is not a video generator. Atlas is an autonomous AI operating system for
building, operating, deploying and growing digital businesses.

**The operator states a goal. Atlas decides how to reach it.** They should never
have to choose the database, the framework, the cloud, the deployment target,
the infrastructure, the AI provider or the orchestration. They ask; Atlas
selects.

This is the same principle as `CLAUDE.md` §2 — the operator never picks a
ControlNet or a LoRA — carried all the way up. What Atlas hides at the recipe
level, it must also hide at the infrastructure level.

### The invariants

These are what make the destinations below reachable. Each one is cheap to hold
now and expensive to retrofit, which is the whole reason for writing them down
before they are needed.

| Invariant | What it forbids |
|---|---|
| Everything modular and reusable | A second orchestrator. Every factory reuses one kernel. |
| Content independent from rendering | Media fields on a source model. Source is `Series → Episode → Script → Scene`; every output is a Rendition. |
| Providers disposable | The kernel knowing which vendor did the work. |
| Capabilities never depend on vendors | A recipe named for a provider. Recipes declare `video.generate`, not "Seedance". |
| Workers stateless | Work that only one machine can resume. |
| Everything reproducible | A generated asset without provider, model, version, workflow, recipe, parameters, seed, prompts, LoRAs and workflow hash. |
| Irreversible actions need approval | Anything public, billable or destructive happening unattended, unless explicitly automated. |

### The factories

Destinations. All of them sit on the same kernel; none of them introduce
orchestration of their own.

- **Media** — one source model, many rendered outputs: video, shorts, podcasts,
  music, blogs, presentations, images, thumbnails. *(M013 built the first slice.)*
- **Website** — given a goal: design, implement, deploy, monitor, improve,
  redeploy.
- **Amazon** — keyword research, image generation, listing creation, A+ content,
  daily monitoring, competitor analysis, inventory analytics.
- **AI SaaS** — build and deploy complete products: image tools, PDF tools, SEO
  tools, marketing tools, automation, subscriptions.
- **Opportunity** — continuously find businesses that need work (no website,
  weak SEO, poor UX, unoptimised Amazon or Airbnb listings), prepare a
  personalised proposal, and after human approval, run outreach over email,
  WhatsApp and CRM. **No spam** — approval is the gate, not a formality.
- **Browser / Computer agent** — operate authenticated software the way a person
  does: Merchant Center, Meta Ads, Seller Central, Hostinger, Cloudflare,
  Stripe, WordPress, Shopify. Eventually configuring services itself once given
  credentials.
- **Deployment · SSH infrastructure · Business automation** — Atlas manages a
  fleet (workstation, GPU workers, Hetzner, cloud) and decides where each job
  runs: GPU rendering, deployment, crawling, browser automation, background work.
- **Multi-model orchestration** — planner, reasoner, coder, vision, search,
  image, video, speech. Each selected **by capability, never by vendor.** Atlas
  must never depend on a single model.

### How to use this

When a design choice appears, prefer the option that grows naturally toward the
above **without adding complexity today**. That last clause is doing real work:
`CLAUDE.md` §4 forbids speculative abstraction, and this section does not repeal
it. The test is not "does this support all eleven factories" — it is "does this
make them harder later?" Building the general case now is a violation; choosing
the specific case that generalises later is the point.

---

## Standing rules

These are not style preferences. Each one exists because breaking it took the
product down.

### SHIP-1 — Atlas exists to build businesses, not software

**Canonical text: [`SHIP_RULE.md`](SHIP_RULE.md).** It is short, it is the
highest-priority rule in the repo, and it overrides roadmap decisions whenever
priorities conflict. Read it rather than a summary of it.

The one line to carry: architecture exists to enable shipping, and architecture
is never the product. Milestones are ranked by revenue, then manual work
eliminated, then products shipped, then customers, then reach, and only then
architecture.

### UI-1 — Never allocate inside a Zustand selector

Select stable references only. Do every `filter`, `map`, `sort` or object build
inside `useMemo`, or wrap the selector in `useShallow`.

```js
// Wrong — a new array on every call
const jobs = useActivityStore((s) => s.jobs.filter(isActive))

// Right — stable reference, derived where deriving belongs
const allJobs = useActivityStore((s) => s.jobs)
const jobs = useMemo(() => allJobs.filter(isActive), [allJobs])
```

Enforced by `packages/kernel/tests/test_desktop_store_selectors.py`, which
scans the desktop source and fails with the file and line.

### UI-2 — Every error a user can see must also be recorded

If it reaches the screen, it reaches `logs/startup.log` and the diagnostics
system. No exceptions. A user must never be looking at an error that Atlas has
no record of, because then the only evidence lives on their screen and dies
when they close the window.

That means every error boundary — the root one, each route's `errorElement`,
and any added later — logs before it renders.

---

## Lessons learned

### UI rendering

#### React error #185, and the crash that had no trace

**Symptom.** The shell booted perfectly: PostgreSQL up, kernel healthy, health
check 200, setup state loaded, `rendering main application`. Then a blank dark
window. The startup log ended at that line with nothing after it.

**Why #185 happened.** `BackgroundTaskStrip` selected like this:

```js
const jobs = useActivityStore((state) => state.jobs.filter(...))
```

`.filter` returns a new array every call. A Zustand selector *is* the
`getSnapshot` for React's `useSyncExternalStore`, and React compares the value
it read during render against the one it reads at commit. Two different arrays,
every time — so React re-rendered to catch up, forever, until it gave up with
"Maximum update depth exceeded".

`BackgroundTaskStrip` is rendered by `DesktopShellLayout`, the root route
element. So it took down the entire application the instant the workspace
rendered, on every launch, for every user.

It is worth being precise about why this was hard: the code is *correct-looking*.
Filtering in a selector reads as good practice — narrow the subscription, render
less. It is only wrong because of what a selector **is**, and nothing about the
call site says so.

#### Why route errors bypassed the global error boundary

`RouterProvider` has an error boundary of its own, and it catches errors thrown
inside routes **before** they can propagate to any boundary above it. Atlas had
a `RootErrorBoundary` at the top of the tree that logged crashes and showed the
diagnostics screen — and it never fired, because the error never reached it.

What the user got instead was react-router's built-in fallback: a minified stack
and the words "💿 Hey developer 👋". Nothing was written to `startup.log`.

The consequence was worse than the bug. For a full day the evidence pointed at
startup — the shell log was flawless and stopped exactly where the UI took over
— so the investigation went to PostgreSQL, the kernel, ports, permissions and
Rosetta. The actual failure was three components deep in the render tree and had
been shouting on screen the entire time, in a form written for whoever wrote the
code rather than whoever was trying to use the product.

**The general shape:** a safety net that a framework can intercept is not a
safety net. Every boundary in the tree has to be accounted for, not just the
outermost one.

#### How these are prevented now

| | |
|---|---|
| Allocating selectors | `test_desktop_store_selectors.py` scans the source and fails with file and line. It caught a stray `git checkout` reverting the fix before a shipped build. |
| Route errors escaping | Every route has an `errorElement` that logs the error and stack, then shows the same diagnostics screen as any other failure. |
| Errors with no record | Rule UI-2. Root boundary, route boundary and shell failures all write to `logs/startup.log`. |
| Minified stacks | Package an **unminified** build (`vite build --minify false`, then `tauri build --config '{"build":{"beforeBuildCommand":""}}'`). `xl`/`bl` became `forceStoreRerender` ← `updateStoreInstance`, which names `useSyncExternalStore` and therefore Zustand — one grep from the answer. |

#### A day lost to a stale build

The same investigation was then repeated against a build in
`target/release/bundle/` that predated every fix. It looked identical, launched
identically, and faithfully reproduced bugs that had been fixed hours earlier.

`startup.log` now opens with the version, the build identity and **the full path
of the running binary**, so "which Atlas is this?" is answered before anyone
thinks to ask. Stale bundles in `target/` are worth deleting rather than
leaving.

**Verifying a UI fix means looking at the window.** Logs proved the tree mounted
and nothing threw; the window was still blank. "No crash" and "something is
visible" are different claims, and only a screenshot settles the second one.

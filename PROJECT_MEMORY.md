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

### Deployment

Learned building and proving M015 Phase A. See `docs/WEBSITE_FACTORY.md` for the
implementation and `infra/phase_a_proof.py` for the run these came from.

#### Provider independence is a set of decisions, not a stated intent

"Provider-independent" is a phrase every system claims and few survive, because
independence leaks through details nobody notices until the day of the move.
Four decisions carry it, and each one is a place it could have been lost:

| Decision | What it prevents |
|---|---|
| Atlas holds the **artifact** — files stored byte for byte, not a path | A build that only exists inside one provider |
| Atlas holds the **deployment state** — what is live is Atlas's row | An answer that depends on an account someone else can close |
| Rollback uses **Atlas's artifacts**, never the provider's history | Rollback silently becoming a provider feature |
| Changing host is **publish + promote** to another target | A "migration project" |

The test that makes it real: deploy a build to one target, deploy the *same
build* to another, and compare the bytes that landed. If that is not an ordinary
operation producing an identical artifact, the abstraction has already failed.

#### Rollback from Atlas's own artifact, even though it is slower

Promoting a version the provider still holds is faster. It is also a rollback
that depends on a retention policy Atlas does not control, and it fails **the day
the provider prunes an old deployment or is swapped** — which is exactly the day
someone needs it.

Republishing from the stored build is slower and always works. It has a second
benefit worth as much: the provider-independence claim is exercised **every time
anyone reverts**, rather than the first time somebody tries to move a customer.
A property tested only when it matters is a property nobody has tested.

Proven by deleting the previous version from the server before rolling back.

#### Testing against production infrastructure without touching it

The box ran 49 production containers behind a **single bind-mounted Caddyfile**.
Adding a vhost meant restarting the proxy in front of live businesses, and the
firewall allowed only 22/80/443.

Neither was done. Instead: a **separate web server container** with its own
config on a spare port, **bound to loopback and reached over an SSH tunnel** —
no proxy restart, no firewall rule, nothing shared with production.

**The general rule: prove a pipeline beside production, never through it.** The
cost of an isolated environment is minutes. The cost of restarting a proxy in
front of someone's revenue to demonstrate something is not bounded, and
"deployment tooling" is a category where the blast radius is the whole point.
A deployment adapter that edits a reverse proxy fronting other people's sites is
a deployment adapter with a blast radius.

#### Verify TLS properly or the check means nothing

The gate exists to inspect what a visitor is served. A gate that fetched over
`verify=False` would be inspecting a connection it had not validated — theatre,
and worse than no gate because it reads as assurance.

Internal certificates are fine. **Skipping verification is not.** Fetch the CA
root, hand it to the client, and let the check be real. It cost one command.

Related: the gate rejected the test suite's own preview URLs on its first run
because they were `http://`. That was correct — a customer site over plain HTTP
is one of the defects being sold against. Exempting it would have made the tests
pass and weakened the gate; the tests changed instead. **When a guard fails on
your own work, the first question is whether the guard is right.**

#### Deployment architecture: publish, then promote

Designing against two hosts at once is what produced the interface. An interface
phrased as *"copy these files to this path"* encodes a filesystem and a
Pages-style host cannot satisfy it; one phrased as *"upload and give me a
deployment id"* encodes the opposite and a box cannot. **Publish a versioned
artifact, then promote it** is what they share.

It buys more than portability. Promotion being separate from publication means an
artifact can be **reachable but not yet live**, which is the only thing that makes
a pre-promotion quality gate possible — the gate inspects what visitors will get,
on the real host, over real TLS, before anyone is served it.

**One adapter cannot validate an interface.** Write the second one, even thin.
An interface validated in prose is validated by nobody.

#### File-level correctness and a working site are different claims

The first live run deployed, promoted and rolled back **perfectly**: the `current`
symlink pointed exactly where it should at every step. Every HTTP check failed,
because the web server was serving the directory that *holds* the symlink rather
than the symlink itself.

Nothing in the deployment code was wrong. The lesson is the same one the UI
section records in different words — *verifying a fix means looking at the
result* — and it is why every promotion is confirmed by fetching the live URL
rather than by trusting a tool's exit code.

Two related configuration traps, both of which look like the code failing:

- **`auto_https off` disables certificate provisioning entirely.** The site then
  serves a TLS handshake with no certificate to offer. `local_certs` is the
  option that means "use an internal CA".
- **A client connecting to an IP sends no SNI**, so a name-based server has no
  site to match and aborts the handshake. `default_sni` names the site to assume.

### Publishing on someone else's behalf

Learned building M015 Phase B, where Atlas started writing pages that go out
under a customer's name rather than its own.

#### Publishing *as* a business is worse than making a claim *about* one

M014's rule is that Atlas may not assert something about a business it cannot
substantiate. Phase B crossed a line that needed a stronger rule: an invented
opening time on a site Atlas built is wrong **in the customer's own voice, on
their own domain**, and *they* absorb the consequence when somebody arrives at
8pm to a closed shop.

Two mechanisms, and it is worth being clear about which one actually works:

**Facts carry a source, and there is no source meaning "a model wrote it."** The
enum has `OPERATOR`, `CUSTOMER`, `BUSINESS_RECORD`, `OBSERVED` and no
`GENERATED`. This does not stop a determined caller attributing an invention to
the operator, and is not meant to — it makes every claim **attributable**, so a
wrong one leads back to its source instead of dissolving into the output.

**Absent facts are absent from the page.** No placeholder, no "Call us today!",
no filler where a phone number should be. *This* is the mechanism that does the
work, because the tempting failure is not inventing an address — nobody sets out
to do that. It is padding a thin page with confident copy that asserts nothing
anyone supplied, one sentence at a time, until the page reads like a claim.

**The general shape: separate what may be written from what must be supplied,
and make them different types.** Prose and Fact cannot be confused at a call
site, so a paragraph cannot become the opening hours by being written
confidently.

#### A quality gate you cannot pad your way past

A site carrying one fact fails Atlas's own thin-content check and is refused.
That is correct: a twenty-character page will not rank, which is the thing being
sold. The remedy is more content from the customer — **a conversation, not a code
change.**

The rule worth keeping: when your own output fails your own gate, the options are
to improve the output or to get more input. Lowering the gate is a third option
that always works and always costs more than it saves.

Related, from the same milestone: the deploy gate rejected the test suite's own
preview URLs because they were `http://`. Correct — plain HTTP is one of the
defects being sold against. Exempting it would have made the tests pass and
weakened the gate; the tests changed instead. **When a guard fails on your own
work, the first question is whether the guard is right.**

#### `</script>` is not escaped by JSON encoding

Found by a test asserting content cannot inject markup, and it was a real hole
rather than a hypothetical: a business name containing `</script>` closes a
JSON-LD block, and everything after it parses as markup. Cross-site scripting on
the customer's own domain, published by Atlas, in their name.

`html.escape` is **not** the fix. The contents of a `<script>` element are not
parsed as HTML, so entities arrive literally and break the JSON instead. Escape
`<`, `>` and `&` as JSON unicode escapes (`\u003c`) — valid JSON, and the
sequence becomes unrepresentable.

The general rule: **JSON inside a `<script>` tag is not safe because it is valid
JSON.** Two escaping contexts are nested, and satisfying the inner one says
nothing about the outer.

#### Determinism is a product property, not a build detail

No build timestamp, no generated ids, no unordered iteration in the output. That
is what lets "this site was rebuilt correctly" be settled by comparing
fingerprints instead of by a person looking at two pages — and it is the entire
basis of being able to rebuild a customer's site from the record years later.

A footer reading "generated on 4 August" would have cost nothing to add and made
every rebuild unverifiable.

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

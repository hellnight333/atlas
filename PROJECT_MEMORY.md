# Project memory

Things Atlas learned the expensive way, and the rules that came out of them.

Not a changelog — the changelog says what changed. This says what to never do
again, and why, so the reasoning survives the people who were there.

---

## Standing rules

These are not style preferences. Each one exists because breaking it took the
product down.

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

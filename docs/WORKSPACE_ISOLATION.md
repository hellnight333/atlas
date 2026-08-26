# Workspace isolation

## The claim that was not true

`GitWorkspace` was introduced as "an isolated Git worktree per mission, so an
agent never edits your checkout", and for the operator's *files* that held. For
the *repository* it did not.

`git worktree add` runs **inside the origin repository** and writes there:

- a new ref under `.git/refs/heads/`
- an entry under `.git/worktrees/`
- every object the mission commits, into the origin's object store

On this deployment the origin is `--repository /opt/qevik/atlas` — the
production checkout. So a mission modified production simply by running, and a
failed one left its branch and objects behind in the thing Qevik runs from.

This is easy to miss because the obvious checks all pass. Measured on the old
path against a clean repository:

| fingerprint field | before | after a mission |
|---|---|---|
| `HEAD` | `ea03679…` | **unchanged** |
| current branch | `main` | **unchanged** |
| `git status --porcelain` | empty | **unchanged** |
| refs | 1 | **2** — gained `refs/heads/mission/old` |
| `.git/worktrees` | `[]` | **`['old']`** |
| loose objects | 8 | **14** |

A test asserting `HEAD` and `status` would have passed on the broken version.
`infra/verify_scratch_isolation.py` asserts all six, and the negative control in
this table is re-run there.

## The shape now

```
/opt/qevik/atlas                production. Read once, never written.
      │  git clone --no-hardlinks
      ▼
<scratch>/<mission-id>/repo     the mission's own repository
      │  git worktree add
      ▼
<worktrees>/mission/<id>        where the agent works
      │
      ▼  tests, review, commit — all inside the clone
      │
      ▼  ── explicit human promotion ──▶ production
```

`--no-hardlinks` is a physical copy. `--shared` would leave the mission's
objects reachable only through the origin, which is the isolation failure with
extra steps. Hardlinks are *probably* safe, since git never rewrites an object
in place — and "probably safe" is the wrong standard for the repository the
business runs from. At 21 MB the copy costs about a second.

`GitWorkspace` is **unchanged and unaware**. It is handed a repository path and
behaves exactly as it did. This adds a step to the pipeline, not a second
pipeline.

## Commits

Unchanged: own branch, never `main`, no force, no rewrite, no push path at all,
and the secret scan still runs before every commit. What changed is only *which
repository the branch lives in* — the mission's clone.

That means a commit sha from a mission exists **only** in that clone, so the
mission now records where:

| field | example |
|---|---|
| `workspace` | `/var/lib/qevik/scratch/mission-c6ab098e7fb8/repo` |
| `origin` | `/opt/qevik/atlas` |
| `origin_kind` | `qevik` \| `external` \| `empty` |

Without these, a report saying "committed `abc1234`" names a sha nothing can
find, and the commit becomes a rumour.

## The clone is never discarded, and the first version got this wrong

A failed mission's worktree was always kept — the directory, branch and diff are
the only record of what the agent did. The first version of this change applied
the same instinct to the clone and discarded it on **success**, which destroyed
the commit.

That is the whole difference the clone makes. The mission's branch used to live
in the origin repository and survived cleanup on its own. It now exists *only*
in the clone, so deleting the clone after a successful mission throws away the
exact artefact the promotion boundary exists to hand to a person. It was caught
by `test_the_commit_is_real_and_on_its_own_branch`, which went looking for the
commit and could not find it.

So clones accumulate, at roughly the size of the origin each (12 MB here).
Pruning them needs a record of what has already been promoted, which does not
exist yet. Keeping a deliverable is the right way to be wrong in the meantime,
and the worker logs where each mission's commits are.

`Scratch.discard()` still exists for the caller that wants it, and refuses to
delete a path equal to its own origin. The whole purpose of the clone is that
the origin survives; deleting the source would invert it.

## Origin is a property of the mission, not of the worker

`--repository` is gone. It set one repository for the whole process, so every
mission on a worker was the same kind of mission — the CUSTOMER case could not be
exercised at all, and one worker could not serve both self-improvement and
unattended work. Passing it now makes the worker **refuse to start** rather than
silently doing something else.

A mission declares `origin_name`. That is a **key**, never a path:

    mission.origin_name = "acme-web"     <- meaningless on its own
    registry.resolve("acme-web")         <- code decides what that is, if anything

`mission/origins.py` is the only thing that turns a name into a location. A
planner emitting `"../../etc"`, `"/opt/qevik/atlas"` or `"qevik "` gets
`UnknownOrigin` and the mission is **BLOCKED** — never a fall back to the
default, because the default is Qevik. There is no path in the mission at all,
so there is nothing to traverse.

| origin | source | kind | who decides |
|---|---|---|---|
| `qevik` | derived from `__file__` | QEVIK | a person, every time |
| `none` | — | EMPTY | nobody; may run unattended |
| *configured* | `--origin NAME=PATH` | CUSTOMER | policy, on the plan |

**The registration check that matters:** a CUSTOMER entry whose path resolves to
Qevik's own repository is refused **at start-up**. Without it, "register the
customer `totally-not-qevik` pointing at /opt/qevik/atlas" routes
self-modification through the customer path, where policy does not ask for
approval — a bypass by configuration, silently. Every refusal happens at
start-up, in front of whoever configured it, rather than blocking one mission at
three in the morning.

## Self-modification is decided by the origin, not the workspace

**A clone of Qevik is still Qevik.** The work is intended to become the running
system, and where it is staged does not change what it is. `classify()` answers
by comparing the origin against `running_from()` — derived from `__file__`, so
there is no configuration setting that turns the self-modification rule off.

| origin | classification | path |
|---|---|---|
| the repository this code runs from | `QEVIK` | self-modification, human approval |
| any other repository | `EXTERNAL` | normal execution path |
| none | `EMPTY` | fresh repo; nothing at risk |

`EMPTY` is the new case and the reason recurring work can now run unattended:
work with no source to start from still needs somewhere to write, and handing it
a clone of Qevik because that is what was lying around is how unrelated work
gets classified as self-modification.

## Two guards, at different times, on different evidence

**`policy.decide`** runs when a plan is attached, on what the planner
*declared*. Unchanged, still deny-by-default, `modifies_qevik_itself` still
defaults to `True`.

**`policy.refuse_unapproved_self_modification`** runs in the worker, on what the
origin *actually is*. The two can disagree — a declaration is a field, an origin
is a fact — and if a plan declaring `modifies_qevik_itself=False` reaches the
queue and the worker then hands it a clone of Qevik, this blocks the mission
before any agent runs.

Approval is detected **structurally**: the only route out of `AWAITING_APPROVAL`
is a person acting, so a mission that was ever in that state was approved by
one. Matching the note text `"approved by operator"` would pass for any mission
whose note happened to contain those words.

## Another way production was being written to

`pass_once` resolved its report directory as `report_root or repository`. With
`--reports` omitted, reports were written **into the origin repository** under
`docs/qevik-docs/autonomous/reports/`. Production passes `--reports`, so it was
never hit there — but the default was a landmine. `report_root` is now resolved
once in `main()` and is never the repository.

## Cost, measured

On `qevik-core-01`: `.git` is 12 MB and a clone takes **0.146 s** as the `qevik`
user. Per mission, that is not a consideration.

## A latent break this uncovered

`/opt/qevik/atlas` on the server is owned by **uid 501, group staff** — the
Mac's uid, preserved by `rsync -a`. Git refuses such a repository with "detected
dubious ownership" for every user on the box, so `git worktree add` could never
have run there. The production worker has in fact **never executed a mission**;
there is no `missions.jsonl` on the server at all, and the `claiming: COMPLETE`
lines in its journal are the claims-backend status, not a mission.

Fixed as **read-trust, not a write grant**: `git config --system --add
safe.directory /opt/qevik/atlas`. Cloning needs to read the origin and nothing
more. A `chown` would have handed write access to every process running as
`qevik` in order to fix a read.

The underlying cause is the deploy method; `rsync -a` should carry
`--no-owner --no-group` here.

## Cleaning the residue

`infra/prune_mission_branches.py`. Dry run by default; `--apply` performs what
it just listed.

The rule is inverted from the usual cleanup: **delete nothing unless it can be
proven stale.** Proof means the branch names a mission that appears in none of
the timelines it was checked against and in no report. Anything else — a live
mission, a mission a report cites, a branch that is not a mission branch, or a
timeline that could not be read — is protected, with the reason printed.

A *missing* timeline protects everything, deliberately. An *existing but empty*
one is evidence: it says "this deployment records missions here, and there are
none". A missing one says "you may be looking in the wrong place", and the
optimistic reading of that difference deletes somebody's work.

A worktree registered under `/tmp` is reported as corroboration — "probably a
harness run" — and never as a deletion rule. Guessing from a path is how a
cleanup removes something that mattered.

## Residue from before the change

`/opt/qevik/atlas` currently carries **13 `mission/*` branches and 8 stale
`.git/worktrees` entries**, dated up to 2026-08-26 08:10 — left by harness runs
executed on the server against the pre-change code, plus some carried over from
the Mac by `rsync -a`. They are exactly the contamination this change prevents,
and they are the evidence that it was real.

Nothing removes them automatically. Deleting refs is destructive and these are
not in anybody's way — the worker no longer touches that repository at all. Left
for an explicit decision; the cleanup, when somebody wants it, is:

```
git -C /opt/qevik/atlas worktree prune
git -C /opt/qevik/atlas branch -D $(git -C /opt/qevik/atlas branch --list 'mission/*')
```

Verified after the change: the two-worker run's commit `54a0186b` is **absent**
from `/opt/qevik/atlas`, and the newest `mission/*` branch there predates it by
four hours.

**Inspected 2026-08-26 — 0 provably stale, 13 protected.** The control plane has
no `missions.jsonl` at all, so there is nothing to check the branches against and
the tool correctly refuses to delete any of them. Three carry corroborating
evidence of harness origin (worktrees registered under `/tmp/qevik-e2e-*`), which
is reported and deliberately does not make them deletable. Once the worker has
actually recorded missions, the check becomes meaningful and the cleanup can run.

## Three independent levels

The boundary does not rest on the code being right:

1. **Code** — the worker clones and never writes to the origin.
2. **systemd** — `ProtectSystem=strict` with `ReadWritePaths=/var/lib/qevik`,
   so the kernel refuses the write even if the code regresses. The unit said
   `ProtectSystem=full`, and removing `/opt/qevik/atlas` from `ReadWritePaths`
   under `full` **did nothing**: `full` only covers `/usr`, `/boot` and `/etc`,
   and leaves `/opt` writable. Measured rather than assumed — a write probe into
   `/opt/qevik/atlas` succeeded under `full` and returns "Read-only file system"
   under `strict`. Both directions are checked: production refuses the write,
   `/var/lib/qevik/scratch` accepts it.
3. **Filesystem** — `/opt/qevik/atlas` is mode 755 owned by uid 501, and a
   write probe as `qevik` returns `Permission denied`.

## The console surface

`GET /api/missions/origins` lists what a mission may be pointed at — **names and
kinds, no filesystem paths**. A path is not something an operator picks from,
and putting one in an HTTP response makes it a free map of the deployment for
anybody who reaches the console.

`QEVIK_ORIGINS` (`name=/path,other=/path`) is read by the control plane **and**
the worker, so one declaration serves both. A name given in both the environment
and `--origin` is refused rather than one silently winning.

Validated in three places, deliberately: the API refuses an unknown key with 400
so a typo is answered by the surface that made it; the worker refuses it again at
dispatch, because that is the check that protects execution; and the registry
refuses a customer entry pointing at Qevik at start-up.

The approval screen offers radio options rather than a `<select>` — each needs a
sentence explaining what it means, and a native select on a phone hides all of
that behind a wheel showing one line at a time, when the whole point is that
somebody reads the difference before approving. Qevik is preselected and marked
amber before it is chosen. Verified at 390×844: `doc.scrollWidth 390`, no
horizontal overflow.

## What the origin model uncovered in dispatch

Two things next to it turned out to be built and not connected — a different
problem from missing, and one that looks fine until you check.

**The scheduler could not see any credential requirement.** `demands_from` was
called with no `agent_for`, so every mission got `placement=EITHER` and an empty
`missing_credentials`. A mission whose agent needed a model credential nobody had
configured was dispatched, reported as running, and failed at the provider —
exactly what `usable_credentials`'s own docstring warns about:

    no agent_for (how it ran)      dispatchable=['m-1']  missing=()
    with agent_for, no creds       dispatchable=[]       missing=('qwen','anthropic','openai')
    with agent_for, qwen present   dispatchable=['m-1']  missing=()

`Mission.agent_id` is now recorded when the plan is attached, from the same value
`policy.decide` was given, so the blast radius a person approved and the one read
at dispatch are the same value. The worker prefers it and falls back to its own
configured agent only for a mission whose plan named nobody. The control plane's
schedule view uses it too — it was showing missions as dispatchable that the
worker would hold.

**The budget was consulted after the work, never before it.**
`budgets.assess()` exists, in its own words, so "the scheduler can decline to
start work it cannot finish", and nothing called it. `queued()` accepted
`remaining_units` and `pass_once` never passed one. `tenant_headroom()` now asks
before dispatch; `None` stays `None` all the way to the scheduler, because an
unmetered tenant is not one with an infinite balance — it is one nobody measured.

`usable_for()` moved into `credentials/service.py` so the worker and the API ask
one implementation. Two definitions of "usable" would disagree on the day one of
them mattered.

## Three refusals, together, before any agent runs

Each asks about something that could have changed between the moment a person
approved the plan and the moment a worker picked it up.

| what changed | refusal |
|---|---|
| the repository it will actually touch | `policy.refuse_unapproved_self_modification` |
| the agent that will actually carry it out | `policy.refuse_agent_substitution` |
| whether every allowance can still carry it | `refuse_over_budget`, via `budgets.assess` |

The agent one was a real hole: a mission approved as `self-check` work
(deterministic, no network, no credentials) picked up by a worker started with
`--agent llm` was carried out by a model. The approval was for one thing and the
execution was another, which makes the approval record *wrong* rather than
merely stale. Substituting a more capable agent silently widens the blast
radius; a less capable one silently produces work nobody can trust.

The budget one is the last word: the scheduler's rule runs earlier on tenant
headroom from a fold that may be seconds old, and this asks the ledger itself,
across tenant, mission and agent, with the actual estimate. An **unpriced** plan
is not refused here — `policy.decide` already required a person for it, and
refusing again on a cost nobody stated would wall off every unestimated mission
for ever. Nothing turns the absence into a number.

`infra/verify_no_fallback.py` attempts each substitution against **real worker
processes**, each with a paired positive control so a refusal that fires for an
unrelated reason shows up as both halves failing rather than as a pass.

## Files

| Path | What |
|---|---|
| `packages/kernel/atlas_kernel/mission/scratch.py` | the clone, the classifier, the fingerprint |
| `packages/kernel/tests/test_scratch.py` | 22 tests |
| `infra/verify_scratch_isolation.py` | 28 checks, real repo, real mission, with the negative control |
| `infra/verify_self_improvement.py` | production fingerprinted across a real self-modification mission |
| `packages/kernel/atlas_kernel/mission/policy.py` | `refuse_unapproved_self_modification` |
| `infra/mission_worker.py` | `--scratch`, `--origin NAME=PATH`, dispatch wiring |
| `packages/kernel/atlas_kernel/mission/origins.py` | the allow-list |
| `packages/kernel/tests/test_origins.py` | 31 tests, cross-origin confusion |
| `packages/kernel/tests/test_worker_dispatch.py` | 14 tests, the three blanks |
| `infra/prune_mission_branches.py` | provable cleanup, dry run by default |

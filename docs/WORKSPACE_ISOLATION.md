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

## Files

| Path | What |
|---|---|
| `packages/kernel/atlas_kernel/mission/scratch.py` | the clone, the classifier, the fingerprint |
| `packages/kernel/tests/test_scratch.py` | 22 tests |
| `infra/verify_scratch_isolation.py` | 28 checks, real repo, real mission, with the negative control |
| `infra/verify_self_improvement.py` | production fingerprinted across a real self-modification mission |
| `packages/kernel/atlas_kernel/mission/policy.py` | `refuse_unapproved_self_modification` |
| `infra/mission_worker.py` | `--scratch`, `--repository none` |

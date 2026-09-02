# ADR-0010 The commit that passed review is the only source of what deploys

## Status

**Accepted for Step 1 only** — owner's approval, 2026-09-02, of the staged
Option (a) recommended in this session's analysis. Step 2 (host-side immutable
install: single-file transfer, staged extract, rename-swap, release directories)
is **a separate architecture decision** that is not taken here and must not be
started until Step 1 is deployed and observed. Nothing in this document
approves release directories, root symlink switching, or any change to the
production host layout.

Every claim below is against `main` at `3fb666b` and names the file and line it
was read from. `infra/deploy_control.sh` last changed at `7d755b5`.

## Context

The development loop lands reviewed work on `main` and, for a task that
declares `requires_deploy`, runs `./infra/deploy_control.sh`
(`infra/devloop/gates.py:331`). The script copies **the working tree**:
`ROOT` is derived from `$0` (`deploy_control.sh:21`) and the tree is read at
five points — the kernel rsync (`:130`), the console rsync (`:134`), the infra
rsync (`:147`), the worker fingerprint (`:193`) and the unit glob (`:200`).
The only guards are "branch is `main`" (`:107-112`) and "porcelain is empty"
(`:113-118`), both evaluated once, before any copy.

The driver discards the commit it landed: `_ship` logs `head_sha()[:12]`
(`driver.py:515`), runs the full suite on the tree (`:521`) with no check that
HEAD is still that commit, and calls the deploy gate with nothing but a `cwd`
(`:530`). The lease is renewed only at `driver.py:301` and `:461` — never
inside `_ship` — so the 90-minute lease (`queue.py:50`) is spent from the
last renewal before the suite: a ship that takes the suite (≈ 11 min) plus a
script on a bad link (≈ 165 s of retries per remote step, a dozen steps,
≈ 45 min worst case) can leave a task nearly out of lease while a deploy is
still writing. There is no repository lock; a second `driver.py run`, a
person, or Codex can `git checkout` in the same tree while a copy is in
flight. And when a post-landing gate cannot be measured, `_infra` requeues
the task (`driver.py:532`, `:553`), but `_ship` has already deleted the
branch (`:514`), so the next run rebuilds already-landed work from scratch.

So today "the deploy shipped what was tested" is a property of nobody touching
the tree for about fifteen minutes, and it is unmeasured. This was the reviewer's
last outstanding finding against the deploy-only line (`b383573`,
t-8214147cda91), and it is correct.

The host holds no record of what it runs: `/opt/qevik/atlas/.git` is at
`ce4ffaa` (2026-08-17, 181 commits behind), there is no marker, and
`infra/deploy_public.sh` is on `main` but absent from the host — the deployed
commit is not recoverable from the host.

## Options considered

**(b) expected-SHA verification at the script boundary** — the driver passes
the landed sha, the script checks `HEAD == sha` before copying. About ten
lines. Rejected as the mechanism: it closes one window (a commit to `main`
during the suite) and leaves the copy window open, because the tree is read at
five places over seconds-to-minutes and a check is a check at one instant.
It is detect-only, a checkout-and-return that fits inside the window is
invisible to it, and it has no restore path for the console or the units.

**(a) immutable artifact deployment** — the payload is derived from the git
object store for the landed commit, so no state of the working tree can change
what is copied. Correct by construction. Its full form (host-side staged
extract and rename-swap) is a production change on a host with no staging
twin and several silent breakers (below), so it is staged.

**Decision: (a), in two steps.** Step 1 changes what the script *reads* and
nothing about how the host is *laid out*. The one idea from (b) that survives
— capture the landed sha and refuse to proceed if the tree drifts from it — is
kept as a driver-side precondition, because neither option makes the test
suite about the commit unless the driver asserts it.

## Decision — Step 1 (this ADR's scope)

The exact immutable git commit `S` that passed gates and review is the sole
source of deployment payload. Deployment never reads the mutable working tree
for deployed content.

1. **`S` is captured** by the driver immediately after the squash commit and
   before the full suite. The landing sequence checks the exit codes it
   currently ignores (`checkout main` `:502`, `commit` `:508`): a failed
   checkout would make `head_sha()` the branch tip.
2. **Repository state is verified before and after the full suite**: HEAD is
   `S`, the tree is clean, and `S` is an ancestor of `main`. Any mismatch is
   CONTESTED, never a deploy. The lease is renewed before the suite and before
   the deploy.
3. **The payload is built from `S` alone**: `git archive S -- <shipped
   prefixes>` extracted to a private temporary directory, verified against the
   commit's own tree (`git ls-tree -r S`, blob id per file, same count), and
   every shipped read — the kernel, the console, the infra tree, the worker
   fingerprint, the unit files, the kernel-presence check — is taken from that
   export. The in-place host layout (`/opt/qevik/atlas`, `/srv/qevik-control`,
   `/etc/systemd/system`) and the transport (`rsync_` over `ssh_`) are
   unchanged. Files the repository ignores no longer ship; today the only such
   files are `infra/.DS_Store` and PyInstaller output under
   `infra/packaging/`, which nothing on the host references.
4. **`S` is passed explicitly** to the script as the environment variable
   `QEVIK_DEPLOY_SHA` (never `$1`, which is the SSH target, `:19`). The script
   refuses without it, refuses a sha that is not a commit, and refuses one
   that is not an ancestor of `main`. After the copies (trees and units), the
   bytes on the host are compared with one per-file sha256 manifest computed
   from the export; a check that cannot run is a refusal, not a pass; the
   fingerprint the workers report is taken from the export's
   `infra/mission_worker.py`. The script's exit codes are a contract the
   driver and a person can read: **0** installed and verified (or rehearsed);
   **1** failed and rolled back (or failed before any write); **2** refused
   before any host contact (sha, tree, arguments, seams); **3** the export did
   not match `S`; **4** rollback incomplete; **5** rehearse found the host
   not ready. The driver never learns the sha from anywhere but its own
   record, and the child process it starts sees no `QEVIK_*` variable from
   the operator's shell except `QEVIK_DEPLOY_SHA`.
   The host targets (`/opt/qevik/atlas`, `/srv/qevik-control`,
   `/etc/systemd/system`, `/opt/qevik/atlas.env`, the health URL, the
   rollback directory) can be redirected for tests by `QEVIK_REMOTE_APP`,
   `QEVIK_CONSOLE_DIR`, `QEVIK_UNIT_DIR`, `QEVIK_ENV_FILE`,
   `QEVIK_HEALTH_URL`, `QEVIK_ROLLBACK_DIR` — only all six together and only
   under `QEVIK_TEST_HOST=1`; any of them set otherwise is a refusal, and
   every run prints the targets it is about to use.
5. **Provenance is durable**: `/opt/qevik/atlas/DEPLOYED_SHA` records the
   full sha, the UTC timestamp and the manifest digest, written **when the
   content is installed and verified on disk** — after the last file (the
   unit files, which today land after the control restart; that order is a
   non-goal and stays) has been copied and the manifest check has passed,
   and before the workers are restarted — and restored or rewritten by every
   rollback path so it always describes what is on disk. From the first live
   write until that point the marker says `state=installing` with the
   attempted and the previous sha, so a script killed mid-copy leaves a
   marker that admits it; the only state that means "the host holds this
   sha" is `state=installed`. The driver records "verified" separately, in
   the task's transitions, and reads the marker back before it lets
   production verification say anything about `S`; when a post-landing gate
   cannot be measured, the task is BLOCKED with `S` and the marker path in
   its reason — never requeued for a rebuild.
6. **`--rehearse`** constructs the export, verifies it against `S`, runs every
   transfer as a dry run (`rsync -n -i`) against the real host, reads the
   host's provenance and tool availability, and writes nothing — no rollback
   copy, no schema, no chown, no restart. It exits zero only if the payload
   could be constructed, every transfer could be planned, and the host's
   `sha256sum --check` works on a known input (exit 5 otherwise, since a real
   deploy would refuse at the host check).
7. **Rollback hygiene**: a failed rollback copy is a refusal, not `echo kept`
   (`:125`); `rm -rf` of a live target is guarded on the rollback copy's
   presence (`:181`, `:228-229`); the console and the installed units are
   saved and restored alongside the kernel and infra; a rollback that could
   not restore a target says so — `ROLLBACK INCOMPLETE`, distinct exit code,
   marker updated to say what is on disk — and never reports success. After
   a restore the services are restarted the way the deploy restarts them
   (control and api under `ssh_`, workers once with `reset-failed`), and the
   restored bytes are measured with the same manifest check before the
   marker is restored. The unguarded `REPORTED="$(ssh_ …)"` under `set -e`
   (`:220`) is guarded.
8. **Host layout and unit assumptions are preserved.** No release directories,
   no symlinked root, no host-side atomic install, no change to
   `WorkingDirectory`, `PYTHONPATH`, `.venv`, `atlas.env`, restart order, or
   which units are shipped.
9. **Objective tests** prove each invariant through controlled negative cases
   (the list is in the task plan below).
10. **First real deployment** happens only after a clean build, objective
    gates, a clean blind review, DONE, and a successful `--rehearse` against
    the real host — and it is **human-watched, on a trivial low-risk reviewed
    commit**, never under an unattended `driver.py run`.

### Non-goals (parked, not implemented here)

Each of these was found in the analysis and is real; none is Step 1. Each is
a separate decision or task, to be raised rather than folded in.

- **Restart order** — `qevik-api`/`qevik-control` restart at `:164`, before
  the units are installed at `:200-204`; a changed api/control unit takes
  effect at a later restart. Behaviour change, not layout: separate task.
- **Timers unshipped** — the unit glob is `qevik-*.service`; `qevik-backup.timer`
  and `qevik-market-scan.timer` on `main` are never installed.
- **The script itself runs from the tree** (`gates.py:331`, `ROOT` from `$0`).
  Materialising it from `S` needs a `ROOT=` override; deferred.
- **No dependency install step** — a `pyproject`/lock change ships and fails
  at import on the host (Python 3.14.4 vs 3.13.7 here). Pre-existing.
- **The unshipped-runtime guard** (`:72-98`) reads the tree. It becomes a
  range check `DEPLOYED..S` once the marker exists; left as-is in Step 1.
- **`gates.in_production`** is a fifth hard-coded consumer of the in-place
  layout (`gates.py:354-356`); what it runs and how it decides are unchanged
  (the provenance read may share its ssh argv helper).
- **The deploy-only task path** (`tasks.deploy_only`, the b383573 line) is
  not part of this ADR. It may be re-raised once Step 1 has landed, with the
  TOCTOU finding closed by construction.
- **A byte mismatch is detected after the control restart**, because the
  manifest check runs after the last copy and the unit install, which today
  follow `:164`; and **the marker is `installing` for the whole copy
  window** — an in-place install has no earlier point at which "installed"
  would be true. Both are what Step 2's staged extract and rename-swap
  remove; Step 1 makes them visible instead of invisible.
- **Rollback restarts `qevik-api`** as the deploy does (`:164`), so a
  rollback carries the same restart as a deploy. Pre-existing; unchanged.
- **Step 2** — single-file transfer, digest on host, staged extract, rename
  swap of the three leaf targets, releases keyed by sha. Decided later, only
  after Step 1 is deployed and observed.

## Qevik-specific constraints the implementation must respect

- **Never a symlinked or relocated root.** `mission/scratch.py:109-113`
  resolves the kernel's own path and walks parents for `.git`;
  `origins.py:143-151` registers the built-in `qevik` origin only when that
  finds one. All nine units hardcode `/opt/qevik/atlas` for
  `WorkingDirectory`, `PYTHONPATH` and the interpreter. (Step 2 concern; Step
  1 does not move anything.)
- **`ssh_` today retries any non-zero exit twelve times** (`:44-52`), which
  makes every deterministic remote failure (a missing file, a failed check)
  cost ≈ 165 s before it is reported, and makes a fail-closed host check
  slow by construction. Step 1 changes `ssh_` to retry only exit 255 — ssh's
  own code for a connection-level failure — with the same counts and sleeps,
  and gives the two polls the patience they used to borrow from that retry
  (health 60 × 2 s, worker fingerprint 60 × 3 s, both explicit in the
  script). `rsync_` is unchanged. Remote steps stay idempotent; the
  single-attempt worker restart stays outside `ssh_` as today (`:212-216`).
- **Ownership is settled by unit sandboxing**, not chown: `qevik-api` has
  `ReadWritePaths=/opt/qevik`; `qevik-control` and the workers exclude
  `/opt/qevik/atlas` on purpose. `git archive` files are uid 0 on extraction;
  the existing chown of the kernel (`:164`) and `mission_worker.py` (`:211`)
  stays.
- **The host has no staging twin.** The first execution of any changed path
  is production. Hence `--rehearse`, and the human-watched first deploy.
- **The manifest digest is per-file sha256 over the extracted export**, never
  a digest of a `.tar.gz`, whose bytes depend on the git/zlib build.
- **`sha256sum` on the host is uutils 0.8.0; on the Mac `/sbin/sha256sum`
  exists too, so a test cannot prove the tool-absent path by leaving it off
  `PATH`** — the harness shims it to exit 127. The host-side check must fail
  closed if the tool or a flag is missing, and `--rehearse` proves the
  host-side check command works on a known input before a real deploy relies
  on it.
- **No secrets.** `DATABASE_URL` lives in `/opt/qevik/atlas.env` and is never
  printed, logged, or written into a marker or manifest.
- **The gate timeout must exceed the script's own retry budget** (`gates.py:324`
  gives 900 s; the script can legitimately spend more on a bad link). Step 1
  gives the deploy gate 3600 s — above the script's own worst case of twelve
  retries on every remote step plus both polls' full patience (≈ 50 min),
  and inside the lease renewed just before the call — kills the script's whole process group on
  timeout (today the kill orphans `rsync`/`ssh` still writing to the host),
  and reports a timeout as an unmeasured gate, never as a failed deploy.

## Task plan (dependency-ordered; each is one bounded devloop task)

The driver's size gate (`gates.py:112-113`: 14 files / 800 non-test lines,
CONTESTED before review) is why Step 1 is three tasks rather than one. Each is
a coherent capability with its own invariant and its own negative tests; none
is a micro-task. They are enqueued one at a time, each after its predecessor
has landed, so a contested predecessor never leaves a successor building on
the wrong script.

| # | Task | Invariant | Allowed paths |
|---|---|---|---|
| 1 | **The deploy payload comes from the commit, not the tree** — `QEVIK_DEPLOY_SHA` contract, ancestor refusal, `git archive` export + integrity check, every read from the export, `--rehearse`, test harness (fake host via PATH shims) | mutating the tree during a deploy cannot change what ships; rehearse writes nothing | `infra/deploy_control.sh`, `packages/kernel/tests/test_deploy_control.py`, `docs/qevik-docs/autonomous/DEPLOY_APP_QEVIK_AI.md` |
| 2 | **The host says what it holds, and a rollback tells the truth** — manifest verification on the host, `DEPLOYED_SHA`, rollback hygiene (no masking, guarded `rm`, console + units restored, `ROLLBACK INCOMPLETE`), `:220` guard | the marker describes bytes on disk at every exit; a rollback failure is never reported as success | same as 1 |
| 3 | **The loop ships the commit it tested, and reads back what shipped** — capture `S`, exit-code checks in the landing sequence, HEAD/clean/ancestor bracket around the full suite, lease renewals, pass `QEVIK_DEPLOY_SHA`, gate timeout, provenance read-back before production verification, `S` in the transition record | a drift between landing and deploy is CONTESTED, never a deploy; production verification cannot claim `S` unless the host's marker agrees | `infra/devloop/driver.py`, `infra/devloop/gates.py`, `packages/kernel/tests/test_devloop.py` |

Tests required across the three (the owner's list, with where each lives):

| Invariant | Task |
|---|---|
| deployment source is independent of working-tree mutation | 1 |
| branch checkout / change during deployment cannot alter payload `S` | 1 |
| non-ancestor / unlanded sha refuses deployment | 1 (script), 3 (driver) |
| HEAD mismatch before / after the suite refuses deployment | 3 |
| `DEPLOYED_SHA` correctness and rollback behaviour | 2 |
| rehearse performs no live writes (with a negative control proving the check can fail) | 1 |
| rollback failure cannot be silently reported as success | 2 |

## Rollout

1. Task 1, 2, 3 land through the loop (build → gates → blind review → DONE),
   as `requires_deploy=0` tasks: nothing deploys as a side effect of landing.
2. `QEVIK_DEPLOY_SHA=<main tip> ./infra/deploy_control.sh --rehearse` against
   the real host, from a clean checkout of `main`, watched. Output kept as
   evidence.
3. First real deployment: a trivial, low-risk, reviewed commit; human-watched;
   never under `driver.py run`. Evidence: the script's verification lines,
   `DEPLOYED_SHA` read back, worker fingerprints, service health.
4. Only then: Step 2 as its own decision.

## Evidence rules

A claim that "the host runs `S`" is CONFIRMED only when the host's
`DEPLOYED_SHA` names `S` **and** the manifest verification for that deploy
passed **and** the workers report the fingerprint of `S`'s
`infra/mission_worker.py`. Any one of these missing is NOT_VERIFIED, never
absent and never assumed. A rehearse that passed says the payload *could* be
constructed and transferred; it says nothing about what the host runs.

## Implementation record

_Appended as each task lands: task id, sha, review rounds, size, scope
verdict. Empty until then._

- **T1 — sha contract, verified `git archive` export, `--rehearse`** · task `t-1194cbe7823c`
  (attempt 2; attempt 1 `t-18c738db28b4` CONTESTED after 3 rounds, branch kept unmerged
  at f1129d9) · landed **a09bae5** on 2026-09-02T10:15Z · run r-e914b67efb, base 82ab9ef ·
  2 review rounds (r1: 1 blocking P2 — worker-file presence was checked after the copy and
  restarts, fixed to validate before any host write; r2: CLEAN) · gates changed=pass,
  tests=pass both rounds · scope: 3 changed paths, all inside the contract
  (`infra/deploy_control.sh` +352/−53, `packages/kernel/tests/test_deploy_control.py` +681,
  `docs/qevik-docs/autonomous/DEPLOY_APP_QEVIK_AI.md` +76) · 2,866 s. Not yet run against
  the host; `--rehearse` against the real host happens after T2 and T3 land.
- **T2 — host manifest check, `DEPLOYED_SHA` marker, rollback hygiene** · task `t-e44a121a65b1`
  (attempt 1) · **CONTESTED** 2026-09-02T11:30Z after 3 rounds, branch kept unmerged at
  9e6c0be (base 3c1d804, run r-5b095f6400, 4,313 s) · gates pass and scope kept in all three
  rounds (3 paths inside the contract: `infra/deploy_control.sh` +397/−59,
  `packages/kernel/tests/test_deploy_control.py` +542, `DEPLOY_APP_QEVIK_AI.md` +120) ·
  each round's findings were fixed and each round surfaced a new one in the same area —
  r1: stale snapshot kept when a target is absent (`:564-566`), failed rollback-marker
  write still reported ROLLED BACK (`:287-290`); r2: manifest promotion `mv … || [ -f … ]`
  masked (`:707-708`), symlinks omitted from the manifest (`:171-176`, major); r3: the
  second `write_marker` on the rollback-incomplete path can fail and leave a stale
  `state=installed` marker (`:303-306`, major) · the r1 and r3 findings are the same class
  (marker write failure not treated as provenance failure) at two sites; the fixer fixed
  the instance, not the class · nothing deployed; no successor enqueued — awaiting the
  owner's decision (successor with recorded diagnosis, decision reference, or abandonment).

- **T2 (attempt 2) — host manifest check, `DEPLOYED_SHA` provenance under one checked
  write contract, rollback hygiene** · task `t-9f3ecb58b4ad`, successor of
  `t-e44a121a65b1` (owner route (a), 2026-09-02; recorded as DQ-012 run 1/15 — the
  recurrence was class-level, not independent findings) · **LANDED 2b7855c** on main
  2026-09-02 (base 357a991, run r-ed199810da, 5,336 s, DONE) · 3 rounds: r1 two
  blocking (provenance probe treated `ssh` exit 255 as absence, :634-637; failed
  manifest removal not entered in `NOT_RESTORED`, :297-299), r2 two major (console
  transfer lacked the manifest's exclusions, :531-532; `--rehearse` did not plan the
  `DEPLOYED_MANIFEST.new` transfer, :584-589), r3 **CLEAN** · gates pass and scope
  kept every round; same three-path contract (`infra/deploy_control.sh` +516/−…,
  `packages/kernel/tests/test_deploy_control.py` +872, `DEPLOY_APP_QEVIK_AI.md` +155;
  1,475 insertions, 68 deletions) · the class invariant holds structurally: every
  atomic marker write lives inside `provenance_write()` (read-back verified;
  `test_the_marker_has_exactly_one_writer`), every call site is enumerated and driven
  to failure (`test_every_provenance_write_has_a_case_below`,
  `test_a_failed_marker_write_is_never_reported_as_success` × 6 sites: installing,
  installed, rolling-back, previous-verbatim, rolled-back, rollback-incomplete), and no
  outcome word or exit code is finalised before its provenance write succeeded · all
  five attempt-1 findings covered by named tests (stale snapshot / absent target,
  demotion-first rollback marker, manifest promotion under `set -e`, symlink refusal
  in preflight, unchecked second marker write) · 46 tests in the file · nothing
  deployed; the first real deployment remains human-watched after T3, per Step 1
  item 10.

- **T3 (attempt 1) — CONTESTED 2026-09-02.** `t-03e23ee8f736` (base 235579d, run
  r-e4fbcf761e, 13:31→16:07 UTC, 2 h 36 min of which 2 h 13 min was the build) on the
  contract `infra/devloop/driver.py`, `infra/devloop/gates.py`,
  `packages/kernel/tests/test_devloop.py`; branch `devloop/t-03e23ee8f736` kept at
  46d8dfe (+940/−43, three commits, pushed to origin). Gates and scope passed in all
  three rounds. Findings: r1 blocking `driver.py:525-530` — a squash *commit* failure
  (hook/signing) returns CONTESTED with the squash still staged on main, wedging the
  loop at the clean-tree check; r2 major `driver.py:657` — the r1 fix's
  `git reset --hard HEAD` would also destroy edits not on the task branch (hook
  rewrites, operator edits after the check); r3 blocking `driver.py:546-547` — the r2
  cleanliness check is racy without an exclusive repository lock spanning
  check/squash/commit/cleanup; r3 major `gates.py:443-447` — `gates.provenance`
  parses the marker into a dict so duplicate `sha`/`state` lines let the last value
  win and a contradictory marker can pass. Rounds 1–3 are one chain about the
  failed-squash cleanup on main (absent → destructive → racy), a path the brief did
  not name; the gates.py finding is independent and narrow. Not re-enqueued: the
  route is the owner's decision. Nothing deployed.

- **DQ-013 — shipping-path failure policy (owner, 2026-09-02).** Decided after the T3
  attempt-1 report, and governing every later `_ship` change: (1) the DevLoop stays a
  single-driver, serial executor — no repository lock is introduced merely against a
  hypothetical second driver (it would not protect against a human edit either);
  (2) the shipping path never automatically runs `git reset --hard` or an equivalent
  destructive reset against `main` to recover from a failed squash merge or squash
  commit; (3) preservation of unknown work outranks automatic loop liveness — when the
  post-failure repository state cannot be *proven* to contain only DevLoop-generated
  squash state, nothing is destroyed: the state is preserved, the task moves to
  BLOCKED, and explicit evidence says what remains and why a person is required;
  (4) a non-destructive cleanup proven safe and limited strictly to the squash state
  may be used, otherwise BLOCKED is the correct terminal outcome; (5) the successor
  also closes the independent parser defect — duplicate authoritative marker fields
  (`sha`, `state`, any repeated key) fail closed rather than last-value-wins;
  (6) DQ-012 run 2/15, recorded as a chained design escalation on one
  failed-shipping path, not the class-level pattern of run 1. T3 is not abandoned; a
  successor with a structured diagnosis and the same three-path contract follows once
  the owner has reviewed its brief.

- **T3 (attempt 2, T3b) — LANDED 8f649c9, DONE 2026-09-02.** `t-a32470d01b7a`
  (base f7a18a8, run r-8e0bc10800, 16:45→18:04 UTC, 1 h 19 min; successor of
  t-03e23ee8f736 under DQ-013 with a structured diagnosis, contract relation
  *equal*) on the same three paths; squash 8f649c9 = +1,480/−37 across `driver.py`
  (+445), `gates.py` (+174), `test_devloop.py` (+898). Gates and scope passed in all
  three rounds. Findings: r1 blocking `driver.py:769-776` — a path edited between
  the content proof and the cleanup loop would be overwritten; r1 blocking
  `driver.py:750-754` — a mode-only change (executable bit) keeps its blob hash and
  escaped the proof; r2 blocking `driver.py:676-678` — the marker was not re-read
  after the production probe, so bytes replaced mid-probe could be recorded as
  verification of S; r3 CLEAN. Fixes stayed inside DQ-013: each path is re-proven
  (content *and* mode, `core.fileMode`-aware) immediately before it is touched and
  any drift stops the cleanup as BLOCKED, saying how far it got — no repository lock,
  and the file contains no `reset --hard`, `clean`, or `checkout -- .` call; the
  provenance marker is read again after the probe and must still name S as
  `installed`. Duplicate marker keys now fail `gates.provenance` closed. Nothing
  deployed by this task. Step 1 is now implemented end to end on `main`; what remains
  of Step 1 is item 10 — a `--rehearse` against the real host, then the first
  human-watched deployment of a trivial reviewed commit.


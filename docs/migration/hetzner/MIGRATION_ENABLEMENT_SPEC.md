# MIGRATION ENABLEMENT SPEC — make the deploy path capable of targeting `qevik-prod-01`

**Specification only. Nothing here has been implemented or executed.** No host,
service, database, secret, DNS or Cloudflare setting was changed while writing
it. No secret value was requested, handled or generated. Phase 3 has not
started; the DevLoop remains paused (AR-5).

**Why this exists.** `PHASE_4_PRE_EXECUTION_REVIEW.md` (commit `abcf400`) found
four blockers that would make Phase 4 unsafe or non-reproducible, plus two
retention hazards. The owner's decision (2026-09-03) is to fix the deployment
path **before** production credentials are created:

> "Phase 3 credentials are created only after the deployment path itself is
> proven capable of safely deploying to `qevik-prod-01`."

So the migration order changes:

```
  Phase 2 (done) → ENABLEMENT (this spec, reviewed code) → Phase 3 (secrets) → Phase 4 (runtime) → …
```

Evidence tags: **PROVED** · **OBSERVED** · **INFERRED** · **UNKNOWN**. DQ-009
applies: every genuine choice is presented with options and a default, and is
not decided here.

---

## 1. Scope contract

**In scope — repository changes only, under the normal reviewed workflow**

| # | Workstream | Outcome |
|---|---|---|
| WS-1 | Deploy target + SSH identity parameterisation | One deployment system that can address the old host **and** `qevik-prod-01`, with explicit configuration and no hidden inference |
| WS-2 | Caddy installation method | A reproducible, version-gated install of a production-compatible Caddy (≥ 2.7, matching production 2.11.4) |
| WS-3 | Caddyfile source of truth | One reviewed target artifact = repository file minus the `:8443` block, plus a written live-vs-repo reconciliation record |
| WS-4 | Env / DB password handling | The deploy stops interpreting `atlas.env` through a shell; password entropy and character set are never constrained |
| WS-5 | Unit / timer / slice inventory | Every unit classified by who installs it and who enables it, with an activation guard against premature backup jobs |
| WS-6 | Migrated dump protection | The 11 historical production dumps are structurally outside the retention glob, with a stated hand-over rule |

**Explicitly out of scope**

- Any change to `qevik-core-01` (AR-4: read-only).
- Any host change on `qevik-prod-01` — including the archive move in WS-6, which is *specified* here and *executed* in Phase 4 step 5 (or as its own approved step).
- Any secret value: none is created, read, requested, rotated or transported. Phase 3 still owns that, and follows this work.
- Cloudflare, DNS, data migration, cutover.
- Re-architecture: no second deployment system, no containers, no config-management framework (AR-3).
- `health.py:23 SERVICES` (T9 / N-5) — real, but Phase 10 code with its own approval.

**Invariants this work must not break**

1. ADR-0010 remains the only sanctioned way code reaches a host: immutable payload, `DEPLOYED_SHA`/`DEPLOYED_MANIFEST` provenance, refusal on dirty tree or non-ancestor SHA.
2. Defaults keep pointing at **the old host** until cutover, so a rollback never needs a commit (D-H).
3. No secret ever appears on a command line, in a log, in git, in docs, or in agent context (SR-1, SR-9).
4. `--rehearse` continues to write nothing to any host.
5. No behaviour change is introduced on `qevik-core-01` by this work; nothing is deployed there.

---

## 2. Blocker classification (owner's A / B / C scheme)

**A** = Phase 3 infrastructure change · **B** = separate reviewed repository change required before Phase 4 · **C** = decision/configuration reconciliation only.

| # | Blocker | Class | Must land before | Why |
|---|---|---|---|---|
| B-1 | Caddy must not be Ubuntu's 2.6.2 | **B + C** — a reviewed installer script (B) and the plan wording already corrected (C). Not A: nothing about it belongs to the security baseline. | **Phase 4** (nothing in Phase 3 installs Caddy) | The install must be reproducible and version-gated, not a hand-typed apt line |
| B-2 | Repository Caddyfile is the source of truth; `:8443` block removed | **B + C** — removing the block is a code change; choosing the repo over the live file is a reconciliation decision | **Phase 4** | Also removes one hard-coded old-host IP |
| B-3 | Deploy target **and SSH identity** parameterised | **B** | **Phase 4** — but *strongly recommended before Phase 3* (see §3.1 note) | Without it, no deploy script can address `qevik-prod-01`; with the wrong key it must not be able to |
| B-4 | `atlas.env` must not be parsed by a shell | **B** | **Phase 4** — and the fix must exist **before the owner chooses the DB password in Phase 3**, so the choice is never constrained | The password is created in Phase 3; the parser that must accept it is code |
| B-5 | Migrated dumps protected from retention pruning | **A + B** — the move is a host action in the Phase 3/4 window (A-shaped), plus one small reviewed change to keep the daily restore-proof working (B) | **before any backup unit runs on the target** | Structural protection beats a documented promise |
| B-6 | `qevik-backup.timer` stays disabled until Phase 6 | **A + C** — an enablement decision enforced by an installer guard (B, small) | **Phase 4** | Prevents dumps of an empty DB and the pruning they would trigger |

**Nothing in this set is Phase-3-blocking except B-4's sequencing** (the password
must be chosen after the parser is fixed, so entropy is never traded for
shell-safety) **and, by strong recommendation, B-3** — the owner's own rationale:
prove the deploy path before creating credentials.

---

## 3. WS-1 — Deploy target and SSH identity parameterisation (B)

### 3.1 Audit (PROVED, `file:line`)

| File | Line | Literal |
|---|---|---|
| `infra/deploy_control.sh` | 67 | `TARGET="${TARGET:-root@2.28.62.83}"` |
| `infra/deploy_control.sh` | 68 | `KEY="$HOME/.ssh/naml_hetzner"` — **no env override** |
| `infra/deploy_console.sh` | 21 | `TARGET="${1:-root@2.28.62.83}"` |
| `infra/deploy_console.sh` | 13 occurrences | `-i "$HOME/.ssh/naml_hetzner"` inline on every `ssh`/`scp`/`rsync` |
| `infra/deploy_console.sh` | 37 | refusal text naming `qevik-core-01 / 2.28.62.83` |
| `infra/deploy_public.sh` | 187, 44 | `TARGET` default, `KEY="$HOME/.ssh/naml_hetzner"` |
| `infra/devloop/boundary.py` | 33 | `HOST = "root@2.28.62.83"` |
| `infra/devloop/inspection.py` | 32 | `HOST = "root@2.28.62.83"` |
| `infra/devloop/gates.py` | 416, 537 (+3 key refs) | `"root@2.28.62.83"`, `naml_hetzner` |
| `packages/kernel/atlas_kernel/infra/cloudflare.py` | 41 | `ORIGIN_IP = "2.28.62.83"`; `check_writable` refuses any other A-record content |
| `infra/run_objective.py` / `resume_objective.py` / `prospect_pipeline.py` | 47 / 44 / 36 | `PUBLIC_BASE` default `http://2.28.62.83` (already env-overridable via `QEVIK_SITES_BASE_URL`) |
| `infra/rotate_admin.py` | 169 | example `ssh -i ~/.ssh/naml_hetzner root@2.28.62.83` in help text |
| `infra/secure_8443.sh` | 26, 54, 68, 104, 106 | old IP (obsolete once WS-3 lands) |
| `infra/qevik-production.Caddyfile` | 230 | `https://2.28.62.83:8443 {` (removed by WS-3) |
| `infra/qevik-control.Caddyfile` | 14 | superseded file |
| `infra/qevik-sites.Caddyfile` | 20 | `default_sni 2.28.62.83`, superseded file |
| tests | `test_public_autonomous_loop.py:41`, `test_model_driven_planning.py:269`, `test_public_serving.py:640` | old IP / key in assertions |

`91.107.244.253` appears nowhere in the repository. `qevik-prod-01` appears only
in `infra/install_offsite_backup.sh` as an **operator-side SSH alias**.

### 3.2 Design

One registry, two thin readers, no inference.

**`infra/deploy_targets.conf`** (new, committed, reviewed) — the single source of truth:

```
# name      ssh_destination        identity                    role
default     = old-prod             # flipped to new-prod in ONE reviewed line at cutover
old-prod    root@2.28.62.83        ~/.ssh/naml_hetzner         production until cutover
new-prod    root@91.107.244.253    ~/.ssh/qevik_prod           production after cutover
```

Resolution order, applied identically everywhere (**explicit beats implicit; no fallback guessing**):

1. `--target <name>` / first positional `<name>` → looked up in the registry.
2. `QEVIK_DEPLOY_TARGET=<name>` → same lookup.
3. A raw `user@host` positional → **requires** `QEVIK_DEPLOY_KEY` to be set; otherwise **refuse (exit 2)**.
4. Nothing given → the registry's `default` entry.
5. An unknown name → **refuse (exit 2)**. Never fall back to a default on a typo.

Every script then uses `$TARGET_HOST` and `-i $TARGET_KEY -o IdentitiesOnly=yes`
(`deploy_control.sh` currently omits `IdentitiesOnly`, which lets an agent offer
other keys — fixed here, and it matters now that `MaxAuthTries` will be lowered
in Phase 3).

**Shared implementation, so no second system appears:**

- `infra/deploy_target.sh` (new, ~40 lines) — `qevik_resolve_target()` sourced by `deploy_control.sh`, `deploy_console.sh`, `deploy_public.sh`.
- `infra/deploy_targets.py` (new, ~40 lines) — same parser for `infra/devloop/{boundary,gates,inspection}.py`.
- `packages/kernel/atlas_kernel/infra/cloudflare.py` — the kernel must not read repo-side infra files at runtime, so `ORIGIN_IP` becomes `os.environ.get("QEVIK_ORIGIN_IP", "2.28.62.83")` with the same refusal semantics in `check_writable`. Default unchanged until cutover.

**SSH aliases.** The operator's `~/.ssh/config` already has a `qevik-prod-01`
alias with the right key. It is *not* reviewable and must not become load-bearing:
the registry may name a bare alias as the destination (`qevik-prod-01`) with
identity `-` meaning "let ssh_config decide", but the **default entries stay
explicit host + explicit key**. Recommended: keep explicit; allow aliases for
ad-hoc use only.

### 3.3 Files that change

| File | Change |
|---|---|
| `infra/deploy_targets.conf` | **new** — the registry |
| `infra/deploy_target.sh` | **new** — shell resolver |
| `infra/deploy_targets.py` | **new** — Python resolver |
| `infra/deploy_control.sh` | source the resolver; replace lines 67–68; add `IdentitiesOnly=yes`; keep every existing refusal |
| `infra/deploy_console.sh` | source the resolver; replace 14 inline `-i …naml_hetzner` with `$TARGET_KEY`; update the refusal text; **decision D-S1**: remove its `--delete` kernel rsync (line 49), which is a second, provenance-free code path into the directory ADR-0010 owns |
| `infra/deploy_public.sh` | source the resolver; replace lines 44, 187 |
| `infra/devloop/{boundary,gates,inspection}.py` | import the resolver instead of `HOST`/key literals |
| `packages/kernel/atlas_kernel/infra/cloudflare.py` | `ORIGIN_IP` from env with the old default |
| `infra/rotate_admin.py` | help text references the registry |
| `packages/kernel/tests/test_deploy_control.py` | new cases (below) |
| `packages/kernel/tests/test_public_serving.py` | update the `naml_hetzner` assertion at 640 |
| `packages/kernel/tests/test_devloop.py` | update host-constant assertions |
| `packages/kernel/tests/e2e/*` | two IP literals → registry/env |

### 3.4 Tests

1. `--target new-prod` resolves to the new host **and** `qevik_prod`; `naml_hetzner` appears nowhere in the resulting argv.
2. `--target old-prod` and no argument both resolve to the old host + `naml_hetzner` (**defaults unchanged**).
3. Unknown name → exit 2, no ssh attempted.
4. Raw `user@host` without `QEVIK_DEPLOY_KEY` → exit 2.
5. `--rehearse` against a fake target still writes nothing (existing harness at `test_deploy_control.py:438`).
6. Grep-style guard test: no `naml_hetzner` and no `2.28.62.83` literal outside `infra/deploy_targets.conf`, docs and archived evidence — this is the test that stops the drift returning (`feedback_parallel_lists_drift`).
7. Every existing `test_deploy_control.py` case still passes unchanged.

### 3.5 Rollback implications

Pure repo change; revert the commit. Because defaults are unchanged, a revert
mid-migration leaves the old host addressable exactly as today. At cutover the
`default =` line flips; rolling back the cutover is that one line, not a
redesign — which is precisely D-H's requirement.

---

## 4. WS-2 — Caddy installation (B + C)

### 4.1 Facts

- Old host: **Caddy 2.11.4**, from `https://dl.cloudsmith.io/public/caddy/stable/deb/debian` (`/etc/apt/sources.list.d/caddy-stable.list`) — PROVED.
- Target: `caddy` absent; Ubuntu 26.04 candidate **2.6.2-14** — PROVED.
- `infra/qevik-production.Caddyfile` uses `handle_errors` + `file_server { status 404 }`, documented in the file itself as needing **Caddy ≥ 2.7**.

### 4.2 Design — `infra/install_caddy.sh` (new, idempotent, root)

1. If `caddy` is present and `caddy version` ≥ the required floor, exit 0 (idempotent).
2. Fetch the Cloudsmith signing key over HTTPS, compute its fingerprint, and **compare against a constant committed in the script**; refuse on mismatch — the same trust-on-verified-pin pattern already used for the Storage Box host key in `install_offsite_backup.sh`.
3. Write `/etc/apt/sources.list.d/caddy-stable.list` (signed-by the pinned keyring), `apt-get update`, `apt-get install -y caddy`.
4. **Version gate:** parse `caddy version`; refuse unless ≥ `2.7` (hard floor) and warn unless it matches the production line `2.11.x` (parity target). Record the exact version for evidence.
5. **Config gate:** `caddy validate --config <the WS-3 artifact>` must pass before Caddy is ever started with it.
6. Print installed version + package origin; change nothing else (the package creates the `caddy` user and `/var/lib/caddy`).

Alternative considered and rejected for now: the official static binary + checksum
from GitHub releases. More self-contained, but then we own the systemd unit, the
`caddy` user and the upgrade path — a divergence from production for no benefit.
Recorded as **decision D-S2** if the owner prefers not to add a third-party apt
source.

### 4.3 Files

| File | Change |
|---|---|
| `infra/install_caddy.sh` | **new** |
| `docs/migration/hetzner/MASTER_MIGRATION_PLAN.md` | Phase 4 allowed/forbidden wording — **already amended** (§8) |
| `packages/kernel/tests/test_public_serving.py` | add a test that the installer's floor (≥ 2.7) is ≥ the features the Caddyfile uses |

### 4.4 Tests / validation

- Unit-level: version-comparison helper accepts `2.11.4`, rejects `2.6.2`, rejects unparsable output (refusal, not a pass).
- On the target (Phase 4, not now): `caddy version` ≥ 2.11 · `apt-cache policy caddy` shows the Cloudsmith origin · `caddy validate` exit 0 · `systemctl cat caddy` is the packaged unit.
- Negative control: run the validator against the current *distro* version string and confirm the gate refuses.

### 4.5 Rollback

`apt purge caddy`, remove the source list and keyring, `apt update`. Nothing else
on the host depends on Caddy until Phase 4 step 11.

---

## 5. WS-3 — Caddyfile source of truth (B + C)

### 5.1 The reconciliation (PROVED by diff, 2026-09-03)

| | Live `/etc/caddy/Caddyfile` (old host) | Repo `infra/qevik-production.Caddyfile` |
|---|---|---|
| Lines | 225 | 290 |
| sha256 | `38df2a4a…` | `8d879127…` |
| `qevik.ai` block | `try_files {path} /index.html` — the **SPA fallback**, which serves the homepage with HTTP 200 for `/services/`, `/about/`, the Arabic site and any unknown URL | fallback removed; `file_server` resolves directories itself |
| `handle_errors` | absent | present: `/ar/404.html` for `/ar/*`, `/404.html` otherwise, both with `status 404`; anything non-404 answered plainly |
| `:8443` block | `https://2.28.62.83:8443` (`tls internal`) — unreachable, blocked by ufw | same block, to be removed (D-D) |
| Everything else | identical | identical |

**The repository is newer.** `DATA_AND_STATE_INVENTORY.md` P1's instruction to
migrate the live file as the target's source of truth would regress a committed
fix, and is corrected (§8).

### 5.2 The target artifact

The reviewed artifact is `infra/qevik-production.Caddyfile` **with the
`https://2.28.62.83:8443 { … }` block deleted** (D-D: the emergency door is
removed; the Hetzner console is the break-glass). One file, deployed to both
hosts by the same tooling — no per-host variant, no second config system.

Consequence to state plainly: the block is also gone from what the *old* host
would receive on its next `deploy_console.sh` run. Nothing may be deployed to the
old host before cutover (AR-4), so no behaviour changes there; but if the owner
ever runs a console deploy on the old host, the (already unreachable) 8443 door
disappears. **Decision D-S3** if the owner wants it kept until Phase 11.

Second consequence, for the cutover checklist: after cutover the public site
answers **real 404s** where today it answers 200 with the homepage. That is the
fix landing in production, and it should be announced rather than discovered.

### 5.3 Files

| File | Change |
|---|---|
| `infra/qevik-production.Caddyfile` | delete the `:8443` block (~35 lines, incl. one hard-coded IP) |
| `infra/secure_8443.sh` | **delete** (it exists only to lock down that block; it is marked "PROPOSAL — NOT YET APPLIED" and carries 3 IP literals) — or keep with an obsolete header (**D-S3**) |
| `infra/qevik-control.Caddyfile`, `infra/qevik-sites.Caddyfile` | superseded; add a deprecation header naming the production file, or delete (**D-S4**) |
| `docs/migration/hetzner/evidence/phase-4/caddyfile-reconciliation.md` | **new** — the hunk-by-hunk record: live vs repo, which side is newer, the decision, and the sha256 of both inputs and of the final artifact |
| `packages/kernel/tests/test_public_serving.py` | assert the production Caddyfile contains **no** `try_files` in the `qevik.ai` block (already covered), and now also **no** `:8443` block and no bare-IP site address |

### 5.4 Rollback

Repo revert restores the block. On a host, the previous `/etc/caddy/Caddyfile` is
kept as a copy before any install (Phase 4 step 11), and `caddy validate` gates
the swap, so a bad config never reaches a running Caddy.

---

## 6. WS-4 — Env / database password handling (B)

### 6.1 Audit (PROVED)

Shell-sourcing of `atlas.env` exists in five places:

| File | Line | Context |
|---|---|---|
| `infra/deploy_control.sh` | 766 | `ssh_ "cd … && set -a && . $ENV_FILE && set +a && … init_db()"` — **the deploy blocker** |
| `infra/devloop/boundary.py` | 78 | remote command builder, same pattern |
| `infra/devloop/inspection.py` | 145 | same |
| `infra/devloop/gates.py` | 496 | same |
| `infra/qevik_backup.sh` | 43 | `set -a; . "$ENV_FILE"; set +a` — runs **under systemd** in production, but the script is also runnable by hand |
| `infra/bootstrap_qevik_server.sh` | 130, 164 | not used on the target (§6.4 of the review) |
| `infra/prove_dispatch_on_production.py` | 14 | hand tool |

A password containing `$`, backtick, `"`, `'`, `\`, `;`, `&`, `|`, `(`, `)`, `#`
or whitespace either breaks the parse or is silently mangled. The existing
production password happens to survive; a newly generated high-entropy one very
likely will not. This is the same failure that the restic repository password
produced in the off-host backup work, where the fix was to stop using a shell.

### 6.2 Design — use systemd's own parser, never a shell

Replace the remote one-liner with:

```
systemd-run --wait --collect --pipe --quiet
  --unit=qevik-schema-<short-sha>
  --property=EnvironmentFile=/opt/qevik/atlas.env
  --property=User=qevik --property=Group=qevik
  --property=WorkingDirectory=/opt/qevik/atlas
  --setenv=PYTHONPATH=/opt/qevik/atlas/packages/kernel
  /opt/qevik/atlas/.venv/bin/python -c 'from atlas_kernel.db import init_db; init_db(); print("schema applied")'
```

Why this and not a hand-written parser:

- It is **the same parser the services use**, so the schema step sees byte-identical values to `qevik-api`/`qevik-control`/the workers. A bespoke reader could diverge on quoting and produce a schema step that works while the services fail (or worse, the reverse).
- The value never touches a shell, a command line or a log: `--property=EnvironmentFile=` passes a **path**, and systemd reads it as root before dropping to `User=qevik`.
- `--wait` propagates the exit status; `--pipe` returns stdout/stderr to the deploy; `--collect` removes the transient unit afterwards.
- systemd **259** is present on the target (PROVED) and on the old host (same release).
- It also satisfies SR-1 (no DSN on any argv) more strictly than today.

Fallback if `systemd-run` is unavailable (not the case on either host, kept for
portability): a ~20-line reader implementing systemd's `EnvironmentFile`
semantics, invoked with the **path** as argv and used only after an explicit
`--allow-no-systemd` flag, so the safe path is the default and the unsafe one is
visible in the command.

The same substitution applies to the three DevLoop remote-command builders; they
are gated by AR-5 (DevLoop paused) but must not carry the bug forward.
`qevik_backup.sh:43` keeps its shell `source` only for hand runs; production runs
it through `EnvironmentFile=` already, and the script gains a comment saying so
(**decision D-S5**: change it too, for one consistent rule).

**What is explicitly not done:** constraining the password's alphabet or length.
The generation policy stays "whatever your password manager produces"; only the
consumer is fixed.

### 6.3 Files

| File | Change |
|---|---|
| `infra/deploy_control.sh` | replace the schema step (line 766); add the `--allow-no-systemd` fallback path |
| `infra/devloop/{boundary,inspection,gates}.py` | same substitution in the remote command builders |
| `infra/qevik_backup.sh` | comment, or the same treatment (D-S5) |
| `packages/kernel/tests/test_deploy_control.py` | new cases (below) |

### 6.4 Tests

1. **Metacharacter fixture:** an env file whose value contains `$ ' " \` `` ` `` `; & | ( ) #` and a space; assert the process observes the value **byte-identically** — compared by sha256, never printed (SR-9).
2. Assert the deploy's remote command contains **no** `. $ENV_FILE` / `set -a` and **no** env value.
3. Assert a failing schema step still triggers `rollback_and_report` with the same exit code as today.
4. Negative control: the old shell form fails the metacharacter fixture — proving the test would have caught the bug.
5. `--rehearse` unchanged (writes nothing).

### 6.5 Rollback

Repo revert. On a host nothing persists from this change; the schema step is
idempotent (`init_db()` is `CREATE … IF NOT EXISTS` by design).

---

## 7. WS-5 — Unit / timer / slice inventory and activation semantics (B)

### 7.1 Current mechanics (PROVED)

- `deploy_control.sh:804` installs `"$EXPORT"/infra/qevik-*.service` — **`.timer` files match nothing, ever**.
- The deploy **enables nothing**; it only `daemon-reload`s and restarts.
- `qevik-jobs.slice` and `qevik-api.service.d/resources.conf` are installed **only** by `recover_qevik_server.sh` — an incident-response script.
- Rollback (`deploy_control.sh:268`) does `rm -f $UNIT_DIR/qevik-*.service` and restores the snapshot taken at line 670 — services only.

### 7.2 Classification (the answer to the owner's question)

| Unit | Installed by | Enabled by | When |
|---|---|---|---|
| `qevik-api.service` | **code deployment** (glob) | infrastructure setup | Phase 4 |
| `qevik-control.service` | code deployment | infrastructure setup | Phase 4 |
| `qevik-worker{,-research,-delivery,-publish,-healthcheck}.service` | code deployment | infrastructure setup | Phase 4 |
| `qevik-backup.service` | code deployment | never (no `[Install]`) — timer-driven | — |
| `qevik-market-scan.service` | code deployment | never — timer-driven | — |
| `qevik-offsite.service` | code deployment | never — timer-driven | — |
| `qevik-backup-failed@.service` | code deployment | never — `OnFailure=` template | — |
| `qevik-offsite.timer` | **infrastructure, once** (`install_offsite_backup.sh`) | infrastructure | **already enabled** on the target |
| `qevik-backup.timer` | infrastructure, once | **only after data migration** | Phase 6, and only after WS-6 (B-5/B-6) |
| `qevik-market-scan.timer` | infrastructure, once | after the new Places key is in place and proven | Phase 7 |
| `qevik-jobs.slice` | infrastructure, once | started, not enabled | Phase 4 |
| `qevik-api.service.d/resources.conf` | infrastructure, once | n/a (drop-in) | Phase 4, **before** the first `qevik-api` start |
| `/usr/local/sbin/qevik_offsite.sh`, `qevik-backup-set-password` | infrastructure, once | n/a | present |

### 7.3 Design

1. **Ship timers with the code, enable them separately.** Widen the deploy's glob to `qevik-*.service` **and** `qevik-*.timer` (files only — shipping a timer does not enable it), so the repo becomes the source of truth for timer *content* and drift cannot accumulate. This requires the snapshot (line 670) and the rollback (line 268) to cover `.timer` as well, or a rollback would delete timers it never saved. **That coupling is the whole reason this is a reviewed code change and not a one-line glob edit.**
2. **`infra/install_qevik_infra.sh` (new, idempotent, root)** installs what the payload cannot: `qevik-jobs.slice`, `qevik-api.service.d/resources.conf`, the `/usr/local/sbin` helpers; creates the directory skeleton with the ownership model; `systemctl enable` the seven long-running services; `systemctl start qevik-jobs.slice`. It **never** enables `qevik-backup.timer` or `qevik-market-scan.timer`.
3. **Activation guard.** Enabling `qevik-backup.timer` happens only through `install_qevik_infra.sh --enable-backup-timer`, which refuses unless (a) a real `qevik` database exists with a non-zero table count, and (b) no un-archived migrated dump is present in the retention glob (WS-6). Refusal, not a warning.
4. Retire `recover_qevik_server.sh`'s role as a provisioning path: it keeps its incident-response job, and its install step points at the new script (**D-S6**).

### 7.4 Files

| File | Change |
|---|---|
| `infra/deploy_control.sh` | glob, snapshot and rollback extended to `.timer`; rehearsal plan lines too (576, 617) |
| `infra/install_qevik_infra.sh` | **new** |
| `infra/recover_qevik_server.sh` | delegate the install step |
| `packages/kernel/tests/test_deploy_control.py` | timers are shipped, timers are **not** enabled by the deploy, rollback restores timers, the unit list assertion (≈ line 1067) updated |

### 7.5 Tests

1. A deploy ships all `.service` **and** `.timer` files present in `infra/`; the manifest covers each twice (payload + installed path), as it already does for services.
2. The deploy issues **no** `systemctl enable`.
3. Rollback restores the pre-deploy timer set exactly (add a case with a timer present before the deploy).
4. `install_qevik_infra.sh --enable-backup-timer` refuses on an empty DB and on an un-archived dump; succeeds only with both satisfied.
5. Guard test: every `infra/qevik-*.timer` names a `Unit=` or has a matching `.service`, so a shipped timer can never point at nothing.

### 7.6 Rollback

Repo revert restores the `.service`-only glob. On a host: `systemctl disable
--now` plus `rm` of the timer files; the snapshot/rollback change makes this
safer than today, not riskier.

---

## 8. WS-6 — Protection of the 11 migrated dumps (A + B)

### 8.1 Hazard (PROVED)

`/opt/qevik/backups` on `qevik-prod-01` holds the 11 verified production dumps
(2026-08-17 → 2026-09-03, `root:root 0600`, original mtimes, sha256-matched, also
in restic snapshot `ed2b42b1`). `infra/qevik_backup.sh:92` prunes with
`ls -1t "$DIR"/qevik-*.dump | tail -n +$((KEEP + 1)) | rm -f`. With `KEEP=14`,
the fourth backup taken on the target starts deleting the oldest **genuine
production** dumps from local disk.

Secondary hazard: the directory is `root:root 0700` while `qevik-backup.service`
runs as `User=qevik` — the backup would fail to write there anyway.

### 8.2 Design

| Item | Rule |
|---|---|
| Archive location | `/opt/qevik/backups/archive/old-host/` — **outside** the `qevik-*.dump` glob the pruner walks, still **inside** the tree `qevik-offsite.service` ships off-host |
| Ownership | `root:root`, directory `0700`, files `0400` (read-only historical evidence; nothing on the target should ever write them) |
| Retention | **Never** pruned by `qevik_backup.sh`. Retention takes ownership only of dumps this host produced, in the top level of `/opt/qevik/backups` |
| Hand-over rule | The archive is deleted only at **Phase 11**, by an explicit owner decision, after the old host's final archive is restore-tested — the same gate that governs deleting the old server |
| Integrity | sha256 of all 11 before and after the move (must match `evidence/backup/old-host-dumps-pull.txt`), then one `qevik-offsite.service` run so the new paths are in a snapshot; restic deduplicates, so no re-upload |
| Timer | `qevik-backup.timer` stays **disabled** until Phase 6 (B-6), enforced by the WS-5 guard |

### 8.3 The one code change this needs

`qevik_offsite.sh`'s `newest_dump()` is `ls -1t "$DUMPS"/qevik-*.dump | head -1`
— top level only. After archiving, the target has **no** top-level dump until
Phase 6, so the daily run's restore-verify degrades from "sha256 match" to
"skipped (no dump on this host yet)" and the off-host copy stops being proven
daily. Change it to find the newest dump **anywhere under** `$DUMPS`, so the
archived production dumps keep the daily restore proof alive between now and
Phase 6.

| File | Change |
|---|---|
| `infra/qevik_offsite.sh` | `newest_dump()` searches recursively; `--restore-dump` likewise |
| `infra/qevik_backup.sh` | comment stating the pruner owns only top-level dumps it produced |
| `docs/migration/hetzner/OFFSITE_BACKUP.md` | archive layout + retention ownership (**amended**, §9) |

### 8.4 Tests

1. `newest_dump()` finds a dump in `archive/old-host/` when the top level is empty; prefers a newer top-level dump when both exist.
2. `qevik_backup.sh` prune test: a fixture with 20 top-level dumps and 11 in `archive/` prunes only top-level ones and leaves the archive untouched.
3. Post-move host validation (Phase 4, not now): 11 files present, sha256 unchanged, `--status` still `ok` and `restore_verified` still a match.

### 8.5 Rollback

Moving files back is a `mv`; the restic repository holds both path layouts and
never deletes content still referenced by a snapshot. The dumps exist in three
places throughout (old host — untouched, target, Storage Box).

---

## 9. Consolidated change list

**New files (7)**

`infra/deploy_targets.conf` · `infra/deploy_target.sh` · `infra/deploy_targets.py` ·
`infra/install_caddy.sh` · `infra/install_qevik_infra.sh` ·
`docs/migration/hetzner/evidence/phase-4/caddyfile-reconciliation.md` ·
(optional) `constraints.txt` from the captured `pip freeze` — Phase 4 item, listed for completeness.

**Modified — deployment path (6)**

`infra/deploy_control.sh` (target/key, `IdentitiesOnly`, schema step, timer glob + snapshot + rollback) ·
`infra/deploy_console.sh` (target/key, refusal text, D-S1 kernel-rsync removal) ·
`infra/deploy_public.sh` (target/key) ·
`infra/qevik-production.Caddyfile` (`:8443` block removed) ·
`infra/qevik_offsite.sh` (`newest_dump` recursive) ·
`infra/qevik_backup.sh` (comment / D-S5).

**Modified — secondary (6)**

`infra/devloop/{boundary,gates,inspection}.py` · `packages/kernel/atlas_kernel/infra/cloudflare.py` ·
`infra/rotate_admin.py` · `infra/recover_qevik_server.sh` ·
`infra/secure_8443.sh` (delete or deprecate, D-S3) ·
`infra/qevik-control.Caddyfile`, `infra/qevik-sites.Caddyfile` (deprecate or delete, D-S4).

**Tests (5)**

`packages/kernel/tests/test_deploy_control.py` · `test_public_serving.py` ·
`test_devloop.py` · `tests/e2e/test_public_autonomous_loop.py` ·
`tests/e2e/test_model_driven_planning.py`.

**Suggested landing order** (each its own reviewed commit, so a bisect is meaningful):

1. WS-4 (env parsing) — smallest, unblocks the Phase 3 password choice.
2. WS-1 (target + identity) — the largest surface; everything else assumes it.
3. WS-3 (Caddyfile artifact + reconciliation record).
4. WS-5 (timers/slice + installer + guard).
5. WS-6 (`newest_dump` + pruner comment).
6. WS-2 (`install_caddy.sh`) — independent; can land any time before Phase 4.

---

## 10. Validation matrix

| # | What | How | Pass criterion | Where |
|---|---|---|---|---|
| V-E1 | Defaults unchanged | run each deploy script with no target, in `--rehearse` | resolves to `root@2.28.62.83` + `naml_hetzner` | local, no host writes |
| V-E2 | New host addressable with the right key | `--target new-prod --rehearse` | resolves to the new host + `qevik_prod`; `naml_hetzner` absent from argv | local |
| V-E3 | No silent fallback | unknown target name; raw host without `QEVIK_DEPLOY_KEY` | exit 2, no ssh | local |
| V-E4 | No literals left | repo-wide grep guard test | zero hits outside the registry, docs, evidence | CI |
| V-E5 | Metacharacter password survives | fixture env file + schema step through `systemd-run` | value observed byte-identical (sha256 compare, never printed) | local/CI |
| V-E6 | Old form would have failed | same fixture through the previous shell form | fails — negative control | CI |
| V-E7 | No secret on argv or in logs | inspect the generated remote command | contains a path, never a value | CI |
| V-E8 | Timers ship, nothing is enabled | deploy against the test harness | `.timer` files present; zero `systemctl enable` | CI |
| V-E9 | Rollback restores timers | deploy → force failure → rollback | pre-deploy timer set restored exactly | CI |
| V-E10 | Backup-timer guard | `--enable-backup-timer` on an empty DB / with un-archived dumps | refuses, exit non-zero | CI (fixtures) |
| V-E11 | Archive survives pruning | 20 top-level + 11 archived dumps | archive untouched | CI |
| V-E12 | Restore proof survives archiving | `newest_dump()` with empty top level | finds the archived dump | CI |
| V-E13 | Caddy version gate | `2.6.2` / `2.11.4` / garbage | reject / accept / reject | CI |
| V-E14 | Caddyfile artifact | `caddy validate` (Caddy ≥ 2.11) + repo assertions | valid; no `:8443`; no bare-IP site; no `try_files` in `qevik.ai` | CI + Phase 4 host |
| V-E15 | Whole suite | `pytest -m "not e2e"` | green, coverage gate still met | CI |
| V-E16 | Rehearsal writes nothing | `--rehearse` against the target (Phase 4 gate, **after** owner GO) | `REHEARSED`, exit 0, host unchanged | target |

Nothing in V-E1…V-E15 touches a production host; V-E16 is the first host contact
and belongs to Phase 4.

---

## 11. Rollback implications

| Layer | Rollback |
|---|---|
| Repository | Every workstream is one revertible commit; defaults are unchanged, so a revert at any point leaves the old host addressable exactly as it is today |
| Cutover lever | `default = old-prod` → `new-prod` is a one-line change; the cutover rollback is that line plus the Cloudflare records, and never a redesign (D-H) |
| Old host | Untouched by all of it. Nothing is deployed there. The only behaviour it would ever see is the `:8443` removal, and only if someone deploys the console to it — which is forbidden before cutover |
| Target host | No host change is made by this spec. The archive move (WS-6) and the installers run in Phase 4 under their own gates, each with a `mv`-back or `apt purge` rollback |
| Backups | Unaffected. The dumps exist on the old host, on the target and in the Storage Box repository throughout; restic never drops content a snapshot references |
| DevLoop | Paused throughout; the DevLoop files change only so the bug is not carried forward |

---

## 12. Migration-document amendments (applied 2026-09-03)

| Document | Amendment |
|---|---|
| `MASTER_MIGRATION_PLAN.md` | Phase 4 prerequisites now require the B-blocker commits; allowed/forbidden lists corrected (Cloudsmith Caddy, repo Caddyfile, parameterised host+key, no password-character workaround, no premature backup timer); B-1…B-6 recorded inline; evidence list extended; Phase 3 points at this spec |
| `OWNER_DECISION_AND_FINAL_ARCHITECTURE.md` | new decision record for the enablement stage; D-E and D-H scope widened (identity, not just IP) |
| `DATA_AND_STATE_INVENTORY.md` | P1 corrected — the repository Caddyfile is the source of truth, not the live file; B1 gains the archive rule |
| `MIGRATION_RISK_REGISTER.md` | R-27…R-31 added (Caddy version, config regression, deploy identity, env parsing, dump pruning) |
| `OFFSITE_BACKUP.md` | archive layout, retention ownership, and the `newest_dump()` change recorded as planned work |
| `PHASE_4_PRE_EXECUTION_REVIEW.md` | status header: accepted as a reconciliation finding; blockers now tracked here |

---

## 13. Decisions the owner still owns

| # | Decision | Default under DQ-009 |
|---|---|---|
| D-S1 | Remove `deploy_console.sh`'s `--delete` kernel rsync (a second, provenance-free path into the ADR-0010 directory)? | remove |
| D-S2 | Caddy from the Cloudsmith apt repository (parity with production) vs the official static binary + checksum | Cloudsmith, with a pinned key fingerprint |
| D-S3 | Delete `infra/secure_8443.sh` with the `:8443` block, or keep it marked obsolete until Phase 11 | delete |
| D-S4 | Delete or deprecate the superseded `qevik-control.Caddyfile` / `qevik-sites.Caddyfile` | deprecate now, delete at Phase 11 |
| D-S5 | Apply the no-shell env rule to `qevik_backup.sh` too, or leave its hand-run `source` with a comment | apply it — one rule everywhere |
| D-S6 | `recover_qevik_server.sh` delegates its install step to `install_qevik_infra.sh` | yes |
| D-S7 | Does WS-1 land **before Phase 3** (owner's stated preference: prove the path first) or only before Phase 4? | before Phase 3 |

---

## 13a. As implemented (2026-09-03)

Approved with amendments A-1, A-2, A-3 and decisions D-S1…D-S7 (all as
recommended, except D-S4 where the owner chose deletion over deprecation, and
D-S7 where the owner chose **(a)** — the whole stage lands before Phase 3).
Repository only: no host was touched, no secret handled, no deploy run.

| Commit | Workstream | What landed |
|---|---|---|
| `ac150d1` | WS-1 (B-3) | `infra/deploy_targets.conf` + `deploy_target.sh` + `deploy_targets.py`; all three deploy scripts and the DevLoop gates resolve host **and** identity through it; `IdentitiesOnly=yes`; `PUBLIC_BASE` off the old IP; `cloudflare.py ORIGIN_IP` documented as a separately-owned DNS guard with a tripwire test |
| `0934ac7` | WS-2 (B-4) | the schema step, three DevLoop probe builders, `qevik_backup.sh` and `bootstrap_qevik_server.sh` all read the environment through `systemd-run --property=EnvironmentFile=`; the schema step runs as the service account in the app directory |
| `2f4659c` | WS-3 (B-1, B-2) | `infra/install_caddy.sh` (pinned GPG signing key, version gate ≥ 2.7, `caddy validate` gate); `:8443` block removed from the production Caddyfile; `evidence/phase-4/caddyfile-reconciliation.md` |
| `01db2bf` | WS-5 (B-6) | deploy ships `.timer` files (snapshot and rollback widened to match); `infra/install_qevik_infra.sh` owns directories, slice, drop-in and enablement, and refuses `--enable-backup-timer` on two guards; `recover_qevik_server.sh` delegates |
| `5fa9cc7` | WS-6 (B-5) | `current_dump` / `archived_dump` / `select_dump` with explicit precedence and `--strict-current`; pruner ownership documented; `--restore-dump` returns both kinds |
| `4a3aa9f` | WS-7 (D-S1/3/4) | console kernel rsync removed; `secure_8443.sh`, `qevik-control.Caddyfile`, `qevik-sites.Caddyfile` deleted; repo-wide guards against the IP and the shared key returning |

**Where the implementation differs from §3–§8 above**

1. **A-1 (no default target).** §3.2 rule 4 said "nothing given → the registry's
   `default` entry"; there is no default entry and no default host. Running any
   deploy script without `--target` (or `QEVIK_DEPLOY_TARGET`) exits 2 and lists
   the known names. **Consequence for the cutover:** it is no longer a one-line
   flip of a `default =` line — every invocation names its target, and the
   rollback is typing `old-prod`. The registry file itself does not change at
   cutover.
2. **A-2 (GPG, not SSH).** §4.2 said "signing key fingerprint" loosely; the
   implementation pins the **repository GPG signing key**
   (`65760C51EDEA2017CEA2CA15155B6D79CA56EA34`, read from the host that has been
   verifying these packages since 2026-08-17), verifies it with
   `gpg --show-keys --with-fingerprint` **before** the keyring is written, and
   records the installed version, the apt origin and the package digest.
3. **A-3 (dump selection).** §8.3 proposed making `newest_dump()` recursive. It
   is not: `current_dump()` (top level, what this host produced) always wins,
   `archived_dump()` answers only while there is no current dump, `status.json`
   records which kind was proved, and `--strict-current` makes a missing current
   dump a failure once the database holds data.
4. **DevLoop gates.** Not in §3: with no target configured they now report
   `unmeasured` rather than reaching for whichever host used to be production,
   and `provenance()` degrades instead of raising into the driver.
5. **`qevik_backup.sh`** took D-S5 option (a) by re-executing itself *through*
   systemd rather than growing a second parser — one parser, no divergence.

## 14. What happens after this spec is approved

1. Implement WS-1…WS-6 in the landing order of §9, each as a reviewed commit with its tests; run the full suite; **no host is touched**.
2. Owner reviews and pushes.
3. Only then: the **Phase 3 Pre-Execution Plan** (host baseline — swap, sshd hardening under AR-2, ufw, fail2ban, `qevik` user, directory skeleton — then the owner types the env files, with the DB password now genuinely unconstrained thanks to WS-4).
4. Then Phase 4, per `PHASE_4_PRE_EXECUTION_REVIEW.md` §12 with the amendments above.

**Status 2026-09-03:** §13a records the implementation. The stage is code-complete
and green on the repository-level matrix; nothing has run against a host. Phase 3
begins only after this stage is reviewed.

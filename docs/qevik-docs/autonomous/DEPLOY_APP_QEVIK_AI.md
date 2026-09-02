# app.qevik.ai — deployed

**Status: LIVE.** `https://app.qevik.ai` serves the Qevik Control panel.
Verified from outside the application, on the public domain:

```
GET /                       200  text/html      <title>Qevik Control</title>
GET /health                 200  application/json
GET /api/health             401  application/json
GET /api/missions           401  application/json   <- JSON, never HTML
GET /api/chat               401  application/json
GET /api/credentials        401  application/json
GET /control/sales/summary  401  application/json   <- sales console intact
GET /missions               200  text/html          <- deep link serves the shell
```

## What was wrong, and the fix

`atlas_kernel/api.py` carries `accept_api_prefix`, a middleware that rewrites
`/api/X` to `/X` so the Atlas desktop client can address the kernel either way.
Mounting the control plane there turned `/api/missions` into `/missions` — a
console path — which passed auth and returned the shell with a **200**.

So `/api/` is an *alias namespace* in the monolith and a *real namespace* in the
control plane. One application cannot hold both, and no routing hack makes it
safe. They are two products, so they run as two processes:

| Port | Service | Serves |
|---|---|---|
| 8080 | `qevik-api` → `atlas_kernel.api:app` | 181 Atlas routes + the sales console API |
| 8081 | `qevik-control` → `atlas_kernel.qevik.app:from_environment` | the composed control plane the acceptance suite exercises |

Caddy sends `/api/*`, `/auth/*` and `/health` to **:8081** and leaves
`/control/*` on **:8080**. One database, so a session issued by either is valid
at both.

## How a deploy is built

`infra/deploy_control.sh` ships **one immutable commit**, never the working
tree. This is ADR-0010 Step 1 — see
[`ADR-0010`](../../decisions/ADR-0010-Immutable-Deploy-Payload.md) for why.

```bash
QEVIK_DEPLOY_SHA=<commit landed on main> ./infra/deploy_control.sh [--rehearse] [user@host]
```

**The sha contract.** The commit comes from `QEVIK_DEPLOY_SHA` and nowhere else
— `$1` is still the ssh target. The script refuses when the variable is unset,
when it does not name a commit, and when that commit is not an ancestor of
`main` (`not landed on main`), because only `main` holds reviewed work. The sha
is resolved to its full 40 characters and printed that way everywhere.

**The export.** `git archive <sha> -- packages/kernel/atlas_kernel infra
apps/control/src` is unpacked into a private temporary directory, and every
shipped read — the kernel, the console, `infra/`, the worker fingerprint, the
unit files, the kernel-presence check — comes from there. A checkout or an edit
in the tree while a copy is in flight therefore cannot change what lands.
Before anything is used, the export is verified against the commit's own tree:
each blob `git ls-tree -r <sha>` lists must be present with that blob's id
(tracked symlinks are hashed as their link text, which is what git stores), and
the export must hold nothing else. It prints `export verified: <n> files from
<sha>`.

**What the commit must carry.** Still in the preflight, before the access check,
the export is required to hold `packages/kernel/atlas_kernel/qevik/app.py` and
`infra/mission_worker.py`, and the worker fingerprint is computed there. A
landed commit that predates the worker source or removes it verifies as an
export perfectly well — the file is simply not in that tree — so this is where
it is caught. Fingerprinting later, after the copies and the restarts, would
abort the run with production already written and the rollback path unreached;
both refusals are exit 1 and write nothing.

**No symlinks in a deployed subtree.** The host manifest below verifies files by
their content, and a link has none: `rsync -a` ships it as a link, and nothing
the host can hash says where it points. So a commit carrying a tracked symlink
under `packages/kernel/atlas_kernel`, `infra` or `apps/control/src` is refused
in the preflight — `REFUSED: <sha> ships a symlink under <path>; the manifest
cannot verify links`, exit 2, before the host is contacted. That is what makes
the manifest's file list exhaustive rather than merely long.

**The host manifest.** After the unit files are installed and `daemon-reload`
has run, and before the mission workers are restarted, the script computes one
line per regular file it placed — `<sha256>  <absolute host path>`, `LC_ALL=C`
sorted, in the `sha256sum --check` format — sends it to
`/opt/qevik/atlas/DEPLOYED_MANIFEST.new` and runs `sha256sum --check --quiet`
**on the host**. Kernel files map under `/opt/qevik/atlas/packages/kernel/
atlas_kernel/`, `infra/` under `/opt/qevik/atlas/infra/`, the console under
`/srv/qevik-control/`, and each shipped `qevik-*.service` additionally under
`/etc/systemd/system/`.

The manifest is a guarantee only if it lists **every** file the transfers place:
a file that is sent and not listed is a deployed file nobody checked, and the
host can then answer "everything matches" without having looked at it. So the
exclusions are named once per subtree — kernel `__pycache__ *.pyc`, infra
`__pycache__ *.pyc .pytest_cache`, console none — and used twice from that one
place: as `rsync --exclude` on the transfer and as `find` predicates in the
manifest. They used to be written out separately at each site and had drifted
apart (the console transfer excluded nothing while the manifest dropped three
patterns from it; the kernel transfer did not exclude `.pytest_cache` while the
manifest did), so a commit tracking such a path under a shipped prefix — git
does not care what a file is named — landed on the host outside the check.
`test_the_exclusions_are_written_down_once` fails if a `--exclude` flag is ever
spelled out at a transfer again.

Any non-zero exit — a mismatch, a missing file, a
missing tool, a flag the host's build does not take — is
`FAILED: the bytes on the host do not match <sha>` and a rollback: a check that
could not run is a refusal, never a pass. On success the manifest is promoted
(`mv` under `set -e`, so a failed promotion is a failed deploy) and the script
prints `host verified: <n> files match <sha>`.

**The provenance marker** is `/opt/qevik/atlas/DEPLOYED_SHA`, one `key=value` per
line, written atomically (`DEPLOYED_SHA.tmp` then `mv`) by one function that
reads the marker back off the host and compares it with what it sent. Nothing
else in the script writes it, and no outcome is printed or given an exit code
until that function has returned success for the marker that outcome claims.
It describes **bytes on disk, never health**: a later health or fingerprint
failure does not make an `installed` marker wrong until the rollback rewrites
it. Nothing from `atlas.env` or the environment is ever written into the marker
or the manifest.

| `state=` | Written when | Means |
|---|---|---|
| `installing` | after the rollback snapshots, before the first transfer | the disk is a mixture; a deploy killed mid-copy leaves this, which is the truth |
| `installed` | after the host's manifest check passed and the manifest was promoted | **the only state that means "the host holds this sha"**; carries `sha`, `installed_at`, `manifest_sha256` |
| `rolling-back` | first action of the rollback, before any restore | a rollback is under way; `state=installed` cannot survive into one |
| `rolled-back` | rollback finished, everything restored, nothing was recorded before | `sha=unknown`, `attempted_sha=<S>` |
| `rollback-incomplete` | rollback finished with something not put back | carries `restored=` and `not_restored=`; a person has to look |

When everything was restored **and** a previous marker existed, that marker goes
back verbatim instead — the host holds exactly what it held before.

**What each failure leaves behind.** Every failure from the moment the snapshots
exist runs one rollback function, and every cell of this table is one of: the
previous marker verbatim, `rolled-back sha=unknown`, `rollback-incomplete`, or
`rolling-back`. None is ever `installed` for the attempted sha, and none is
`installing`.

| The deploy failed at | marker write succeeds | marker write fails |
|---|---|---|
| the snapshots, or the probe that reads what they kept (before any transfer) | untouched, exit 1 `REFUSED` | untouched, exit 1 `REFUSED` |
| the `installing` marker, a transfer, the schema, a chown/restart, the health poll, the units, `daemon-reload`, the manifest transfer, its check, its promotion, the `installed` marker, a worker restart, the fingerprint poll | previous marker verbatim (or `rolled-back sha=unknown` if none), exit 1 `ROLLED BACK` | `rollback-incomplete` with `provenance` in `not_restored`, exit 4 — or, if that write fails too, `rolling-back` plus the line `provenance: marker write failed; host marker state unknown`, still exit 4 |
| any target that could not be restored, a restored tree that does not match the previous manifest, or (no previous manifest) the attempted sha's manifest that could not be removed | `rollback-incomplete` naming it — `provenance` for the manifest — exit 4 | as above, exit 4 |
| a service that did not restart, everything else restored | the marker that describes the bytes, exit 4 | exit 4 |

**Rollback snapshots** are taken before the `installing` marker and cover every
target the script changes: the kernel → `/opt/qevik/rollback`, `infra` →
`…-infra`, the console → `…-console`, the installed `qevik-*.service` files →
`…-units/`, and the previous marker and manifest → `…-provenance/`. Every prior
snapshot is removed before the live target is tested, so a target that is
**absent** leaves no snapshot at all — it leaves a marker under `…-absent/` that
the rollback reads as "do not remove anything; report this target as not
restored". A failed snapshot is `REFUSED: could not keep the current tree`,
exit 1, before anything is transferred.

Immediately after the snapshots the script asks the host, in **one** command
whose exit status is the only thing that decides whether the answer counts,
whether a marker and a manifest were kept. Absence and a dropped link are
different facts and are never merged: a link that exhausts its retries is
`REFUSED: the host could not be asked what it had kept`, exit 1, with nothing
transferred. Reading it as absence would tell the rollback that the snapshots it
is about to restore from do not exist — it would put `sha=unknown` over a real
previous marker and *remove* the manifest instead of restoring it.

The rollback restores each target from its own snapshot, measures the result
against the previous manifest — or, when nothing was recorded before this
deploy, removes the attempted sha's manifest, because there is no longer
anything on disk it describes. That removal is load-bearing rather than
best-effort: if it fails, `provenance` goes into `not_restored` and the run ends
`ROLLBACK INCOMPLETE`, exit 4. The alternative is a host reporting `ROLLED BACK`
with a `DEPLOYED_SHA` saying one thing and a `DEPLOYED_MANIFEST` next to it
listing the attempted sha's files, and each of the two looks authoritative on
its own. The rollback writes the marker **before** the restarts (the
bytes are settled by then, so a restart that hangs leaves a marker that is
already true), then restarts exactly as a deploy does — control and api through
the retrying `ssh_`, the workers one at a time through a bare `ssh` with
`reset-failed` first. Restoring the units **replaces the installed set**: a unit
this deploy added that the snapshot does not carry is removed with it. Nothing
enables or disables units.

**After `ROLLBACK INCOMPLETE` (exit 4)** a person reads
`/opt/qevik/atlas/DEPLOYED_SHA`: `not_restored=` names exactly what is wrong.
`kernel`, `infra`, `console` or `units` means that tree on the host is not the
previous one — restore it from `/opt/qevik/rollback*`, which is still there.
`provenance` means the bytes may be fine but the marker does not describe them —
compare `DEPLOYED_MANIFEST` against the disk with `sha256sum --check` before
believing either. Nothing is automatic: exit 4 exists so the loop stops rather
than deploying on top of a host in an unknown state.

**Exit codes**, which the loop and a person both read:

| Code | Meaning |
|---|---|
| 0 | deployed and verified, or rehearsed |
| 1 | a preflight refusal, or a deploy that failed and was rolled back |
| 2 | refused before any host contact — arguments, the sha, the test seams, a shipped symlink |
| 3 | the export did not match the commit |
| 4 | the rollback could not put everything back |
| 5 | a rehearsal found the host not ready |

Nothing is written to the host before the access check, and every refusal above
happens before it.

**`--rehearse`** builds and verifies the same payload, runs every transfer a
real deploy would run as `rsync -n -i` against the real host — the kernel, the
console, infra, each unit file, **and the manifest to
`/opt/qevik/atlas/DEPLOYED_MANIFEST.new`** — prints the
itemised changes and a count per target, prints the manifest's file count and
digest for the commit, reads three read-only host facts (the provenance marker,
`systemctl is-active`, whether `sha256sum` exists) and proves the host-side
check on a known input — the sha256 of the empty file against `/dev/null` —
printing `host sha256sum --check: works` or `DOES NOT WORK`. In the second case
it ends `NOT READY: a real deploy would refuse at the host check` and exits 5.
It writes nothing — no rollback copy, no marker, no schema, no chown, no
restart — and otherwise ends with
`REHEARSED sha=… kernel=… console=… infra=… units=… manifest=…; nothing was
written`. Since this host has no staging twin, a changed deploy path is
rehearsed before it is run.

The manifest transfer is in that list because it is the only one whose
destination is the application root rather than a subtree below it: on a host
where every subtree is writable and `/opt/qevik/atlas` itself is not, a
rehearsal that skipped it printed `REHEARSED` and exited 0 for a deploy that
would then fail at its last copy and roll back.

**The evidence rule** (from the ADR): "the host runs `S`" is CONFIRMED only when
`DEPLOYED_SHA` says `state=installed sha=S`, **and** the manifest verification
for that deploy passed, **and** the workers report the fingerprint of `S`'s
`infra/mission_worker.py`. Any one missing is NOT_VERIFIED — never absent, never
assumed. A rehearsal that passed says the payload could be built and
transferred; it says nothing about what the host runs.

**Redeploying an older state** is the same command with the older sha:
`QEVIK_DEPLOY_SHA=<the previous commit> ./infra/deploy_control.sh`. An
already-landed commit older than main's tip is accepted on purpose; that is how
the previous state goes back.

**Test seams.** `QEVIK_REMOTE_APP`, `QEVIK_CONSOLE_DIR`, `QEVIK_UNIT_DIR`,
`QEVIK_ENV_FILE`, `QEVIK_HEALTH_URL` and `QEVIK_ROLLBACK_DIR` exist so
`packages/kernel/tests/test_deploy_control.py` can point a whole deploy at a
fake host. **Production never sets them.** They are accepted only all six
together and only with `QEVIK_TEST_HOST=1`; anything else — one seam left in a
shell, or the flag on its own — is refused with exit 2, because half a
redirection would send part of a deploy to the wrong place. Every run prints
the targets it is about to use.

**The loop does not pass the sha yet.** `infra/devloop/gates.py` still calls the
script without `QEVIK_DEPLOY_SHA`; it passes the landed sha from task 3 of this
ADR onward, and until then an automated deploy refuses rather than reading the
tree.

## Deployment notes worth keeping

**`systemctl reload caddy` does not work on this host.** Caddy's admin API on
:2019 is disabled, so reload fails with `connection refused` while reporting the
config as valid. Use `systemctl restart caddy`. The old Caddyfile is preserved at
`/etc/caddy/Caddyfile.before-control-plane`.

**The vault master key was generated on the server**, by the server, into
`/opt/qevik/control.env` (0600, owned by `qevik`). Its value has never been
printed, transmitted or stored anywhere else. Without it the vault seals and the
Credential Centre stores nothing rather than falling back to plaintext.

## The one thing left, and it needs a person

`/api/*` answers 401 for everyone because **no operator is attached to a
tenant**. The server has `admin` and `viewer`, both with `tenant_id=''`, and the
customer boundary refuses that — correctly, since an operator account exists to
run Qevik rather than to read one customer's file.

Attaching a tenant to a production account is an auth change on a live system, so
it is yours to make:

```bash
ssh -i ~/.ssh/naml_hetzner -o IdentitiesOnly=yes root@2.28.62.83
cd /opt/qevik/atlas && set -a && . /opt/qevik/atlas.env && set +a
PYTHONPATH=packages/kernel .venv/bin/python -c \
  "from atlas_kernel.auth.store import AuthStore; \
   print(AuthStore().set_tenant('admin', 'tenant-qevik').tenant_id)"
```

No password is touched. After that, sign in at `https://app.qevik.ai` with the
existing `admin` credentials and every surface answers.

## Then

The Credential Centre lists all sixteen providers and can store keys, because the
vault is unsealed. Enter rotated keys there — never in a chat transcript.

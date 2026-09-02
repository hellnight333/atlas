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
(tracked symlinks are hashed as their link text, which is what git stores, so
one is never mistaken for a mismatch — it is refused on its own terms below),
and the export must hold nothing else. It prints `export verified: <n> files
from <sha>`.

**What the commit must carry.** Still in the preflight, before the access check,
the export is required to hold `packages/kernel/atlas_kernel/qevik/app.py` and
`infra/mission_worker.py`, and the worker fingerprint is computed there. A
landed commit that predates the worker source or removes it verifies as an
export perfectly well — the file is simply not in that tree — so this is where
it is caught. Fingerprinting later, after the copies and the restarts, would
abort the run with production already written and the rollback path unreached;
both refusals are exit 1 and write nothing.

**And what it must not carry: a symlink under a deployed path.** `rsync -a`
ships a tracked link as a link, but the manifest below is built with `find -type
f`, which cannot see one — so the link would be the only shipped byte the host
never measures, and a missing or repointed link would pass the host check and
still leave `state=installed`. Rather than a second host-side mechanism for
something no deployed path carries, such a commit is refused (`REFUSED: <sha>
carries symlink(s) under a deployed path`, exit 1, after the export check so a
*tampered* link is still reported as the mismatch it is). What the deploy sends
and what the manifest covers stay the same set.
`packages/kernel/tests/test_deploy_control.py` asserts the index holds no such
link, so this refusal costs nothing until someone adds one.

**The host measures itself.** Before the host is touched, a manifest is built
from the export: one `<sha256>  <absolute host path>` line per shipped regular
file — the kernel under `/opt/qevik/atlas/packages/kernel/atlas_kernel/`,
`infra/` under `/opt/qevik/atlas/infra/`, the console under
`/srv/qevik-control/`, and each `infra/qevik-*.service` a second time under
`/etc/systemd/system/` — sorted with `LC_ALL=C sort`. After the last copy and
`systemctl daemon-reload`, the manifest is sent to
`/opt/qevik/atlas/DEPLOYED_MANIFEST.new` and the host runs `sha256sum --check
--quiet --strict` on it itself. **Any** non-zero exit — a mismatch, a missing
file, a missing tool, an unsupported flag — prints `FAILED: the bytes on the
host do not match <sha>` and rolls back: a check that could not run is a
refusal, never a pass. On success the file is promoted to `DEPLOYED_MANIFEST`
and the script prints `host verified: <n> files match <sha>`. The promotion is
part of the guarantee rather than a tidy-up after it: it is chained (`[ -f
.new ] && mv … && [ -f DEPLOYED_MANIFEST ]`), because a failed `mv` followed by
a separate existence test is answered by the *previous* deploy's manifest, and
the marker would then record this commit's `manifest_sha256` over a durable
manifest describing the last one. A promotion that fails rolls back.

**The provenance marker** `/opt/qevik/atlas/DEPLOYED_SHA` is a few `key=value`
lines, written atomically (`DEPLOYED_SHA.tmp`, then `mv`). It describes **bytes
on disk, never health**, and it never carries anything from `atlas.env` or the
environment.

| `state=` | Written when | What it means |
|---|---|---|
| `installing` | after the rollback copies, before the first transfer | the disk is about to hold a mixture; `attempted_sha`, `previous_sha` and `started_at` say what of. A deploy killed mid-copy leaves this behind, which is the truth |
| `installed` | after the manifest check passed | the host holds `sha`; `installed_at` and `manifest_sha256` record the measurement. **The only state that means the host holds that commit** |
| `rolled-back` | by a rollback that restored everything and found no earlier marker | `sha=unknown`, `attempted_sha=<the deploy that failed>` |
| `rollback-incomplete` | by a rollback that could not restore something | `restored=` and `not_restored=` name the targets; a person has to look |

A rollback that restored everything and *did* find an earlier marker puts that
marker back verbatim, so the host goes on saying exactly what it said before.
A later health or fingerprint failure does not make an `installed` marker wrong
— the bytes really are there — until the rollback rewrites it.

**Rollback.** Before the first transfer the script keeps every target it writes:
the kernel, `infra/`, the console, the installed `qevik-*.service` files, and
the previous marker and manifest. Each saved copy is cleared before the target
is read, so the saved set is only ever *this* deploy's pre-state — a target that
is absent on the host is saved as nothing, never as whatever an earlier deploy
left behind. A copy that fails is a refusal (`REFUSED: could not keep the current
tree`) *before* anything is sent. From that point every failure — a transfer that
exhausted its retries, the schema step, a chown, the unit install,
`daemon-reload`, the manifest check, the health poll, the worker fingerprint poll
— runs one rollback, which restores each target only when the copy to replace it
exists, re-measures the restored bytes against the previous manifest, writes the
marker **before** restarting anything, and then restarts exactly what a deploy
restarts. It ends with `ROLLED BACK: <targets>` (exit 1) or `ROLLBACK
INCOMPLETE: <not restored>` (exit 4) and never reports a failed restore as
success. A target that did not exist before this deploy is one it cannot
restore: it is named in `not_restored=` and the rollback exits 4, rather than
being reported as put back. The marker counts as a target too — `provenance` in
`not_restored=` means the bytes may be back but `DEPLOYED_SHA` does not yet say
so, and is likewise exit 4. Restoring the units replaces the whole set, so a
unit this deploy added that the saved set did not contain is removed; nothing is
enabled or disabled.

**Exit codes**, which the loop and a person both read:

| Code | Meaning |
|---|---|
| 0 | deployed and verified, or rehearsed |
| 1 | a preflight refusal, or a deploy that failed and was fully rolled back |
| 2 | refused before any host contact — arguments, the sha, the test seams |
| 3 | the export did not match the commit |
| 4 | rollback incomplete — something could not be put back, or a service did not restart |
| 5 | a rehearsal found the host not ready |

Nothing is written to the host before the access check, and every refusal for
codes 2 and 3 happens before it.

**After `ROLLBACK INCOMPLETE` (exit 4)** production is in a state the script
could not finish undoing, so this is a person's job and not the loop's. Read
`/opt/qevik/atlas/DEPLOYED_SHA` first — it is accurate: `not_restored=` names
what is still wrong, and the copies are still on the host at
`/opt/qevik/rollback`, `-infra`, `-console`, `-units` and `-provenance`. Put the
named targets back from those copies by hand, run `sha256sum --check
/opt/qevik/rollback-provenance/DEPLOYED_MANIFEST`, restore that directory's
`DEPLOYED_SHA`, and restart `qevik-control`, `qevik-api` and the workers. If
`not_restored` is empty the bytes are fine and only a restart failed — the
marker already says what is on disk.

**The evidence rule** (ADR-0010): a claim that the host runs `S` is confirmed
only when the marker names `S` with `state=installed`, **and** the manifest
verification for that deploy passed, **and** the workers report the fingerprint
of `S`'s `infra/mission_worker.py`. Any one missing is not verified — never
assumed. A successful run prints all three — `host verified: <n> files match
<sha>`, the workers' fingerprint line, and finally `deployed sha=<S>` — and the
marker it left behind is the durable copy of the first. A rehearsal that passed
says the payload *could* be built and transferred; it says nothing about what
the host runs.

**`--rehearse`** builds and verifies the same payload, runs every transfer a
real deploy would run as `rsync -n -i` against the real host, prints the
itemised changes and a count per target, prints the manifest's file count and
digest (`manifest: <n> files, sha256 <digest>`), reads three read-only host
facts (the provenance marker, `systemctl is-active`, whether `sha256sum`
exists), and proves the host-side check itself on a known input — printing
`host sha256sum --check: works`, or `DOES NOT WORK` followed by `NOT READY: a
real deploy would refuse at the host check` and exit 5. It writes nothing — no
rollback copy, no marker, no schema, no chown, no restart — and ends with
`REHEARSED sha=… kernel=… console=… infra=… units=…; nothing was written`.
Since this host has no staging twin, a changed deploy path is rehearsed before
it is run.

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

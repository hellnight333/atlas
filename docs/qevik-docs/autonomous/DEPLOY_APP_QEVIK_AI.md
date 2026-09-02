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

**Exit codes**, which the loop and a person both read:

| Code | Meaning |
|---|---|
| 0 | deployed and verified, or rehearsed |
| 1 | a preflight refusal, or a deploy that failed and was rolled back |
| 2 | refused before any host contact — arguments, the sha, the test seams |
| 3 | the export did not match the commit |

Nothing is written to the host before the access check, and every refusal above
happens before it.

**`--rehearse`** builds and verifies the same payload, runs every transfer a
real deploy would run as `rsync -n -i` against the real host, prints the
itemised changes and a count per target, reads three read-only host facts
(the provenance marker, `systemctl is-active`, whether `sha256sum` exists) and
writes nothing — no rollback copy, no schema, no chown, no restart. It ends
with `REHEARSED sha=… kernel=… console=… infra=… units=…; nothing was written`.
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

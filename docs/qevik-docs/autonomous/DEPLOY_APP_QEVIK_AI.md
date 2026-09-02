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

## Deployment notes worth keeping

**`systemctl reload caddy` does not work on this host.** Caddy's admin API on
:2019 is disabled, so reload fails with `connection refused` while reporting the
config as valid. Use `systemctl restart caddy`. The old Caddyfile is preserved at
`/etc/caddy/Caddyfile.before-control-plane`.

**The vault master key was generated on the server**, by the server, into
`/opt/qevik/control.env` (0600, owned by `qevik`). Its value has never been
printed, transmitted or stored anywhere else. Without it the vault seals and the
Credential Centre stores nothing rather than falling back to plaintext.

## How a deploy is built

`infra/deploy_control.sh` builds everything it ships from one immutable commit,
never from the working tree (ADR-0010 Step 1). A checkout, a rebase or an edit
while a copy is in flight cannot change what lands on the host.

```bash
QEVIK_DEPLOY_SHA=<commit> ./infra/deploy_control.sh [--rehearse] [user@host]
```

**The sha contract.** The commit comes from `QEVIK_DEPLOY_SHA`, never from `$1`
— `$1` is and stays the ssh target. The script refuses when the variable is
unset, when it does not name a commit, and when that commit is not an ancestor
of `main` ("not landed on main"). It resolves the value to its full 40-hex id
and prints that id everywhere it mentions the commit. The branch/porcelain
checks stay as fail-safes about the operator's own checkout; they are not
where the payload comes from.

**The export.** `git archive <sha> -- packages/kernel/atlas_kernel infra
apps/control/src` is extracted into a private temporary directory that is
removed on exit. Before anything is sent, every blob in `git ls-tree -r <sha>`
for those prefixes is compared with `git hash-object` of the extracted file,
and the number of regular files under the export must equal the number of
blobs. The run prints `export verified: <n> files from <sha>`. Every shipped
read — the kernel, the console, the infra tree, the unit files, the worker
fingerprint, the kernel-presence check — comes from that export.

**Exit codes**, so a person and the loop read the same answer:

| Code | Meaning |
|---|---|
| 0 | deployed, or rehearsed |
| 1 | a preflight refusal, or a deploy that failed |
| 2 | refused before any host contact — arguments, seams, sha, tree |
| 3 | the export did not match the commit |

Nothing is written to the host before the access check (`ssh true`) succeeds.

**`--rehearse`** does the same argument parsing, the same refusals, the same
export and verification, and the same access check — then plans every transfer
a real run would make as `rsync -n -i` against the real host, reads the host's
provenance marker, service states and `sha256sum` availability, and writes
nothing: no rollback copy, no schema step, no chown, no restart. It finishes
with `REHEARSED sha=<sha> kernel=… console=… infra=… units=…; nothing was
written`. The host has no staging twin, so this is the only way to see what a
deploy would do before it does it.

**Redeploying an older state.** An already-landed older commit is allowed on
purpose — that is how the previous state goes back:

```bash
git -C . log --oneline -n 5 main          # find the commit that was good
QEVIK_DEPLOY_SHA=<that sha> ./infra/deploy_control.sh --rehearse
QEVIK_DEPLOY_SHA=<that sha> ./infra/deploy_control.sh
```

**Retries.** `ssh_` retries only exit 255 — ssh's own status for a
connection-level failure. Any other status is the remote command's own answer
and is returned at once, so a deterministic failure costs one round trip
instead of 165 seconds. The two polls therefore state their own patience: the
health poll waits 60 × 2 s, the worker fingerprint poll 60 × 3 s.

**Test seams.** `QEVIK_REMOTE_APP`, `QEVIK_CONSOLE_DIR`, `QEVIK_UNIT_DIR`,
`QEVIK_ENV_FILE`, `QEVIK_HEALTH_URL` and `QEVIK_ROLLBACK_DIR` redirect the host
paths so `packages/kernel/tests/test_deploy_control.py` can drive a whole run
against a fake host. **Production never sets them.** All six together and only
under `QEVIK_TEST_HOST=1`, or the script refuses — a seam left behind in a
shell must never redirect part of a real deploy. Every run prints
`targets: app=… console=… units=… rollback=…` so the destination is visible.

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

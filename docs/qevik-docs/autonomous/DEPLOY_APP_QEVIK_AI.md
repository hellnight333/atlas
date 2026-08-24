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

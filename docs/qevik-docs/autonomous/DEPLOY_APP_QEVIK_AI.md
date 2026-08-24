# Deploying the control panel to app.qevik.ai

**Status: not deployed. The remaining work is one debugging task, not a
credential.**

This corrects an earlier report. I said deployment was blocked on SSH access. It
is not — the `naml_hetzner` key opens `qevik-core-01`, and my first check failed
only because I let SSH pick a default identity:

```bash
ssh -i ~/.ssh/naml_hetzner -o IdentitiesOnly=yes root@2.28.62.83   # works
ssh root@2.28.62.83                                                # Permission denied
```

## What is actually on the server

| | |
|---|---|
| Host | `qevik-core-01` / `2.28.62.83`, reachable |
| Caddy | active, config at `/etc/caddy/Caddyfile` |
| API | `qevik-api.service` → `uvicorn atlas_kernel.api:app` on `127.0.0.1:8080` |
| Repository | `/opt/qevik/atlas` at `ce4ffaa` — **long behind this working copy** |
| Console dir | `/srv/qevik-control/index.html` — the old Sales Intelligence page |

So app.qevik.ai is live and healthy and serves the *previous* product. Its API
predates every control-plane route.

## Why it is not deployed yet

The server runs **`atlas_kernel.api:app`** — the monolith — not
`qevik/app.py::create_app`, which is the composed application every test and the
console acceptance run exercise.

Two ways forward, and the first was attempted and abandoned:

**1. Mount the control plane onto the monolith** (attempted, reverted). Adding
the routers to `atlas_kernel/api.py` produced 38 control-plane paths and served
the console — but `/api/missions` returned **200 with `text/html`** instead of
401 with JSON. Something in the monolith's routing matches those paths before the
mission router does. That is a security regression: an unauthenticated 200 where
an authenticated API belongs, and HTML that anything not checking content type
reads as success. It was reverted rather than shipped.

**2. Switch the service to the composed app.** `qevik/app.py` is correct today —
`/api/*` refuses with 401, the console serves, `/nonsense` 404s — and it already
mounts the sales router, so `/control/sales/*` survives. The risk is the
monolith's *other* routes, which the composed app does not carry and which
something on that host may depend on.

## The exact remaining work

1. Enumerate what `atlas_kernel.api:app` serves that `qevik/app.py` does not,
   and decide per route whether anything still calls it.
2. Either close the routing conflict in the monolith, or move the service to the
   composed app with the missing routers added to it.
3. `rsync` the working copy to `/opt/qevik/atlas`, `systemctl restart
   qevik-api`, then `./infra/deploy_console.sh root@2.28.62.83`.
4. The deploy script installs the Caddyfile — which now proxies `/api/*` — and
   verifies over HTTPS that `/api/health` returns JSON rather than HTML. It
   exits non-zero if it is still falling through.

Step 1 is the whole job. Steps 2–4 are minutes.

## Until then, run it locally

```bash
export QEVIK_VAULT_MASTER_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
python3 infra/serve_console.py
```

Prints a generated password on first run, opens on `http://127.0.0.1:8080`, and
keeps state in `~/.qevik/local/` so a mission survives restarting it. Same
application, same console, same APIs — just not on the public domain.

**Keep the master key.** The vault cannot be read without it, and without it set
the Credentials page lists all sixteen providers and stores none, because it
seals rather than writing plaintext.

## What must not happen

Do not deploy the reverted mounting. An `/api/*` path answering 200 with HTML is
worse than a 404: the console would appear to work, every call would return the
shell, and the failure would look like a data problem rather than a routing one.

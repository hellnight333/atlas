# Qevik — Capability State

What is genuinely operational, what is a seam waiting on something external, and
what does not exist. Updated 2026-08-17.

**The rule for this document: a capability is `IMPLEMENTED` only if it has been
executed end to end on `qevik-core-01` and observed to do the thing.** An
interface, a class or a passing unit test does not qualify. Where something is
blocked, the blocker is named specifically enough to act on.

---

## Legend

| State | Meaning |
|---|---|
| **IMPLEMENTED** | Executed on the canonical server and verified by observing the result |
| **INTEGRATED** | Wired into the plan runner and exercised, but against a stand-in rather than the real external system |
| **BLOCKED** | Adapter exists; a named external credential, account or piece of hardware is missing |
| **NOT IMPLEMENTED** | No working code. Do not describe as available |

---

## The autonomous execution loop

| Capability | State | Evidence |
|---|---|---|
| `code.execute` — run commands, capture stdout/stderr/exit | **IMPLEMENTED** | Subprocess with timeout, output cap, argv-only |
| `code.write` / workspace | **IMPLEMENTED** | Paths confined by `safe_join`; traversal, absolute and symlink escapes refused |
| `code.generate` — static site files | **IMPLEMENTED** | Deterministic, reproducible from stored inputs, HTML-escaped |
| `browser.operate` — open, extract, screenshot | **IMPLEMENTED** | Chromium on the server; runs on a dedicated thread so it works inside FastAPI's event loop |
| `web.search` | **IMPLEMENTED** | Brave, live, spend reported per run |
| `site.deploy` — publish then promote | **IMPLEMENTED** | Publicly reachable, verified externally |
| Plan composition (dependencies, `${step.key}` refs) | **IMPLEMENTED** | Deploy step's URL consumed by the verification step without a caller supplying it |
| Failure → diagnose → repair → re-run | **IMPLEMENTED** | Project corrupted after generation; suite fails, repairer regenerates, suite passes on attempt 2 |
| Lineage / audit trail | **IMPLEMENTED** | Every action recorded with payload, output, duration, evidence — successes and failures alike |
| Model-driven planning | **BLOCKED** | Planner and validation complete and unit-tested. **No model credential on the server.** Falls back to the deterministic planner and records that it did |

### What the model-driven planner needs

Set **one** of these in a `0600` file under `/opt/qevik/` and reference it from
the unit with `EnvironmentFile=-`:

- `QEVIK_DASHSCOPE_API_KEY` — Qwen, roughly 1/300th of Claude's cost for routine work
- `QEVIK_ANTHROPIC_API_KEY` — Claude

Nothing else changes. `default_registry()` registers a provider only when its
credential is present, and `LLMPlanner` resolves whatever is registered.

---

## Public deployment

| Aspect | State | Detail |
|---|---|---|
| Public URL | **IMPLEMENTED** | `http://2.28.62.83/<slug>/`, verified from outside the server |
| Versioned deployments | **IMPLEMENTED** | `versions/<id>/` per publish |
| Live version / promote | **IMPLEMENTED** | Atomic symlink swap through a staging name |
| Rollback | **IMPLEMENTED** | Ordinary promotion of an earlier version; verified externally |
| Deployment status | **IMPLEMENTED** | `status()` reports live version *and* re-fetches the URL |
| Post-deploy verification | **IMPLEMENTED** | `promote()` raises `DeploymentUnreachable` if the URL does not serve |
| Browser verification of the public URL | **IMPLEMENTED** | Chromium opens the public URL and extracts DOM text |
| Approval boundary | **IMPLEMENTED** | Unapproved publish refused; the site returns 404 because nothing was written |
| **HTTPS** | **BLOCKED** | **No domain resolves to this host.** A certificate authority will not issue for a bare IP |
| **DNS integration** | **NOT IMPLEMENTED** | Deliberate — see below |

### What HTTPS needs

One DNS **A record** pointing a hostname at `2.28.62.83`. Then:

```
cat > /etc/caddy/sites.d/sites.caddy <<'EOF'
sites.example.com {
    root * /srv/sites
    @site_root path_regexp siteroot ^/([^/]+)/?$
    rewrite @site_root /{re.siteroot.1}/current/
    file_server
}
EOF
systemctl reload caddy
```

Caddy obtains and renews the certificate automatically. `PublicHostTarget` then
reports `is_secure` as true because its `base_url` changed — no code change.

**DNS is not automated on purpose.** An agent that can create DNS records can
also point an existing production hostname somewhere else. That capability
belongs behind an approval gate, and there is nothing yet that needs it.

---

## Durable jobs and connectivity

The operator's link to this host is intermittently unreliable — ICMP passes, TCP
handshakes complete, and application data does not arrive, for minutes at a
time. It is a path problem, not a server problem: during one such window the
journal showed `qevik-api` returning 200s and Caddy serving other clients.

| Capability | State | Evidence |
|---|---|---|
| Detached jobs (`qevikctl`) | **IMPLEMENTED** | A workflow ran to completion during a deliberate 95-second disconnection |
| Job state after reconnect | **IMPLEMENTED** | `show` returned exit code, timestamps, duration from a new process |
| stdout / stderr / exit code | **IMPLEMENTED** | Kept per job under `/var/lib/qevik/jobs/<id>/` |
| Artifact retrieval | **IMPLEMENTED** | 2 artifacts retrieved after reconnection, including a screenshot |
| `LOST` detection | **IMPLEMENTED** | No exit code and no process is reported as lost, not guessed |
| Health/status after reconnect | **IMPLEMENTED** | `qevikctl status` — services, API, resources, active/failed/last job |
| cgroup-bounded execution | **IMPLEMENTED** | `--slice qevik-jobs.slice`; e2e ran inside it with 0 browsers left |

**Rule: every long operation goes through `qevikctl`.** Running one directly over
SSH ties its survival to a link that does not survive.

## Infrastructure

| Component | State | Detail |
|---|---|---|
| `qevik-api` | **IMPLEMENTED** | systemd, `127.0.0.1:8080` — **loopback only, deliberately** |
| Caddy site host | **IMPLEMENTED** | `:80` public, serves `/srv/sites` only, never proxies the API |
| PostgreSQL | **IMPLEMENTED** | Local, loopback |
| Daily market scan | **IMPLEMENTED** | systemd timer |
| Backups | **IMPLEMENTED** | Daily timer, proven by a real restore |
| Quota ledger | **IMPLEMENTED** | Platform limits vs spend limits distinguished |
| Worker abstraction | **INTEGRATED** | Capability strings and dispatcher exist; no remote worker has attached |
| **Authenticated API** | **NOT IMPLEMENTED** | The reason the API is still loopback |
| **Control UI** | **NOT IMPLEMENTED** | Depends on authentication |
| GPU worker (Z8 / P520) | **BLOCKED** | Hardware not attached |
| Iran worker | **BLOCKED** | Hardware not attached |

---

## Factories — do not describe these as working

| Factory | State | Honest position |
|---|---|---|
| Website Factory | **IMPLEMENTED** | Request → plan → build → test → repair → deploy → public browser verification |
| Game Factory | **NOT IMPLEMENTED** | Nothing builds or packages a game |
| Video Factory | **NOT IMPLEMENTED** | No GPU worker; frozen at M013 steps 1–7 |
| YouTube publishing | **NOT IMPLEMENTED** | No connector. Also quota-bound — see `11A` |
| Instagram / TikTok publishing | **NOT IMPLEMENTED** | Requires App Review / audit before any API works |
| Inbox | **NOT IMPLEMENTED** | Gmail *sending* works; nothing receives, classifies or threads |
| Sponsorship CRM | **NOT IMPLEMENTED** | Models only |
| Revenue tracking | **NOT IMPLEMENTED** | No platform reports anything into it |
| Opportunity Factory | **INTEGRATED** | Real discovery (OSM + Places), real evidence, Gmail send proven. Not running autonomously |

---

## Credentials

| Variable | Purpose | Present on server |
|---|---|---|
| `ATLAS_DATABASE_URL` | PostgreSQL | Yes |
| `QEVIK_GOOGLE_PLACES_API_KEY` | Business discovery | Yes |
| `QEVIK_BRAVE_API_KEY` | Web search | Yes |
| `QEVIK_DASHSCOPE_API_KEY` *or* `QEVIK_ANTHROPIC_API_KEY` | Model-driven planning | **No — this is the live blocker** |

All live in `0600` files under `/opt/qevik/`, one per concern, referenced with
`EnvironmentFile=-` so a missing key never fails a unit. **None are in Git**, and
`.gitignore` covers the patterns.

---

## Security posture

- The control API listens on `127.0.0.1:8080` and is **not** reachable from the
  internet. It will stay that way until authentication exists — publishing an
  unauthenticated control plane that can deploy sites and send email is the most
  dangerous single change available in this project.
- The public site host serves static files from `/srv/sites` and has no
  `reverse_proxy` line, so exposing the API cannot happen by editing one file.
- `ufw` allows 22 and 80 only.
- Outward-facing deployment requires an approval object the plan cannot construct
  for itself, checked before any file is read.
- A refusal is never retried as a failure — repairing one would mean attempting
  to publish repeatedly without permission.

---

## The honest summary

The core loop works, publicly, with evidence: a request becomes a plan, the plan
builds and tests a site, repairs it when the tests fail, deploys it to a URL
anyone can open, opens that URL in a real browser and checks what a visitor
receives.

Two things stand between that and the phase's definition of done:

1. **A model credential** — without it the planner is deterministic, so Qevik
   executes autonomously but does not yet *decide* autonomously.
2. **Authentication and a UI** — the loop cannot be driven from a browser
   because the control plane is correctly still closed.

Neither is architecture. Both are next.

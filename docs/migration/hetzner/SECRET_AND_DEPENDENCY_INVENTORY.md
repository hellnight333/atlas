# SECRET_AND_DEPENDENCY_INVENTORY

Phase 0 deliverable 3. **No secret values appear in this document.** Every row
names an identifier or category, where it is consumed, how it is stored today,
whether the migration needs it, the safe way to move it, and what the owner must
do. Evidence: host env-file *names* (`prod-storage.txt`, `prod-caddy-units.txt`
— captured with `cut -d= -f1`), unit files, and the repository at `6ad8a98`.
Values were never read, printed, or copied.

Tags: PROVED / OBSERVED / INFERRED / UNKNOWN as in the inventory.

## 1. Secrets that exist on the production host today

| # | Identifier (name only) | Category | Consumed by | Stored in (host) | Mode | Needed on target? | Safe transfer method | Owner action |
|---|---|---|---|---|---|---|---|---|
| K1 | `ATLAS_DATABASE_URL` | DB DSN (embeds the `qevik` role password) | `qevik-api`, `qevik-control`, 5 workers (via `atlas_kernel.db`), `qevik_backup.sh` | `/opt/qevik/atlas.env` | root 0600 | Yes — **with a new password** | Never copy the old DSN. Owner generates a new password on the target (`ALTER ROLE` there), writes the new DSN into the target's `atlas.env` over an SSH session. The old value is retired at decommission. | Generate + enter new DB password (Phase 3). Old password is **known to be exposed** (argv of stale root processes, `.pgpass`) → rotation is mandatory, not optional. |
| K2 | `QEVIK_CLAIMS_DSN` | DB DSN (same role, PROVED name; whether same password: INFERRED yes) | `qevik-control`, 5 workers (`qevik_mission_claim`) | `/opt/qevik/control.env`, `/opt/qevik/worker.env` | qevik 0600 | Yes — new password | Same as K1; must match K1's role/password. | Same as K1. |
| K3 | `QEVIK_VAULT_MASTER_KEY` | Encryption key (PBKDF2-HMAC-SHA256 sealed `vault.json`, `credentials/vault.py:139-175`) | `qevik-control`, workers | `/opt/qevik/control.env` | qevik 0600 | **Owner decision** — `vault.json` is 2 bytes (OBSERVED), i.e. effectively empty. If the vault has never held a real credential, generate a fresh key and start empty; if it has, the same key must be entered on the target or the file is unreadable. | Owner reads the current value from the old host over SSH and types it into the target's `control.env` (or generates a new one). Never via chat, Markdown, git, or task evidence. | Decide keep-or-regenerate (Phase 3). |
| K4 | `QEVIK_ADMIN_PASSWORD` | Bootstrap admin login (`auth/models.py:209-222`; `infra/rotate_admin.py`) | `qevik-api`/`qevik-control` auth store | `/opt/qevik/atlas.env` | root 0600 | Only for first-boot bootstrap; the hashed user row lives in `qevik_users` and migrates with the DB (INFERRED from `auth/store.py`) | Owner sets a new value on target, or omits it once the DB (with the existing user row) is restored. | Decide: keep existing operator accounts (DB) vs. re-bootstrap. |
| K5 | `QEVIK_DASHSCOPE_API_KEY` (+ `QEVIK_DASHSCOPE_BASE_URL`, not secret) | Third-party LLM API key (Alibaba DashScope) | `qevik-api`, `qevik-control`, workers (`llm/providers.py`) | `/opt/qevik/atlas.env` | root 0600 | Yes | Owner re-enters on target from the provider console (preferred: **issue a new key** and revoke the old at decommission). | Provide / rotate DashScope key (Phase 3). |
| K6 | `QEVIK_BRAVE_API_KEY` | Third-party search API key | `qevik-api` only (`resources.conf` drop-in; `research/brave.py`) | `/opt/qevik/brave.env` | root 0600 | Yes (research recipes) | Re-enter on target from Brave console; rotate at decommission. | Provide Brave key. |
| K7 | `QEVIK_GOOGLE_PLACES_API_KEY` | Third-party API key, **IP-restricted to `2.28.62.83`** (`00_PROJECT_STATE.md:36`) and documented as once exposed in a screenshot (rotation open, `:390-391`) | `qevik-api`, `qevik-market-scan.timer` | `/opt/qevik/places.env` | qevik 0600 | Yes | **Rotate**: create a new key restricted to the *target* IP in Google Cloud console; enter on target. The old key's IP restriction means it will not work from the new host anyway. | Create new restricted key; delete old key after cutover. |
| K8 | `.pgpass` (root) | DB password file for hand `psql` | root shell only | `/opt/qevik/.pgpass` | root 0600 | No (DO_NOT_MIGRATE) | Recreate on target only if the owner wants passwordless `psql` for root; new password. | Optional. |
| K9 | Let's Encrypt account key + 4 certificates/keys | TLS material | Caddy | `/var/lib/caddy/.local/share/caddy/` (certificates/acme-v02…/{qevik.ai,www,app,sites}) | caddy | **Owner decision** (P2 in data inventory): copy for a zero-gap cutover, or re-issue on the target (needs :80 reachable via Cloudflare → only after the origin change) | If copied: `rsync -a` root→root over SSH of `/var/lib/caddy`, chown `caddy:caddy`. | Decide copy vs re-issue (Phase 4). |
| K10 | Caddy internal CA (for `:8443 tls internal` and `127.0.0.1`) | TLS material | Caddy | `/var/lib/caddy/.local/share/caddy/pki/` | caddy | No — REGENERATE | — | — |
| K11 | SSH host keys (`/etc/ssh/ssh_host_*`) | Host identity | sshd | `/etc/ssh` | root | No — the target gets new host keys; the operator's `known_hosts` must be updated | — | Accept new host key fingerprint out-of-band (Hetzner console shows it). |
| K12 | `root` `authorized_keys` (1 ED25519 key, fingerprint `SHA256:VI9x…`, matches `~/.ssh/naml_hetzner` — INFERRED from deploy scripts) | SSH access | sshd | `/root/.ssh/authorized_keys` | root | Yes — same **public** key is fine; **the private key is shared with Naml's host** (ADR-0011:32) | Public key only; owner may choose a dedicated key pair for the new production host. | Decide: reuse `naml_hetzner` or a new production-only key (recommended). |
| K13 | `qevik` deploy key `/home/qevik/.ssh/id_ed25519` (GitHub pull-only, `bootstrap:82-87`) | Git credential | `git` as `qevik` (bootstrap/clone; **not used by any unit** — ADR-0010 deploys via rsync from the Mac) | `/home/qevik/.ssh` | qevik | Probably not (ADR-0010 payload deploy does not clone) — UNKNOWN whether any hand workflow still pulls on-host | Generate a new deploy key on the target and add it to GitHub if needed; never copy the private key. | Decide whether on-host git access is still wanted. |

Present in code but **absent on the host** (no env file, no name in any env file — PROVED by name listing): `QEVIK_CLOUDFLARE_API_TOKEN`, `QEVIK_CLOUDFLARE_ACCOUNT_ID`, all `QEVIK_SMTP_*`, `QEVIK_ANTHROPIC_API_KEY`/`ANTHROPIC_API_KEY`, `QEVIK_OPENAI_API_KEY`, `QEVIK_DEEPSEEK_API_KEY`, `QEVIK_STRIPE_SECRET_KEY`, Google OAuth client/refresh tokens, Instagram/YouTube/Amazon/Noon tokens. **None of these needs to be migrated because none exists.** Whether any of them is *wanted* on the new host is a product decision, not a migration requirement.

## 2. Credentials the migration itself needs that are NOT on the host

| # | Credential / access | Why | Where consumed | Exists today? | Safe provision method |
|---|---|---|---|---|---|
| M1 | **Hetzner Cloud console/API access** for the project that holds `qevik-core-01` (vServer 162146484) | create the production server, firewall, volume/backup add-on; later delete the old server | Owner's browser / owner-run `hcloud` — **never** stored on either server; the repo has no Hetzner API usage (PROVED) | UNKNOWN (owner) | Owner performs provisioning actions personally, or hands a scoped project token to an interactive session and revokes it afterwards. Phase 2 stop point. |
| M2 | **Cloudflare account access** for zone `qevik.ai` (dashboard; token "NOT YET CREATED" per `cloudflare_token.md`) | cutover = change the origin for `qevik.ai`, `www`, `app`, `sites` from `2.28.62.83` to the target; rollback = change it back | Owner's browser | Dashboard: presumably yes (zone is live); API token: UNKNOWN/absent | Owner performs the origin change in the dashboard at the approved cutover moment. No automation will touch DNS. |
| M3 | Domain registrar access for `qevik.ai` (nameservers already at Cloudflare) | not needed unless nameservers change (they don't) | — | UNKNOWN registrar | None required for this migration. |
| M4 | SSH access to the **target** (new root key) | all Phase 2–9 work | operator Mac ↔ target | does not exist yet | Hetzner console injects the chosen public key at creation; private key stays on the operator Mac. |
| M5 | Google Cloud console access (Places key restriction) | K7 rotation | owner browser | assumed yes (key exists) | Owner action only. |
| M6 | DashScope / Brave consoles | K5/K6 rotation (recommended, not strictly required) | owner browser | assumed yes | Owner action only. |
| M7 | GitHub push to `origin` | the repo edits that retarget the origin IP (§14.2 of the inventory) must reach `main` before an ADR-0010 deploy can run against the new host | operator Mac | yes (owner) | Owner pushes; agent never pushes. |

## 3. Non-secret dependencies the target must satisfy

| # | Dependency | Used by | Version on old host (PROVED) | Notes |
|---|---|---|---|---|
| N1 | Ubuntu 26.04 LTS, kernel as shipped | all | 26.04 (`os-release`) | Same major is the least-risk choice; Python 3.14 from distro. |
| N2 | Python | venv | 3.14.4 | `pyproject.toml` lower bounds only; no lock. |
| N3 | PostgreSQL | DB | 18.6 (`postgresql-18 18.6-0ubuntu0.26.04.1`) | `pg_dump -Fc` from 18.6 restores into 18.x; do not go lower. `shared_buffers=128MB`, `max_connections=100` defaults. |
| N4 | Caddy | proxy/TLS | 2.11.4 (distro package) | Config uses `trusted_proxies static`, `disable_tlsalpn_challenge`, `admin off`. |
| N5 | rsync, curl, git, ffmpeg | deploy, workers, market scan | rsync 3.4.1, curl 8.18, ffmpeg 8.0.1 | `ffmpeg` installed by bootstrap; used by Playwright (`ffmpeg-1011`) and media code. |
| N6 | Playwright + Chromium 1234 + headless shell 1234 | `browser/session.py`, evidence capture, healthcheck | 656 MB under `/opt/qevik/ms-playwright` | Not in `pyproject.toml`; install command UNKNOWN → record `pip show playwright` on old host in Phase 4. Needs Chromium's apt deps (`playwright install-deps`). |
| N7 | ufw, unattended-upgrades, fail2ban (**inactive** today) | security | ufw 0.36.2 | Phase 3 decides fail2ban / password-auth off. |
| N8 | Outbound HTTPS to: `dashscope-intl.aliyuncs.com`, `api.search.brave.com`, `places.googleapis.com`, `api.cloudflare.com` (unused today), `acme-v02.api.letsencrypt.org`, `github.com`/`api.github.com`, arbitrary public sites (research/healthcheck/publish verification), Ubuntu mirrors | workers, api, Caddy, apt | ufw default allow-out | Hetzner Cloud Firewall (if used) must allow these outbound. |
| N9 | Inbound: 22 (owner IPs ideally), 80, 443 (Cloudflare ranges ideally) | sshd, Caddy | ufw 22/80/443 any | Recommendation only; today 80/443 are open to the world at the host firewall and Cloudflare is trusted only for `X-Forwarded-For`. |
| N10 | Cloudflare proxy in front of every public hostname | edge | orange-cloud on 4 names (PROVED) | Origin change is the cutover lever. |
| N11 | Time sync (systemd-timesyncd) | timers, ACME, sessions | distro default (INFERRED) | Verify on target. |

## 4. OWNER_INPUT_REQUIRED

Nothing below is needed to finish Phase 0. Each item is needed at the phase
indicated and must be provided by the owner directly on the target host (SSH
session, typed or pasted into a 0600 env file) or performed in the owner's own
browser. **Do not provide any of these values in chat, in a task, in a document,
or in git.**

| # | What | Why | Consumed where | Safe method | Phase |
|---|---|---|---|---|---|
| O1 | Hetzner project access / decision to create the production server (type, location, volume, backups) | provisioning | Hetzner console | owner acts | 2 (STOP before) |
| O2 | New production SSH key pair (or explicit choice to reuse `naml_hetzner`) | target access | Hetzner console (public) / Mac (private) | owner generates | 2 |
| O3 | New `qevik` DB password → `ATLAS_DATABASE_URL`, `QEVIK_CLAIMS_DSN` | K1/K2 rotation | target `atlas.env`, `control.env`, `worker.env` | owner types into target env files | 3 |
| O4 | `QEVIK_VAULT_MASTER_KEY` — keep or regenerate | K3 | target `control.env` | owner reads old value over SSH and re-enters, or generates new | 3 |
| O5 | `QEVIK_DASHSCOPE_API_KEY` (+ base URL), `QEVIK_BRAVE_API_KEY` | K5/K6 | target `atlas.env`, `brave.env` | owner re-enters (rotate recommended) | 3 |
| O6 | New IP-restricted Google Places key | K7 | target `places.env` | owner creates in GCP console, enters on target | 3 |
| O7 | `QEVIK_ADMIN_PASSWORD` policy (keep DB accounts vs re-bootstrap) | K4 | target `atlas.env` | owner decides/enters | 3 |
| O8 | Cloudflare dashboard access at cutover and rollback moments | DNS/origin change | owner browser | owner acts | 9 (STOP before) |
| O9 | Decision: copy LE certs vs re-issue | K9 | target `/var/lib/caddy` | owner decides; if copy, root rsync | 4 |
| O10 | Push of the repo change that retargets `2.28.62.83` → new IP (after review) | M7 | GitHub | owner pushes | 4 |
| O11 | SMTP / mailbox: **not required** for migration (nothing configured today). If the owner wants outbound mail on the new host, that is a new capability: provider, `QEVIK_SMTP_*` values, SPF/DKIM/DMARC DNS records | new feature, not migration | target env + Cloudflare DNS | owner decides separately | out of scope |
| O12 | Confirmation of which hand-copied `/opt/qevik/*.py`/`*.sh` scripts and `qevik_test` DB are still used | A6 / D2 classification | — | owner answers | 5 |

## 5. Handling rules (binding for every later phase)

1. Secrets move **owner → target** only; never old-host → agent → target, never through chat, Markdown, git, task DB, logs, or agent prompts.
2. Env files on the target are created by the owner with `umask 077`; the agent may verify **names and modes** (`cut -d= -f1`, `stat`) but never `cat` them.
3. DSNs are never passed on a command line (the stale `verify_recurrence.py` processes on the old host leak the current one via `ps` — finding F-1 in the risk register). Use `EnvironmentFile=` or `PGPASSFILE`.
4. Every credential that ever lived on the old host is treated as exposed once the old host is decommissioned or earlier; rotation of K1/K2/K5/K6/K7 is part of Phase 3/11, not optional.
5. `vault.json` and `credentials.jsonl` are copied byte-exact with sha256 proof; their contents are never inspected.

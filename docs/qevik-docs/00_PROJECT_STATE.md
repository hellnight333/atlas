# Qevik — Current Project State

**Last consolidated: 2026-08-17**

## Canonical execution environment

**`qevik-core-01` — Hetzner, 2.28.62.83.** Ubuntu 26.04 LTS, 4 vCPU AMD EPYC
Genoa, 8 GB RAM, 150 GB disk. Python 3.14.4.

This is the authoritative server for Qevik Core / control plane / development.
Personal machines are clients.

- Qevik lives at `/opt/qevik/atlas`, owned by a non-root `qevik` user (§28).
- PostgreSQL 16 native, loopback only. Role and database `qevik`.
- Config at `/opt/qevik/atlas.env` (0600, `qevik`). The password exists only
  there and in `/opt/qevik/.pgpass`; it is not in Git and is never printed.
- GitHub access is a **read-only deploy key** — the server can pull, not push.
- `ufw` active, port 22 only.

Reproduce the whole thing with `infra/bootstrap_qevik_server.sh`, which is
idempotent and has been re-run against a live install to prove it. It installs
the service too, so bare server → running system is one script.

### Scheduled, running on their own

- `qevik-market-scan.timer` — 06:00 daily. Answers "which niche, which
  geography" from live data, so nobody has to be asked. Research only: reads
  public pages and Places, contacts nobody, produces no proposals.
- `qevik-backup.timer` — 03:30 daily. Takes a dump **and restores it into a
  scratch database to prove it works**, per §29: a backup that has never been
  restored is not a verified backup. Unverified dumps are kept with an
  `.UNVERIFIED` suffix rather than deleted.

### Google Places

Configured, IP-restricted to the server, key in `/opt/qevik/places.env` (0600,
outside the repo). The client is pinned to IPv4 — a dual-stack host prefers IPv6
and Google then answers `API_KEY_IP_ADDRESS_BLOCKED`, which reads like a wrong
key and is not.

**It was worth paying for, and the numbers say why.** Reachability went from
2–17% on OpenStreetMap to 83–100% on Places. Reachability, not defect rate, was
the constraint that made every market unworkable. A full six-niche scan costs
about $0.58.

### Running services

- `qevik-api` — systemd, enabled at boot, restarts on failure (verified by
  SIGKILL, not by reading the config). `127.0.0.1:8080`, health returns 200.
- `postgresql` — systemd, enabled at boot.
- Only port 22 is publicly reachable. `ufw` active.

**The API is bound to loopback because it has no authentication layer.** Reach
it from a laptop with an SSH tunnel:

```
ssh -N -L 8080:127.0.0.1:8080 root@2.28.62.83
# then http://127.0.0.1:8080/health on the laptop
```

Do not change the bind address without adding auth first — that would publish an
unauthenticated control plane.

### Proven working on the server (not asserted)

LEVEL 3 and LEVEL 4 of the roadmap were driven against the live API:
workspace → project → run → auto-created job → worker polled it → executed →
completed with a provider recorded. Artifacts persist (assets table populated).

This closes these §39 items: Hetzner canonical · Qevik starts reliably ·
PostgreSQL starts reliably · clean DB init · full suite green · Claude Code can
work on the repo · a tracked job can be created · an agent can execute a task ·
logs persisted · artifacts persisted.

**Not yet verified:** survival of an actual reboot. The service is `enabled`, so
the mechanism is right, but nobody has rebooted the box to watch it come back.

**Not** the Naml automation box at 204.168.249.69. That runs 50 production
containers at load ~12 and is a different system.

## Current identity
Working product/brand: **Qevik**.

## Current technical milestone
Google OAuth/Gmail integration has reached a real end-to-end test.

Reported by Claude:
- A real Gmail message was sent through the complete M014 path.
- Approval gate, fingerprint verification, suppression and cooldown executed.
- Duplicate outreach was blocked by a 90-day cooldown.
- Editing a proposal after approval was blocked by fingerprint mismatch.
- Suppressed addresses were blocked.
- Secrets were kept outside the repository and logging was hardened.

## Test state
**Full suite is GREEN on the canonical server as of 2026-08-17.**
- On `qevik-core-01`: 1040 passed, 4 skipped, coverage 92.16% (gate 90%).
- On the Mac: 1040 passed, 4 skipped, coverage 92.13%. The two agree.
- The 4 skips are demo-installer tests that skip once demos exist.

One environment blocker was found and fixed: without `ffmpeg`/`ffprobe`, 85
media tests skip and coverage falls to 88.22% — a red build caused by a missing
binary rather than by any code being wrong. `ffmpeg` is now installed and is in
the bootstrap script.
- Verified twice; the second run shows 1040 passed + 4 skipped, which are
  demo-installer tests that skip once demos exist ("already installed by an
  earlier run"). Benign and expected.
- ruff, tsc, oxlint, rustfmt and clippy all clean.

PostgreSQL was not actually down. The server was running; the role `atlas` and
database `atlas` did not exist, so every connection failed with
`role "atlas" does not exist`. Both were created.

Creating them then exposed a real bug: `init_db()` could not build the schema
from nothing. An `ALTER TABLE atlas_scene_renders` ran before that table's
`CREATE TABLE`, and because the whole of `init_db()` is one transaction, the
failure rolled everything back and left zero tables. Invisible on any database
that already had the table — which was every database anyone had used. Fixed by
moving the ALTER after the CREATE.

## Google credentials
Desktop/installed OAuth client.
Local path:
`~/.qevik/credentials/google_client_secret.json`
Permissions: `600`
First scope:
`https://www.googleapis.com/auth/gmail.send`
Google app remains in Testing.

## Immediate priorities
1. ~~Restore PostgreSQL and run the complete test suite.~~ **Done.**
2. ~~Make Hetzner the canonical environment.~~ **Done 2026-08-17 — `qevik-core-01`.**
3. Decide niche + geography + offer. **← still the blocker, and not a code problem**
4. Run a small, manually approved Opportunity Factory pilot.
3. Run a small, manually approved Opportunity Factory pilot.
4. Set up OpenClaw on a dedicated P520 operator machine.
5. Keep project documentation in Git.
6. Keep broad Atlas → Qevik internal refactoring deferred.

## Deferred
- Broad package/schema/database rename.
- High-volume autonomous prospecting.
- Adding every Google API scope at once.
- Giving agents unrestricted access to personal browser accounts.

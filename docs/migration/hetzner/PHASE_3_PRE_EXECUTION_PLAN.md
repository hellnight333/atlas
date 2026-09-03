# PHASE 3 — PRE-EXECUTION PLAN (infrastructure preparation of `qevik-prod-01`)

**Plan only. Nothing here has been executed.** No host was changed while writing
it: every host fact below comes from a read-only command run on
2026-09-03 22:18 UTC. No secret was requested, created, transferred or handled.
Phase 3 has not started. The DevLoop remains paused (AR-5).

**Baseline.** The approved repository baseline is
**`3103ced656f6e18acf496591c9abe5e525dbd55b`** — the closed ENABLEMENT stage.
This plan is written against that state and supersedes every earlier Phase 3
sketch.

---

## 0. What changed since the earlier Phase 3 drafts (reconciliation with `3103ced`)

| Earlier draft said | Now, at `3103ced` | Effect on this plan |
|---|---|---|
| Phase 3 creates the whole `/var/lib/qevik` + `/srv` skeleton | `infra/install_qevik_infra.sh` owns the skeleton, its ownership, the slice, the drop-in and enablement — and needs the deployed tree | Phase 3 creates **only** the service account and the two directories that must exist before it: the ownership decision is made here, the skeleton is made in Phase 4 by the canonical installer |
| Phase 3 chooses a DB password "that survives a shell" | WS-4 removed shell parsing entirely (`systemd-run --property=EnvironmentFile=`) | The password is **unconstrained**: any bytes a password manager produces. §8 keeps the choice, drops the constraint |
| `MaxAuthTries 3` risks locking out tooling that offers many keys | every deploy path now passes `-o IdentitiesOnly=yes` with a pinned identity from `infra/deploy_targets.conf` | `MaxAuthTries 3` is safe for the tooling; the residual risk is the operator's own interactive `ssh` (§3, D-3.2) |
| Caddy is installed early | `infra/install_caddy.sh` exists, gated on version and `caddy validate` | **Deferred to Phase 4** (constraint 7). Phase 3 installs no Caddy |
| Directory ownership follows the old host (`/opt/qevik` `qevik:qevik 0750`) | `/opt/qevik` holds `backup.env` (the restic repository password) and `install_qevik_infra.sh` never chowns `/opt/qevik` itself | The ownership model is an explicit decision here (§5, D-3.4); default is **root-owned `/opt/qevik`**, which the installer is already compatible with |
| — | `qevik-offsite.timer` is enabled and proving the off-host copy nightly | Every group below states its effect on that timer; none of them touches it |

---

## 1. Objective, boundary and hard constraints

**Objective.** `qevik-prod-01` has the hardened access posture, the resource
baseline and the service account that Phase 4 assumes — and nothing else.

**In scope (the only host changes Phase 3 makes)**

| Group | Change |
|---|---|
| G1 | 2 GB swap file, `vm.swappiness=10` |
| G2 | sshd hardening (key-only, `MaxAuthTries`), under AR-2 |
| G3 | `ufw` enabled as a mirror of the Cloud Firewall |
| G4 | `fail2ban` with an sshd jail |
| G5 | service account `qevik`, and the ownership model for `/opt/qevik` |
| G6 | journald size cap *(optional — default: defer to Phase 10)* |
| G7 | reboot test: everything above survives, and SSH still works |

**Out of scope — not in Phase 3, at all**

- No application deployment, no `deploy_control.sh`, no rehearsal (constraints 1, 2).
- No PostgreSQL installation, no role, no database, no migration (constraint 3).
- No secret created, transferred, read or handled by the agent. §8 is a STOP gate where the **owner** acts (constraints 4, 5).
- No Cloudflare or DNS change (constraint 6).
- No Caddy install or configuration (constraint 7).
- No backup timer enablement; `qevik-backup.timer` is not even installed yet (constraint 8).
- No DevLoop task (constraint 9).
- No change on `qevik-core-01` (AR-4).
- No touch of `/opt/qevik/backups` or the 11 migrated dumps: their archive move is Phase 4, in the order `OFFSITE_BACKUP.md` §10.2 fixes.

---

## 2. Current state of the target (PROVED read-only, 2026-09-03 22:18 UTC)

| Fact | State |
|---|---|
| OS / kernel | Ubuntu 26.04.1 LTS, 7.0.0-30-generic; 0 packages upgradable; no reboot pending |
| Hardware | 8 vCPU · 15 GiB RAM · 301 GB disk, **1.9 GB used** |
| **Swap** | **none**; `/etc/fstab` has no swap entry; `vm.swappiness=60` |
| Users | **`qevik`, `postgres`, `caddy` do not exist**; only `root` |
| sshd | `passwordauthentication yes` · `permitrootlogin prohibit-password` · `kbdinteractiveauthentication no` · `pubkeyauthentication yes` · `maxauthtries 6` · `usepam yes`; `/etc/ssh/sshd_config.d/` is **empty**; `Include /etc/ssh/sshd_config.d/*.conf` is line 24 of `sshd_config` |
| ssh units | **`ssh.socket` enabled and active; `ssh.service` disabled** — socket activation, so each connection starts `sshd` fresh and reads the config then |
| `authorized_keys` | one line, `qevik_prod` (ED25519) |
| Host firewall | `ufw` **inactive**; ingress governed by the Hetzner Cloud Firewall: 22/80/443 + ICMP (PROVED from the second vantage, `evidence/phase-2/`) |
| fail2ban | not installed; candidate `1.1.0-9`; `/var/log/auth.log` exists (2.0 MB) |
| `/opt/qevik` | `root:root 0755`; `backup.env` root 0600; `backups/` root 0700 with the **11 migrated dumps** |
| `/var/lib/qevik` | `root:root 0755`, holds `backup/` only |
| qevik units | `qevik-offsite.{service,timer}` + `qevik-backup-failed@.service`; the timer is **enabled**; last run `result: ok`, `restore_verified: … sha256 match` |

---

## 3. SSH lockout-safe hardening (G2) — the procedure, before the commands

**AR-2 is mandatory and is the reason this group is written first.** Every
command that can affect SSH access has its recovery path listed *before* it.

**Standing recovery paths, in force for the whole phase**

| # | Path | Why it works |
|---|---|---|
| R1 | **Session A** — an SSH session opened before the first change and never closed. Every rollback below can be typed into it | A live session survives a broken sshd config; only *new* connections are affected |
| R2 | **A dead-man timer** — before each risky change: `systemd-run --on-active=10min --unit=qevik-undo-<group> /bin/sh -c '<undo>'`, cancelled with `systemctl stop qevik-undo-<group>.timer` only after a fresh session proves the change | The host repairs itself if the operator is disconnected mid-change |
| R3 | **Hetzner web console** (VNC) — break-glass, independent of sshd and of both firewalls | D-D chose this over IP-restricted SSH precisely because the owner's egress IP is unstable |
| R4 | **Hetzner rescue system** — boots a different OS with the disk mounted | Recovers even from a broken `/etc/fstab` or unit |
| R5 | **Cloud Firewall** still allows 22 from anywhere; a `ufw` mistake cannot be compounded by the cloud layer | D-D staged the tightening deliberately |

**The AR-2 sequence for G2, exactly**

1. **Session A** open, and stays open until step 8.
2. Capture the baseline: `sshd -T | sort > /root/sshd-T.before`.
3. Arm the dead-man (R2) with the undo for this group.
4. Write the drop-in (`/etc/ssh/sshd_config.d/10-qevik-hardening.conf`).
5. `sshd -t` — a syntax check that must pass **before** anything takes effect.
6. **Session B**: from the Mac, a *fresh* `ssh -i ~/.ssh/qevik_prod -o IdentitiesOnly=yes root@…  'echo B-OK; id'`. Under socket activation the new config is already live for this connection, so B is the proof.
7. Negative control from the second vantage (`qevik-core-01`, read-only carve-out U16): `ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no root@91.107.244.253` must be **refused**, and a key-less attempt must fail.
8. **Session C**: another fresh session with the key. Only then cancel the dead-man and close A.

> **Socket-activation note (new since the earlier drafts).** `ssh.service` is
> disabled and `ssh.socket` is enabled, so there is no daemon holding the old
> config: the drop-in applies to the *next* connection. `systemctl reload ssh`
> is therefore not the lever it is on a classic setup — `sshd -t` plus session B
> is. `systemctl restart ssh.socket` is **not** run: it would drop the listener
> briefly for no benefit.

**D-3.2 (owner decision).** `MaxAuthTries 3` vs leaving 6.
Recommended: **3**. The deploy tooling now pins its identity
(`IdentitiesOnly=yes`, `infra/deploy_targets.conf`), so it offers exactly one
key. The residual risk is an interactive `ssh` from a Mac whose agent holds
several keys: add `IdentitiesOnly yes` to the `qevik-prod-01` block in
`~/.ssh/config` first. If the owner prefers no client-side prerequisite, 6 is
acceptable and fail2ban carries the load.

---

## 4. Firewall — exact rules (G3)

`ufw` mirrors the Cloud Firewall; the cloud layer stays the authoritative one
(D-D). Nothing listens on 80/443 until Phase 4, and opening them now is
deliberate: it keeps the two layers identical, and a rule added under load is a
rule added in a hurry.

| Direction | Rule | Reason |
|---|---|---|
| in | `22/tcp` ALLOW from anywhere | the only administrative path (R3/R4 aside) |
| in | `80/tcp` ALLOW from anywhere | ACME HTTP-01 and the Cloudflare origin, from Phase 4 |
| in | `443/tcp` ALLOW from anywhere | the origin, from Phase 9 |
| in | ICMP echo | already permitted by `ufw`'s `before.rules`; keep |
| in | everything else | DENY (default) |
| out | everything | ALLOW (default) — DashScope, Brave, Places, Let's Encrypt, the Storage Box (SFTP 23), apt, GitHub |
| logging | `ufw logging low` | enough to see drops, not enough to fill the journal |

**Not now:** restricting 80/443 to Cloudflare ranges, and restricting 22 by IP.
Both are D-Q, Phase 10, and both are lockout risks today (unstable egress IP,
and a range typo becomes a 521 at cutover).

**Outbound port 23 (Storage Box SFTP) must keep working** — the off-host backup
runs nightly at 04:15 UTC. Default-allow-outgoing covers it; §4's validation
proves it rather than assuming it.

---

## 5. Users, ownership and the directory skeleton (G5)

**Only one account is created in Phase 3.** `postgres` and `caddy` are created
by their own packages in Phase 4 (`postgresql-18`, the Caddy package); creating
them by hand would give them the wrong shell, home or uid and is not needed.

| Account | Created by | Shell | Home | Purpose |
|---|---|---|---|---|
| `qevik` | **Phase 3**, `useradd --system` | `/usr/sbin/nologin` *(D-3.3)* | `/home/qevik`, mode 0750 | runs `qevik-api`, `qevik-control`, the five workers, `qevik-backup` |
| `postgres` | Phase 4, `apt install postgresql-18` | package default | package default | database superuser, local peer only |
| `caddy` | Phase 4, the Caddy package | `/usr/sbin/nologin` | `/var/lib/caddy` | the proxy; owns the certificate store |
| `root` | — | — | — | sshd, the deploy (ADR-0010), `qevik-offsite.service` |

**D-3.3 (owner decision).** `nologin` vs `/bin/bash` for `qevik`.
Recommended: **`nologin`**. Nothing needs an interactive shell: systemd units do
not use one, and `runuser -u qevik -- <cmd>` and `sudo -u qevik <cmd>` both work
without one (Phase 4 creates the venv that way). The cost is that
`sudo -iu qevik` will not work for ad-hoc debugging; `runuser -u qevik -- bash`
still does when the operator wants it. The old host uses `/bin/bash` with uid
1000 — parity is not required and the plan says so rather than copying it.

**D-3.4 (owner decision).** Ownership of `/opt/qevik` itself.

| Option | Consequence |
|---|---|
| **A — `root:root 0755` (recommended, and what the host already has)** | `/opt/qevik/backup.env` (the restic repository password) cannot be unlinked or replaced by the `qevik` account, so a compromised worker cannot redirect the off-host backup. `install_qevik_infra.sh` never chowns this directory, and every path the services write to is a `qevik`-owned subdirectory (`atlas/`, `backups/`, `market/`), so nothing breaks |
| B — `qevik:qevik 0750` (old-host parity) | Same as production today, including production's exposure: write permission on the directory is permission to replace the files in it |

Everything below `/opt/qevik` and all of `/var/lib/qevik` and `/srv` is created
**in Phase 4** by `infra/install_qevik_infra.sh`, which is now the single
implementation of that layout (D-S6). Phase 3 creates only:

| Path | Owner | Mode | Why in Phase 3 |
|---|---|---|---|
| `/opt/qevik` | per D-3.4 (default `root:root`) | 0755 | already exists; the decision is recorded, not re-applied |
| `/home/qevik` | `qevik:qevik` | 0750 | created by `useradd -m`; nothing writes there, it exists so the account is well-formed |

`/opt/qevik/backups` and its 11 migrated dumps are **not touched**: their
ownership change and the archive move belong to Phase 4, in the order fixed in
`OFFSITE_BACKUP.md` §10.2 (deploy → re-run `install_offsite_backup.sh` → move →
confirm `--status` still proves a `sha256 match`).

---

## 6. Execution order, with the commands, validation and rollback

Every group: arm the recovery, change, **validate**, then either keep or roll
back. No group starts until the previous one has been validated.

### STOP GATE 3-A — owner GO to begin Phase 3

Nothing below runs without it. The GO should also answer **D-3.2** (MaxAuthTries),
**D-3.3** (`qevik` shell) and **D-3.4** (`/opt/qevik` ownership).

---

### G0 — baseline capture (read-only, no change)

```
ssh qevik-prod-01 'sshd -T | sort > /root/phase3-sshd.before; \
  ufw status verbose > /root/phase3-ufw.before 2>&1; \
  swapon --show > /root/phase3-swap.before; cp /etc/fstab /root/phase3-fstab.before; \
  sysctl vm.swappiness >> /root/phase3-swap.before; \
  systemctl list-unit-files "qevik-*" > /root/phase3-units.before; \
  /usr/local/sbin/qevik_offsite.sh --status > /root/phase3-offsite.before'
```

*Validation:* the five files exist and are non-empty.
*Rollback:* none needed (reads only; the files are the rollback references).

---

### G1 — 2 GB swap

*Recovery armed first:* none required — swap cannot affect SSH; a bad `/etc/fstab`
can affect **boot**, which is why the fstab line is validated with `mount -a`
equivalent (`findmnt --verify`) before the reboot in G7, and R4 recovers it.

```
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
cp /etc/fstab /etc/fstab.phase3.bak
printf '/swapfile none swap sw 0 0\n' >> /etc/fstab
printf 'vm.swappiness=10\n' > /etc/sysctl.d/60-qevik-swap.conf
sysctl --system | grep -A1 60-qevik-swap
```

*Validation:*
```
swapon --show                 # /swapfile, 2G, prio -2
free -h | awk '/Swap/'        # total 2.0Gi
sysctl -n vm.swappiness       # 10
findmnt --verify --verbose | tail -3   # fstab parses
```
*Rollback:* `swapoff /swapfile; rm -f /swapfile; cp /etc/fstab.phase3.bak /etc/fstab; rm -f /etc/sysctl.d/60-qevik-swap.conf; sysctl --system`

---

### G2 — sshd hardening  ⚠ affects SSH access

*Recovery armed first (R1 + R2), in this order:*
```
# Session A stays open in another terminal.
systemd-run --on-active=10min --unit=qevik-undo-sshd \
  /bin/sh -c 'rm -f /etc/ssh/sshd_config.d/10-qevik-hardening.conf'
```

```
cat > /etc/ssh/sshd_config.d/10-qevik-hardening.conf <<'EOF'
# Phase 3 (AR-2). Key-only administrative access.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
MaxAuthTries 3
EOF
chmod 644 /etc/ssh/sshd_config.d/10-qevik-hardening.conf
sshd -t && echo "config valid"
```

*Validation (the AR-2 proof, all four parts):*
```
sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|maxauthtries|permitrootlogin)'
# session B, from the Mac, a FRESH connection:
ssh -i ~/.ssh/qevik_prod -o IdentitiesOnly=yes -o BatchMode=yes root@91.107.244.253 'echo B-OK; id -un'
# negative control, from the second vantage (qevik-core-01, read-only):
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no -o StrictHostKeyChecking=no \
    -o ConnectTimeout=10 root@91.107.244.253 true    # must fail: "Permission denied (publickey)"
# session C, another fresh connection with the key, before A is closed
```
*Keep:* `systemctl stop qevik-undo-sshd.timer 2>/dev/null; systemctl reset-failed qevik-undo-sshd.service 2>/dev/null`
*Rollback:* in **session A** — `rm -f /etc/ssh/sshd_config.d/10-qevik-hardening.conf` (takes effect on the next connection; no restart needed under socket activation). If session A is lost: the dead-man timer does it, and R3 is the floor.

---

### G3 — ufw ⚠ affects SSH access

*Recovery armed first:*
```
systemd-run --on-active=10min --unit=qevik-undo-ufw /bin/sh -c 'ufw --force disable'
```
Session A open throughout.

```
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'ssh (admin)'
ufw allow 80/tcp comment 'ACME + Cloudflare origin (from Phase 4)'
ufw allow 443/tcp comment 'Cloudflare origin (from Phase 9)'
ufw logging low
ufw --force enable
```

*Validation:*
```
ufw status verbose                    # active, deny(incoming) allow(outgoing), 22/80/443 v4+v6
ss -tlnp | awk 'NR==1||/:22 /'        # sshd still listening
# session B, a FRESH connection from the Mac: must succeed
# outbound still open — the off-host backup depends on it:
nc -vz -w 5 u662608.your-storagebox.de 23   # succeeded
getent hosts dashscope-intl.aliyuncs.com >/dev/null && echo dns-ok
# second vantage (read-only) confirms nothing new is exposed:
#   22 open · 80/443 closed (nothing listening yet) · 8443, 5432 filtered
```
*Keep:* stop the dead-man timer, as in G2.
*Rollback:* `ufw --force disable` (session A, or the timer, or R3).

---

### G4 — fail2ban

Ordered **after** ufw so `banaction = ufw` is valid on first start.

```
DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban
cat > /etc/fail2ban/jail.d/qevik.local <<'EOF'
[DEFAULT]
# Bans are a nuisance control, not the access control: password auth is off, so
# these attempts cannot succeed. Ban long enough to cut the noise, short enough
# that a mistyped key from a changing egress IP is not a half-day lockout.
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd
banaction = ufw
# Never ban the host itself; no operator IP is listed, because the owner's
# egress IP is not stable (D-D) and a stale allow-list is worse than none.
ignoreip = 127.0.0.1/8 ::1

[sshd]
enabled = true
EOF
systemctl enable --now fail2ban
```

*Validation:*
```
systemctl is-active fail2ban                 # active
fail2ban-client status sshd                  # jail exists, filter systemd, 0 or more banned
fail2ban-client get sshd banaction           # ufw
journalctl -u fail2ban -n 20 --no-pager      # no "Failed to ..." lines
# session B, a fresh connection: still works
```
*Rollback:* `systemctl disable --now fail2ban; rm -f /etc/fail2ban/jail.d/qevik.local` (and `apt-get purge -y fail2ban` if the package itself is unwanted). **If the operator is ever banned:** R3, then `fail2ban-client set sshd unbanip <ip>`.

---

### G5 — the service account

```
useradd --system --create-home --home-dir /home/qevik \
        --shell /usr/sbin/nologin --comment 'Qevik services' qevik      # per D-3.3
chmod 750 /home/qevik
# /opt/qevik ownership per D-3.4 — default A leaves it exactly as it is:
stat -c '%n %U:%G %a' /opt/qevik
```

*Validation:*
```
id qevik                                   # uid/gid, no supplementary groups
getent passwd qevik                        # shell is /usr/sbin/nologin
stat -c '%n %U:%G %a' /home/qevik          # qevik:qevik 750
runuser -u qevik -- id -un                 # qevik   (proves nologin does not block the units' pattern)
stat -c '%n %U:%G %a' /opt/qevik /opt/qevik/backup.env
ls /opt/qevik/backups | wc -l              # still 11 — untouched
```
*Rollback:* `userdel -r qevik` (nothing owns files as `qevik` yet, which is why this group is safe to reverse at this point and not later).

---

### G6 — journald cap *(optional; default: defer to Phase 10)*

Included for completeness because D-P names it. If the owner wants it now:
```
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=1G\n' > /etc/systemd/journald.conf.d/60-qevik.conf
systemctl restart systemd-journald
```
*Validation:* `journalctl --disk-usage`; `systemd-analyze cat-config systemd/journald.conf | grep SystemMaxUse`
*Rollback:* `rm /etc/systemd/journald.conf.d/60-qevik.conf; systemctl restart systemd-journald`

---

### STOP GATE 3-B — before the reboot

Report G1–G5 evidence to the owner. The reboot is the first moment a mistake in
`/etc/fstab`, `ufw` or sshd becomes a *boot* problem rather than a session
problem, so it is a gate, not a step.

---

### G7 — reboot test

*Recovery:* R3 (console) and R4 (rescue). `findmnt --verify` in G1 is what makes
this low-risk.

```
systemctl reboot
# wait, then from the Mac:
ssh -i ~/.ssh/qevik_prod -o IdentitiesOnly=yes root@91.107.244.253 'uptime; \
  swapon --show; ufw status | head -1; systemctl is-active fail2ban; id qevik; \
  systemctl list-timers qevik-offsite.timer --no-pager'
```

*Validation:* session opens with the key; swap present; `ufw` active; fail2ban
active; `qevik` exists; **`qevik-offsite.timer` is still enabled with a future
next-run**, and `/usr/local/sbin/qevik_offsite.sh --status` still reports
`result: ok`.
*Rollback:* none required — a reboot is not a change; if the host does not
return, R3 then R4.

---

## 7. Validation summary (what "Phase 3 is done" means)

| # | Check | Expected |
|---|---|---|
| P3-1 | `sshd -T` diff vs `/root/phase3-sshd.before` | exactly four lines changed: password/kbd/maxauthtries (+ permitrootlogin unchanged) |
| P3-2 | password auth from the second vantage | refused |
| P3-3 | key auth from the Mac, fresh session | works, three times (B, C, post-reboot) |
| P3-4 | `ufw status verbose` | active; deny incoming; 22/80/443 allowed v4+v6 |
| P3-5 | second-vantage port scan | 22 open · 80/443 closed (nothing listening) · everything else filtered |
| P3-6 | `fail2ban-client status sshd` | jail active, `banaction ufw`, systemd backend |
| P3-7 | `swapon --show`, `sysctl vm.swappiness` | 2 GB, 10 — and after the reboot |
| P3-8 | `id qevik`, `runuser -u qevik -- id -un` | exists, `nologin`, usable by the units' pattern |
| P3-9 | `/opt/qevik` and `backup.env` | unchanged owner/mode; 11 dumps still present |
| P3-10 | `qevik_offsite.sh --status` | `result: ok`, `restore_verified … sha256 match` — before and after the reboot |
| P3-11 | no PostgreSQL, no Caddy, no venv, no `qevik-api` | `dpkg -l` and `systemctl list-unit-files 'qevik-*'` unchanged apart from nothing |
| P3-12 | evidence written | `docs/migration/hetzner/evidence/phase-3/` — names, modes, `sshd -T` diff, session A/B/C timestamps; **no secret values** |

---

## 8. STOP GATE 3-C — secrets are the owner's, and they come last

Phase 3 **ends** here. The agent does not create, read, transfer, generate or
verify the *value* of anything below; it may verify **names and modes only**
(`cut -d= -f1`, `stat`), as it did for `backup.env`.

| File | Mode/owner | Keys (names only) | When it can be written |
|---|---|---|---|
| `/opt/qevik/atlas.env` | `root:root 0600` | `ATLAS_DATABASE_URL`, `QEVIK_DASHSCOPE_API_KEY`, `QEVIK_DASHSCOPE_BASE_URL`, `QEVIK_ADMIN_PASSWORD`, `QEVIK_SITES_BASE_URL`, `QEVIK_LEDGER`, `QEVIK_REPORTS_STORE` | see the sequencing note |
| `/opt/qevik/control.env` | `qevik:qevik 0600` | `QEVIK_VAULT_MASTER_KEY`, `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` | after the role exists |
| `/opt/qevik/worker.env` | `qevik:qevik 0600` | `QEVIK_CLAIMS_DSN`, `QEVIK_REQUIRE_ATOMIC_CLAIMS` | after the role exists |
| `/opt/qevik/brave.env` | `root:root 0600` | `QEVIK_BRAVE_API_KEY` | any time after G5 |
| `/opt/qevik/places.env` | `qevik:qevik 0600` | `QEVIK_GOOGLE_PLACES_API_KEY` | any time after G5 — **must be a new key restricted to `91.107.244.253`** (SR-5); the current one is pinned to the old IP and will fail here |

**Sequencing note (a real ordering problem, not a formality).** The DSNs name a
password that belongs to a database role, and Phase 3 creates no database
(constraint 3). Two ways, owner's choice:

- **(a) recommended** — the owner chooses the password now (**any characters:
  WS-4 removed the shell entirely**), stores it in the password manager, writes
  the env files once at this gate, and Phase 4 sets *that* password on the role
  with `\password qevik`;
- (b) the owner writes the non-database files now (`brave.env`, `places.env`)
  and the DSN-bearing files in Phase 4 immediately after the role is created.

Either way the agent never sees a value, and no credential is rotated in Phase 3:
K5/K6/K7 rotation happens when the owner writes these files, and the *old* host's
credentials are not touched until Phase 11 (rotating them earlier breaks
rollback).

### STOP GATE 3-D — before Phase 4

Phase 4 begins only on a separate owner GO, and only after: this plan's
validation table is green, the env files are in place (names and modes verified),
and `MIGRATION_ENABLEMENT_SPEC.md` §13b's ordering constraint is carried into the
Phase 4 runbook.

---

## 9. Every reversible change, in one table

| Group | Change | Rollback | Recovery if SSH is lost |
|---|---|---|---|
| G1 | swap file, fstab line, sysctl file | `swapoff` + `rm` + restore `fstab.phase3.bak` + `rm` sysctl file | R4 (fstab is the only boot-affecting file) |
| G2 | sshd drop-in | `rm` the drop-in — effective on the next connection | R1 session A · R2 dead-man · R3 console |
| G3 | ufw rules + enable | `ufw --force disable` | R1 · R2 · R3 · R5 (cloud layer unchanged) |
| G4 | fail2ban package + jail | `systemctl disable --now fail2ban`, `rm` jail, optional purge | R3, then `unbanip` |
| G5 | `qevik` account + home | `userdel -r qevik` | n/a (cannot affect SSH) |
| G6 | journald cap | `rm` the drop-in, restart journald | n/a |
| G7 | reboot | n/a | R3 then R4 |

Whole-phase rollback: every item above, in reverse; and if that is ever
insufficient, the Phase 2 rollback (a free console rebuild) still applies —
nothing in Phase 3 is expensive to recreate, and the target holds no production
data.

---

## 10. Risks specific to this phase

| # | Risk | Handling |
|---|---|---|
| 1 | Lockout from a bad sshd config | AR-2's four proofs + dead-man + console; `sshd -t` before anything |
| 2 | Lockout from `ufw` | dead-man + session A; the cloud firewall is unchanged and still permits 22 |
| 3 | fail2ban bans the operator's changing egress IP | password auth is off, so bans need repeated *key* failures; `unbanip` via console; `bantime` 1h, not permanent |
| 4 | `MaxAuthTries 3` breaks an agent-heavy client | `IdentitiesOnly yes` in `~/.ssh/config` (the deploy tooling already does this); or D-3.2 = 6 |
| 5 | The nightly off-host backup breaks | it runs as root over outbound 23; `ufw` allows outgoing; P3-10 proves it before and after the reboot |
| 6 | fstab typo → the host does not boot | `findmnt --verify` before G7; R4 rescue |
| 7 | Scope creep into Phase 4 | §1's out-of-scope list, and the fact that the skeleton, Caddy, Postgres and the venv all now live in scripts that Phase 3 does not run |

---

## 11. Stop

This plan is presented for approval. Nothing in it has been executed: no host
change, no package, no user, no firewall rule, no secret, no database, no
deployment, no DevLoop task. Phase 3 begins at **STOP GATE 3-A**, on an explicit
owner GO that also answers D-3.2, D-3.3 and D-3.4.

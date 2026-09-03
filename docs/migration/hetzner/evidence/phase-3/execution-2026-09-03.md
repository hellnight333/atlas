# Phase 3 — execution evidence (2026-09-03 22:25–22:36 UTC)

Executed against `qevik-prod-01` per `PHASE_3_PRE_EXECUTION_PLAN.md`
(approved at `1afef99`), on the repository baseline `3103ced`.
Names, modes, versions and states only — **no secret value appears here**, and
none was created, read, transferred or handled. No application, database, Caddy,
venv or deployment was introduced; the backup timer was not enabled.

Decisions executed at the plan's documented defaults: **D-3.2** MaxAuthTries 3
(the operator's `~/.ssh/config` already pins `IdentitiesOnly yes` for this host),
**D-3.3** `qevik` shell `/usr/sbin/nologin`, **D-3.4** option A — `/opt/qevik`
stays `root:root 0755` so the service account cannot reach `backup.env`.

## Two corrections the host forced (owner-accepted 2026-09-04)

**C-1 — sshd needs a reload.** The plan's §3 said socket activation makes each
connection read the config, so no reload was needed. The host disproved it:
`ss -tlnp` showed a persistent `sshd` (pid 1098) holding `:22` since boot —
`ssh.socket` starts `ssh.service` once and that daemon serves every connection.
The drop-in was on disk and `sshd -T` reported it, while the running daemon still
advertised `publickey,password`. `systemctl reload ssh.service` (whose
`ExecReload` runs `sshd -t` first, then `kill -HUP`) applied it; only after that
did the negative control show `Authentications that can continue: publickey`.
**The dead-man timer was re-armed to include the reload in its undo before the
change was applied**, so the recovery path matched the real model.

**C-2 — fail2ban bans through nftables, not ufw.** `banaction = ufw` in
`jail.d/qevik.local` did not take effect: `jail.d/defaults-debian.conf` sets
`banaction = nftables` and that is what the jail loaded. Bans live in the
`inet f2b-table` and are read with `fail2ban-client get sshd banned`, not
`ufw status`. Both are evaluated and a drop in either drops. The jail file now
documents the real behaviour rather than asserting the setting that did nothing.

## AR-2 proof chain (G2)

| Step | Result |
|---|---|
| Session A (multiplexed master, opened before any change) | live throughout; every rollback typed there |
| Dead-man armed | `qevik-undo-sshd.timer`, 10 min, undo = remove drop-in **+ reload** |
| `sshd -t` | valid, before the reload |
| Session B (fresh, `-i qevik_prod -o IdentitiesOnly=yes`) | `B-OK 2026-09-03T22:29:08Z` |
| Negative control, second vantage (`qevik-core-01`, nothing written there) | `Authentications that can continue: publickey` · `Permission denied (publickey)` |
| Session C (fresh) | `C-OK 2026-09-03T22:29:25Z` |
| Dead-man cancelled, session A closed | after C |

## Post-reboot validation (G7 — boot id `dd40a744…`, 4th boot)

| # | Check | Result |
|---|---|---|
| P3-1 | `sshd -T` vs baseline | exactly two lines: `maxauthtries 6→3`, `passwordauthentication yes→no` |
| P3-2 | password auth, second vantage | refused — `publickey` only |
| P3-3 | key auth, fresh sessions | B, C and post-reboot all succeeded |
| P3-4 | `ufw status verbose` | active · deny incoming / allow outgoing · 22/80/443 v4+v6 |
| P3-5 | second-vantage ports | 22 open · 80/443 closed (nothing listening) · 8443/5432 filtered · ICMP reply |
| P3-6 | fail2ban | active + enabled, sshd jail, systemd backend, 3600/600/5, action `nftables` (C-2), 2 brute-force IPs banned, 0 errors |
| P3-7 | swap | 2 GB active, `vm.swappiness=10`, `swapfile.swap` active after reboot |
| P3-8 | `qevik` account | uid 999, `nologin`, `/home/qevik` 0750, `runuser -u qevik` works |
| P3-9 | `/opt/qevik` | unchanged `root:root 0755`; `backup.env` root 0600 unreadable by `qevik`; 11 migrated dumps present |
| P3-10 | off-host backup | `result: ok`, `restore_verified … sha256 match`; timer enabled, next 2026-09-04 04:18 UTC |
| P3-11 | Phase 4 absent | no postgresql-18, caddy, python3-venv/pip, ffmpeg, nodejs; no `/opt/qevik/atlas`; `/srv` empty; only `backup.env` present |
| P3-12 | evidence | this file — no secret values |

## Rollback readiness

`/root/phase3-{sshd,ufw,swap,fstab,units,offsite,paths}.before` and
`/etc/fstab.phase3.bak` are on the host. Per group: swap → `swapoff` + `rm` +
restore fstab + remove sysctl file; sshd → remove the drop-in **and reload**;
ufw → `ufw --force disable`; fail2ban → `systemctl disable --now` + remove the
jail; account → `userdel -r qevik`. Whole-phase fallback: the Phase 2 console
rebuild, which costs nothing to redo — the host still holds no production data.

---

## Raw host output

```
## sshd -T diff (baseline -> after)
57c57
< maxauthtries 6
---
> maxauthtries 3
62c62
< passwordauthentication yes
---
> passwordauthentication no

## sshd drop-in
/etc/ssh/sshd_config.d/10-qevik-hardening.conf root:root 644 182 bytes
# Phase 3 (AR-2). Key-only administrative access.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
MaxAuthTries 3

## ssh units
disabled enabled 
{ path=/usr/sbin/sshd ; argv[]=/usr/sbin/sshd -t ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }
{ path=/bin/kill ; argv[]=/bin/kill -HUP $MAINPID ; ignore_errors=no ; start_time=[n/a] ; stop_time=[n/a] ; pid=0 ; code=(null) ; status=0/0 }

## swap
NAME      TYPE SIZE USED PRIO
/swapfile file   2G   0B   -1
vm.swappiness=10
/swapfile none swap sw 0 0
active

## ufw
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere                   # ssh (admin)
80/tcp                     ALLOW IN    Anywhere                   # ACME + Cloudflare origin (from Phase 4)
443/tcp                    ALLOW IN    Anywhere                   # Cloudflare origin (from Phase 9)
22/tcp (v6)                ALLOW IN    Anywhere (v6)              # ssh (admin)
80/tcp (v6)                ALLOW IN    Anywhere (v6)              # ACME + Cloudflare origin (from Phase 4)
443/tcp (v6)               ALLOW IN    Anywhere (v6)              # Cloudflare origin (from Phase 9)


## fail2ban
fail2ban 1.1.0-9
active
enabled
Status for the jail: sshd
|- Filter
|  |- Currently failed:	0
|  |- Total failed:	0
|  `- Journal matches:	_SYSTEMD_UNIT=ssh.service + _COMM=sshd
`- Actions
   |- Currently banned:	1
   |- Total banned:	2
   `- Banned IP list:	45.148.10.183
The jail sshd has the following actions:
nftables
bantime=3600 findtime=600 maxretry=5

## accounts and ownership
qevik:x:999:983:Qevik services:/home/qevik:/usr/sbin/nologin
uid=999(qevik) gid=983(qevik) groups=983(qevik)
/home/qevik qevik:qevik 750
/opt/qevik root:root 755
/opt/qevik/backup.env root:root 600
/opt/qevik/backups root:root 700
/var/lib/qevik root:root 755
dumps=11

## off-host backup
{"unit":"qevik-offsite","host":"qevik-prod-01","last_run_utc":"2026-09-03T16:26:43Z","result":"ok","snapshot":"ed2b42b1","restore_verified":"qevik-20260903T033126Z.dump sha256 match","check":"ok(5%)","repository":"sftp:…","keep":"daily=30,weekly=8,monthly=6","duration_s":9,"note":""}
Fri 2026-09-04 04:18:00 UTC 5h 41min Thu 2026-09-03 11:03:27 UTC      - qevik-offsite.timer qevik-offsite.service

## units
UNIT FILE                    STATE   PRESET
qevik-backup-failed@.service static  -
qevik-offsite.service        static  -
qevik-offsite.timer          enabled enabled

3 unit files listed.

## absent (Phase 4 has not begun)
  postgresql-18: not-installed
  caddy: absent
  python3-venv: not-installed
  python3-pip: absent
  ffmpeg: absent
  nodejs: absent
  /opt/qevik/atlas: absent
  /srv entries: 0
  env files: /opt/qevik/backup.env 

## boot
2026-09-03 22:34:42
 -1 89bb03636f254bfeab1122bedfe082dc Thu 2026-09-03 10:27:49 UTC Thu 2026-09-03 22:34:35 UTC
  0 dd40a7449e8c4d51a5d9eecc9ea7a37e Thu 2026-09-03 22:34:45 UTC Thu 2026-09-03 22:36:26 UTC

## rollback references
/etc/fstab.phase3.bak
/root/phase3-fstab.before
/root/phase3-offsite.before
/root/phase3-paths.before
/root/phase3-sshd.before
/root/phase3-swap.before
/root/phase3-ufw.before
/root/phase3-units.before
```

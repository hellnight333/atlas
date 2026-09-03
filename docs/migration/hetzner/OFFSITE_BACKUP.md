# Off-host backup — Qevik production → Hetzner Storage Box

Status: **INSTALLED on `qevik-prod-01` 2026-09-03**; see §10 for what is PROVED and what
waits on data that is still on the old host. Evidence: `evidence/backup/`.

This closes risk **F-6** (the old host's only backups sit on the same disk as the
database, and a five-day silent failure once went unnoticed) and delivers migration
items **T2** (off-host copy) and the `OnFailure=` half of **T9**. Nothing here changes
the old host (AR-4) and nothing here adds infrastructure beyond one apt package (AR-3).

## 1. Architecture

```
qevik-prod-01 (91.107.244.253)                      Storage Box BX11 "qevik-prod-storage"
                                                    u662608.your-storagebox.de:23
03:30 UTC qevik-backup.timer  → qevik-backup.service (User=qevik, existing)
   pg_dump -Fc → verify by pg_restore → /opt/qevik/backups (keep 14)
   OnFailure= ─────────────────────────────┐
04:15 UTC qevik-offsite.timer → qevik-offsite.service (root)         ┌────────────────────┐
   /usr/local/sbin/qevik_offsite.sh                                  │ sub-account         │
     restic backup ── sftp, key /root/.ssh/storagebox_ed25519 ─────► │ u662608-sub1        │
     restic forget --keep-daily 30 --keep-weekly 8 --keep-monthly 6  │ /qevik-prod-backup/ │
     restic check --read-data-subset=5%                              │   restic/  (repo)   │
     restore newest dump from repo → sha256 == local                 └────────────────────┘
     status.json ; clear FAILED                                       encrypted client-side
   OnFailure= ─────────────────────────────┤                          (AES-256, restic)
                                           ▼
                        qevik-backup-failed.service → /var/lib/qevik/backup/FAILED
Hetzner image backups (console add-on, daily, 7 rotations) — whole-VM restore, 2–4 h
```

Two layers, two failure modes:

| Layer | Answers | Restore time | Survives |
|---|---|---|---|
| Hetzner image backup | "the VM broke / bad upgrade / disk died" | 2–4 h (console restore) | server loss |
| **restic → Storage Box** (this doc) | "the VM, its disk **and** its image backups are gone; or someone with server access deleted them" | ≈ ½ day rebuild (§8) | server loss + project-level loss; readable only with the owner's password |

Why restic and not tar + rsync (the earlier sketch): encryption before bytes leave the host,
deduplication (30 daily copies of a 20 MB dump and 260 MB of mostly-cold evidence cost a few
hundred MB), a retention policy that is one command, and `check` + `restore` that are real
proofs rather than "copy succeeded". Why its own timer and not `OnSuccess=` from the dump
unit: a failed `pg_dump` must still ship yesterday's verified dump and all non-database state.

## 2. What is backed up

| Path | Why | Size (old host, 2026-09-02) |
|---|---|---|
| `/opt/qevik/backups/qevik-*.dump` (verified only; `*.UNVERIFIED` excluded) | the database | 10 × ~20 MB |
| `/var/lib/qevik/control` (vault.json, credentials.jsonl, missions.jsonl, reports) | mission state, sealed vault | small |
| `/var/lib/qevik/evidence` | evidence packages missions cite | 165 MB |
| `/var/lib/qevik/{jobs,prospects,outreach,audits,briefs,workspaces}` | job records, sales artefacts | small |
| `/srv/sites`, `/srv/qevik-public` | published sites (symlinks preserved), public site | 18 MB |
| `/etc/caddy`, `/var/lib/caddy` | Caddyfile, Let's Encrypt account + certs | 236 KB |
| `/var/lib/qevik/backup/env-names.txt`, `units.txt` | **names only** of every `/opt/qevik/*.env` key and every `qevik-*` unit — the rebuild checklist | tiny |

## 3. Intentionally NOT backed up

| Path | Why |
|---|---|
| `/opt/qevik/atlas` (4.8 GB), venv, Playwright browsers | regenerable from git + `infra/deploy_control.sh`; image backups cover the fast path |
| `/var/lib/qevik/scratch`, `/var/lib/qevik/worktrees` | per-mission clones of the repo (`DO_NOT_MIGRATE`) |
| `qevik_test` database, `/opt/qevik/backups/*.UNVERIFIED` | test data; unproven dumps are evidence for a human, not backups |
| `$TMPDIR/atlas-assets` under `PrivateTmp` | dies on every restart already (finding A9) — nothing durable to save |
| journald, apt state, OS | image backups + rebuild |
| **every secret value** (`/opt/qevik/*.env`, `.pgpass`, `/root/.ssh/*`, `QEVIK_VAULT_MASTER_KEY`) | never leave the host; the owner's password manager is their backup (see §7, open question 91_OPEN_QUESTIONS #8 for the vault master key) |

## 4. Schedule

| Timer | When (UTC) | Unit |
|---|---|---|
| `qevik-backup.timer` | 03:30 (+ ≤ 5 min jitter) | `qevik-backup.service` — dump + verify (installed with Postgres in Phase 4) |
| `qevik-offsite.timer` | 04:15 (+ ≤ 5 min jitter), `Persistent=true` | `qevik-offsite.service` — ship, prune, check, restore-verify |

## 5. Retention

- Local: 14 dumps (`QEVIK_BACKUP_KEEP`, existing).
- Off-host (`restic forget`): **30 daily, 8 weekly, 6 monthly** snapshots, `--prune` after each run.
  Worst case ≈ 6 months back; every snapshot is a complete, independently restorable point in time.
- Hetzner image backups: 7 rotations (console).

## 6. Storage location

`sftp://u662608-sub1@u662608.your-storagebox.de:23`, sub-account base `/qevik-prod-backup`,
repository directory `restic/` inside it (`RESTIC_REPOSITORY=sftp:storagebox:restic`, relative to
the sub-account's home). Host key pinned in `/root/.ssh/known_hosts` after fingerprint
verification: ED25519 `SHA256:XqONwb1S0zuj5A1CDxpOSuD2hnAArV1A3wKY7Z3sdgM`.

## 7. Secrets — where they are, and where they are not

| Secret | Location | Mode | Who typed it | Backed up? |
|---|---|---|---|---|
| Storage Box SSH key | `/root/.ssh/storagebox_ed25519` (generated on the host, no passphrase) | root 0600 | nobody — `ssh-keygen` on the host | **no** — a rebuilt host makes a new one; the owner installs its public half (§8 step 2) |
| Sub-account password | Hetzner console / owner's password manager | — | owner, once, into `ssh-copy-id` in their own Terminal | no |
| restic repository password | `/opt/qevik/backup.env` → `EnvironmentFile=` | root 0600 | owner, on the host, via `qevik-backup-set-password` | **no — the owner's password manager copy is the only other copy** |

Not in git, not in the task DB, not in logs (`qevik_offsite.sh` prints the repository as
`sftp:…`), not in this document, not in evidence files. `env-names.txt` in the backup holds
key **names** only.

## 8. Restore after total server loss

Needs: a fresh Ubuntu host, the Storage Box sub-account password (or a key already on the
sub-account), the restic repository password, and this repo from GitHub.

1. `apt install restic git` ; `git clone` the atlas repo (or `curl` just
   `infra/qevik_restore_offsite.sh` and `infra/qevik_backup.sh`).
2. Install a key on the sub-account: `ssh-keygen -t ed25519 -f /root/.ssh/storagebox_ed25519 -N ''`
   then `ssh-copy-id -p 23 -s -i /root/.ssh/storagebox_ed25519.pub u662608-sub1@u662608.your-storagebox.de`
   (sub-account password). Or skip and let step 3 fall back to password auth.
3. `sudo infra/qevik_restore_offsite.sh` — asks for the repository password, lists snapshots,
   restores `latest` under `/` with `--verify`, prints what came back and the next steps.
   (`--snapshot ID` for a point in time; `--target /mnt/x` to inspect without writing into `/`.)
4. Recreate the secret files named in `/var/lib/qevik/backup/env-names.txt` from the password
   manager (`umask 077`, root 0600) — same procedure as Phase 3 of the migration.
5. Rebuild the application: `infra/recover_qevik_server.sh` / `infra/deploy_control.sh`
   (Postgres, role, units, venv, Playwright).
6. Database: `infra/qevik_backup.sh --verify-only <newest dump>` then
   `pg_restore --no-owner -d qevik <newest dump>`.
7. `infra/install_offsite_backup.sh` so the new host backs itself up again (new key → §8 step 2
   again for the new public key).

Expected time ≈ ½ day (AR-1 R3); RPO ≤ 24 h (last 04:15 run).

## 9. Operating it

```
qevik_offsite.sh --status            # last result JSON; exit 2 + marker text if FAILED exists
qevik_offsite.sh --snapshots         # what the Storage Box holds
systemctl start qevik-offsite.service && journalctl -u qevik-offsite -n 30   # manual run
qevik_offsite.sh --selftest          # 4 MiB random file: backup → restore → sha256 → forget
qevik_offsite.sh --restore-dump /root/restore-test   # newest dump out of the repo, non-destructive
journalctl -u qevik-offsite -u qevik-backup-failed --since -2d
```
Failure detection today: the `FAILED` marker + journal. Phase 10 T9 adds the `/api/health`
component that reads `status.json` and the marker (code change, owner approval). Until then,
`--status` is the check; an external uptime monitor on `/api/health` will make it push-style.

Re-install after any change to `infra/qevik_offsite.sh` or the units:
`sudo /opt/qevik/atlas/infra/install_offsite_backup.sh` (idempotent; the deploy glob installs
only `qevik-*.service`, and the script lives in `/usr/local/sbin`, outside the deploy tree, so
a mid-deploy or rolled-back tree cannot break the backup).

## 10. Verification record (2026-09-03)

Full output: `evidence/backup/install-and-selftest.txt` (names, modes, fingerprints only).

| Claim | Status | How |
|---|---|---|
| SSH to Storage Box with the host-local key, no password | PROVED | `sftp -o BatchMode=yes storagebox` lists `/home` (sub-account chroot) and `restic/` |
| Host key pinned = fingerprint recorded from a second observation | PROVED | installer refuses on mismatch; `ssh -v` "matches the ED25519 host key" |
| Negative control before the key existed | PROVED | `Permission denied (publickey,password)`, exit 255 |
| `backup.env` root 0600, single key `RESTIC_PASSWORD`, systemd parses the same bytes the file holds | PROVED | `stat`, `cut -d= -f1`, `systemd-run -p EnvironmentFile=` equality test (no value printed) |
| Repository initialised, encrypted, `restic check --read-data` clean | PROVED | repo id `a8dfcaf29daf256b`, version 2 |
| Backup → restore → byte-identical (4 MiB random selftest) | PROVED | snapshot `e4228699`, forgotten + pruned after |
| Dump path: fixture `qevik-*.dump` shipped, restore-verify `sha256 match`; local copy deleted, `--restore-dump` from the repo returns identical bytes | PROVED | snapshot `739e6f4e`, fixture removed, snapshots pruned |
| Tampered local dump is detected | PROVED | `MISMATCH … exit 1` |
| Real run through systemd under `ProtectSystem=strict` etc. | PROVED | `systemctl start qevik-offsite.service` → `OK in 7s`, `status.json` result ok |
| Failure marker written by `OnFailure=`, `--status` exit 2, cleared by next success | PROVED | transient `/bin/false` unit; systemd 259 `MONITOR_*` found unreliable → templated `%i` |
| Timer enabled, next run 2026-09-04 04:15 UTC | PROVED | `systemctl list-timers` |
| The 11 verified production dumps from the old host are in the repository, byte-identical | PROVED | see §10.1 below; `evidence/backup/old-host-dumps-pull.txt` |
| A **real** production dump restored from the Storage Box parses with `pg_restore --list` | PROVED | all 11 restored dumps: `pg_restore` exit 0, 250–304 TOC entries, 65–75 TABLE DATA entries |
| A **real** production dump fully loaded into Postgres on the target (V15) | **NOT YET** | no Postgres server on the target until Phase 4; each dump was load-verified by `qevik_backup.sh` on the old host at creation time |
| Restore on a machine that is not the server | **NOT YET** | `qevik_restore_offsite.sh` written; execution needs the owner to type both secrets on that machine |

### 10.1 Old-host dumps pulled into the repository (2026-09-03 16:13–16:27 UTC)

Owner GO: "pull old dumps", Mac-mediated, read-only, no agent forwarding. Evidence with every
hash and count: `evidence/backup/old-host-dumps-pull.txt`.

- **Copied: 11 dumps**, `qevik-20260817T131008Z.dump` … `qevik-20260903T033126Z.dump`
  (dates 2026-08-17, 08-18, 08-26, 08-27, 08-28, 08-29, 08-30, 08-31, 09-01, 09-02, 09-03),
  100.5 MiB total. Excluded: the two ad-hoc `pre-*.sql` files under `/var/lib/qevik/backups`
  (never verified by restore); no `.UNVERIFIED` existed; no test-DB data is in these dumps.
- Source access: `ls`, `stat`, `sha256sum`, `head`, `tail` only. Re-`stat` after the copy shows
  the same 11 names/sizes/mtimes. Nothing on the old host was modified or deleted (AR-4).
- Transfer: old host → Mac stdin/stdout → target, 4 MiB resumable chunks, `.part` prefix
  re-verified against the source before each resume; final 11/11 sha256 match; original mtimes
  restored with `touch -d @epoch`, mode 0600.
- Restic: `systemctl start qevik-offsite.service` → snapshot **`ed2b42b1`** (11 new files,
  75 MiB added), `check --read-data-subset=5%` ok, restore-verify of the newest dump `sha256 match`,
  `status.json` result ok. Then a **full `restic check --read-data`: 8/8 packs, no errors**.
- Restore test: all 11 dumps restored from the Storage Box into `/root/restore-test`
  (removed afterwards): **11/11 sha256 match the old-host checksums**, mtimes preserved, and
  `pg_restore --list` (postgresql-client 18.6, same major as the old host's `pg_dump` 18.6)
  exits 0 on every file — 250→304 TOC entries, 65→75 TABLE DATA entries, growing with the dates.
- Repository after upload: raw data 78.2 MB (74.6 MiB) in 65 blobs; restore size 105.4 MB;
  Storage Box shows 75.4 MB used of 1 TB; 2 snapshots (`b5212410` state-only, `ed2b42b1` dumps).
- The full-load test (V15) still waits for Postgres on the target (Phase 4).

### 10.2 Retention ownership of the migrated dumps (planned, B-5 / R-31)

The 11 dumps in §10.1 are **historical production evidence**, not backups this host
produced, and `qevik_backup.sh` prunes `/opt/qevik/backups/qevik-*.dump` to the 14
newest. Before any backup unit runs here:

- they move to `/opt/qevik/backups/archive/old-host/` — outside the pruner's glob,
  still inside the tree `qevik-offsite.service` ships off-host — `root:root`, dir
  `0700`, files `0400`;
- `qevik-backup.timer` stays **disabled** until Phase 6 (B-6), enforced by a guard in
  the planned `install_qevik_infra.sh`;
- `qevik_offsite.sh`'s `newest_dump()` becomes recursive, so the daily restore proof
  keeps running against the archived dumps until the target produces its own;
- the archive is removed only at Phase 11, by owner decision, after the old host's
  final archive is restore-tested.

Specified in `MIGRATION_ENABLEMENT_SPEC.md` §8; **the code landed 2026-09-03**
(`5fa9cc7`): `qevik_backup.sh`'s pruner is documented as owning only the top level,
`qevik_offsite.sh` selects a **current** dump when one exists and falls back to the
archive only while this host has produced none (`--strict-current` makes that a
failure once the database holds data), and `install_qevik_infra.sh` refuses to
enable `qevik-backup.timer` while an unarchived migrated dump is still in the
retention path. **The move itself has not been performed** — it is a host action,
and no host has been touched.

Interim note: until Phase 4 deploys the repo, the installed sources live in `/root/qevik-infra/`
on the target (copied from `infra/` at this commit). After Phase 4, re-run the installer from
`/opt/qevik/atlas/infra/` and remove `/root/qevik-infra`.

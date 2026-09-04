#!/usr/bin/env bash
#
# Everything a host needs that the deploy payload cannot install.
#
#   ./infra/install_qevik_infra.sh                        # install + enable the services
#   ./infra/install_qevik_infra.sh --enable-backup-timer  # additionally start taking backups
#   ./infra/install_qevik_infra.sh --check                # report, change nothing
#
# `deploy_control.sh` ships unit *files* and enables nothing; `qevik-jobs.slice`
# and the `qevik-api` drop-in live under `infra/systemd/` and match no glob it
# uses. Until now the only thing that installed them was
# `recover_qevik_server.sh` — an incident-response script — so a correctly
# deployed host could be missing its memory limits and the Playwright browser
# path until something went wrong enough to run the recovery.
#
# The split this script implements, and the reason each unit is on its side of it:
#
#   installed by the deploy      every qevik-*.service and qevik-*.timer file
#   installed here, once         qevik-jobs.slice, qevik-api.service.d/resources.conf
#   enabled here                 api, control and the six workers — the units that
#                                must survive a reboot
#   enabled only after data      qevik-backup.timer  (a backup of an empty database
#                                is not a backup, and its retention would begin
#                                deleting the migrated production dumps)
#                                qevik-market-scan.timer (needs the new, IP-restricted
#                                Places key, and spends quota to prove nothing)
#   never enabled                qevik-backup.service, qevik-market-scan.service,
#                                qevik-offsite.service — timer-driven, no [Install]
#                                qevik-backup-failed@.service — an OnFailure= template
#
set -euo pipefail

BASE="${QEVIK_BASE:-/opt/qevik}"
APP="${QEVIK_APP:-$BASE/atlas}"
APP_USER="${QEVIK_USER:-qevik}"
STATE="${QEVIK_STATE_DIR:-/var/lib/qevik}"
DUMPS="${QEVIK_BACKUP_DIR:-$BASE/backups}"
#: Where the migrated production dumps live, outside the retention glob.
ARCHIVE="${QEVIK_BACKUP_ARCHIVE:-$DUMPS/archive}"
UNIT_DIR="${QEVIK_UNIT_DIR:-/etc/systemd/system}"
SRC="${QEVIK_INFRA_SRC:-$APP/infra}"

#: The units that must come back after a reboot.
# qevik-worker-llm.service is here, and it is the only one that calls a paid
# provider. Without it an approved plan reaches `queued` and stops: every other
# worker serves a different agent, and `policy.refuse_agent_substitution`
# correctly refuses to let one carry out a plan approved for another. A host
# built without this unit has a complete chat-to-mission pipeline and nobody at
# the end of it.
LONG_RUNNING="qevik-api.service qevik-control.service qevik-worker.service \
qevik-worker-llm.service \
qevik-worker-research.service qevik-worker-delivery.service \
qevik-worker-publish.service qevik-worker-healthcheck.service"

MODE=install
case "${1:-}" in
  --check) MODE=check ;;
  --enable-backup-timer) MODE=backup-timer ;;
  "") ;;
  *) echo "usage: $0 [--check|--enable-backup-timer]" >&2; exit 2 ;;
esac

say() { printf '\n== %s\n' "$*"; }
die() { echo "REFUSED: $*" >&2; exit 1; }

# --- the guard that stops a backup starting before there is anything to back up

#: True when the database exists and has tables in it — i.e. the data migration
#: has happened. `psql` runs as the postgres superuser over the local socket, so
#: no DSN and no password is involved.
database_has_data() {
  local count
  count="$(sudo -u postgres psql -tAc \
    "select count(*) from pg_tables where schemaname='public'" qevik 2>/dev/null || echo 0)"
  [ "${count:-0}" -gt 0 ] 2>/dev/null
}

#: True when dumps are sitting in the retention path and none of them has been
#: archived — i.e. the migrated production history is still where the pruner
#: would delete it.
#:
#: The rule is deliberately about *structure*, not about timestamps. "Older than
#: this host's boot" was the first attempt and is wrong twice over: a reboot
#: after the data migration makes every dump look migrated, and a host that
#: cannot report its boot time would answer "nothing to worry about" — a guard
#: that fails open. This asks one question with a stable answer: are there dumps
#: in the retention path, and has the archive they belong in been created? On
#: this target the only dumps that exist before the data migration are the
#: migrated ones, and archiving them creates the directory, so the guard opens
#: exactly when the move has happened and stays open afterwards.
unarchived_migrated_dumps() {
  [ -d "$DUMPS" ] || return 1
  ls -1 "$DUMPS"/qevik-*.dump >/dev/null 2>&1 || return 1   # nothing there at all
  [ -d "$ARCHIVE" ] && return 1                              # the move has happened
  return 0
}

if [ "$MODE" = backup-timer ]; then
  [ "$(id -u)" -eq 0 ] || die "run as root."
  say "checking whether backups may begin"
  database_has_data \
    || die "the qevik database has no tables. A backup of an empty database is not a backup, and its retention would begin deleting the migrated production dumps. Enable this after the data migration (Phase 6)."
  ! unarchived_migrated_dumps \
    || die "$DUMPS holds dumps and $ARCHIVE does not exist, so the migrated production history is still where qevik_backup.sh would prune it. Move it to $ARCHIVE/old-host/ first — retention owns only what this host wrote (B-5)."
  systemctl enable --now qevik-backup.timer
  systemctl list-timers qevik-backup.timer --no-pager
  echo "qevik-backup.timer is enabled."
  exit 0
fi

say "1/6 what is installed"
systemctl list-unit-files 'qevik-*' --no-pager || true
echo
for f in "$UNIT_DIR/qevik-jobs.slice" "$UNIT_DIR/qevik-api.service.d/resources.conf"; do
  [ -f "$f" ] && echo "present: $f" || echo "absent:  $f"
done

if [ "$MODE" = check ]; then
  say "backup timer"
  if database_has_data; then echo "database: has tables"; else echo "database: empty (backups must stay disabled)"; fi
  if unarchived_migrated_dumps; then echo "dumps: migrated dumps are still in the retention path"; else echo "dumps: nothing unarchived in the retention path"; fi
  systemctl is-enabled qevik-backup.timer 2>&1 | sed 's/^/qevik-backup.timer: /'
  exit 0
fi

[ "$(id -u)" -eq 0 ] || die "run as root."
[ -d "$SRC" ] || die "no infra sources at $SRC — deploy first, or set QEVIK_INFRA_SRC."
id "$APP_USER" >/dev/null 2>&1 || die "the service account '$APP_USER' does not exist (Phase 3 creates it)."

say "2/6 directories the units write to"
# Ownership follows the units: state and served trees belong to the service
# account; the served trees are group/other-readable because Caddy runs as a
# different user and an unreadable file is a 403 that reads like an outage.
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 \
  "$STATE" "$STATE/control" "$STATE/control/reports" "$STATE/scratch" \
  "$STATE/worktrees" "$STATE/jobs" "$STATE/evidence" "$STATE/prospects" \
  "$STATE/outreach" "$STATE/audits" "$STATE/briefs" "$STATE/workspaces"
# The application tree itself. `deploy_control.sh` rsyncs *into* these
# directories and rsync will not create a missing destination root: on a fresh
# host the first deploy fails with "change_dir /opt/qevik/atlas: No such file or
# directory" after eleven retries, which reads like a network fault and is a
# missing mkdir. The layout is this script's job, so it makes them.
install -d -o "$APP_USER" -g "$APP_USER" -m 0755 \
  "$APP" "$APP/packages" "$APP/packages/kernel" "$APP/packages/kernel/atlas_kernel" \
  "$APP/infra"
install -d -o "$APP_USER" -g "$APP_USER" -m 0755 /srv/sites /srv/qevik-public /srv/qevik-control
install -d -o "$APP_USER" -g "$APP_USER" -m 0755 "$DUMPS"
install -d -o "$APP_USER" -g "$APP_USER" -m 0750 "$BASE/market"
ls -ld "$STATE" "$DUMPS" /srv/sites /srv/qevik-control

say "3/6 resource limits (the deploy cannot install these)"
install -m 0644 "$SRC/systemd/qevik-jobs.slice" "$UNIT_DIR/qevik-jobs.slice"
install -d -m 0755 "$UNIT_DIR/qevik-api.service.d"
install -m 0644 "$SRC/systemd/qevik-api.service.d/resources.conf" \
  "$UNIT_DIR/qevik-api.service.d/resources.conf"
systemctl daemon-reload
systemctl start qevik-jobs.slice || true
systemctl show qevik-jobs.slice -p MemoryMax -p TasksMax -p CPUQuotaPerSecUSec

say "4/6 enabling what must survive a reboot"
for unit in $LONG_RUNNING; do
  [ -f "$UNIT_DIR/$unit" ] || { echo "skipped (not deployed yet): $unit"; continue; }
  systemctl enable "$unit" >/dev/null
  echo "enabled: $unit"
done

say "5/6 timers"
# The off-host backup ships state and any dump that exists; it is safe on an
# empty host and is the one timer that should already be running.
if [ -f "$UNIT_DIR/qevik-offsite.timer" ]; then
  systemctl enable --now qevik-offsite.timer >/dev/null
  echo "enabled: qevik-offsite.timer"
fi
echo "left disabled: qevik-backup.timer (after the data migration: $0 --enable-backup-timer)"
echo "left disabled: qevik-market-scan.timer (after the new Places key is in place and proven)"

say "6/6 state"
systemctl list-unit-files 'qevik-*' --no-pager
echo
echo "Units are installed and enabled; nothing that touches production data has"
echo "been started."

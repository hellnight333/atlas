#!/usr/bin/env bash
#
# Back up the Qevik database, and prove the backup restores.
#
#   qevik_backup.sh            # take a backup, verify it, prune old ones
#   qevik_backup.sh --verify-only PATH
#
# §29 is blunt about the standard: "A backup that has never been restored is not
# considered verified." So this does not stop at writing a file. Every backup is
# restored into a scratch database and checked for the tables it should contain,
# and the backup is only kept if that passes. An unverified dump is a feeling,
# not a backup.
#
set -euo pipefail

BASE="${QEVIK_BASE:-/opt/qevik}"
ENV_FILE="${BASE}/atlas.env"
DIR="${QEVIK_BACKUP_DIR:-${BASE}/backups}"
KEEP="${QEVIK_BACKUP_KEEP:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

# The URL carries the password and is never echoed. Nothing below prints
# $PGPASSWORD or the URL.
#
# Prefer what the environment already holds. Under systemd this script runs as
# `User=qevik` while `/opt/qevik/atlas.env` is root-owned 0600, so *sourcing* it
# here fails with "Permission denied" — which is exactly how every backup from
# 2026-08-22 to 2026-08-26 failed, five days with no verified backup and no
# signal anywhere. The other four units never hit it because they use
# `EnvironmentFile=`, which systemd reads as root *before* dropping privileges.
#
# So the unit now does the same, and this fallback is for a human running the
# script by hand as root. The file's permissions are deliberately unchanged:
# loosening them to fix this would have handed the database URL to any process
# running as qevik, to repair a service that never needed to read the file
# itself.
# Under systemd the environment arrives through `EnvironmentFile=`. A hand run
# has to get it from somewhere too, and it used to `source` the file — a shell,
# so a database password containing `$`, a backtick, a quote or a space either
# broke the run or was silently altered before psql saw it.
#
# Rather than write a second parser that would drift from systemd's, a hand run
# re-executes itself *through* systemd, with the same EnvironmentFile= the units
# use. One parser, one set of semantics, and the value never passes through a
# shell. The marker stops the re-exec repeating if the file does not define it.
if [ -z "${ATLAS_DATABASE_URL:-}" ]; then
  if [ ! -r "$ENV_FILE" ]; then
    echo "ATLAS_DATABASE_URL is not set and $ENV_FILE is not readable by $(id -un)." >&2
    echo "Under systemd this comes from EnvironmentFile=; by hand, run as root." >&2
    exit 1
  fi
  if [ -n "${QEVIK_BACKUP_REEXEC:-}" ]; then
    echo "$ENV_FILE does not define ATLAS_DATABASE_URL." >&2
    exit 1
  fi
  if ! command -v systemd-run >/dev/null; then
    echo "ATLAS_DATABASE_URL is not set and systemd-run is unavailable." >&2
    echo "Run this unit rather than the script: systemctl start qevik-backup" >&2
    exit 1
  fi
  exec systemd-run --wait --collect --pipe --quiet \
    --property=EnvironmentFile="$ENV_FILE" \
    --property=User="${QEVIK_USER:-qevik}" --property=Group="${QEVIK_USER:-qevik}" \
    --property=WorkingDirectory="$BASE" \
    --setenv=QEVIK_BACKUP_REEXEC=1 \
    "$0" "$@"
fi
URL="${ATLAS_DATABASE_URL#*://}"
CRED="${URL%%@*}"; HOSTDB="${URL#*@}"
PGUSER_="${CRED%%:*}"; PGPASSWORD="${CRED#*:}"
HOSTPORT="${HOSTDB%%/*}"; PGDATABASE_="${HOSTDB##*/}"
PGHOST_="${HOSTPORT%%:*}"; PGPORT_="${HOSTPORT##*:}"
export PGPASSWORD

verify() {
    local dump="$1" scratch="qevik_verify_$$"
    # Restored into a throwaway database rather than checked with `file`. The
    # only question that matters is whether postgres accepts it.
    createdb -h "$PGHOST_" -p "$PGPORT_" -U "$PGUSER_" "$scratch" >/dev/null
    local ok=1
    if pg_restore -h "$PGHOST_" -p "$PGPORT_" -U "$PGUSER_" -d "$scratch" --no-owner "$dump" >/dev/null 2>&1; then
        local tables
        tables=$(psql -h "$PGHOST_" -p "$PGPORT_" -U "$PGUSER_" -d "$scratch" -tAc \
            "select count(*) from information_schema.tables where table_schema='public'")
        # A dump that restores into an empty schema restores nothing. The count
        # is the difference between "pg_restore exited 0" and "the data is there".
        [ "${tables:-0}" -ge 50 ] && ok=0
        echo "  restored ${tables} tables"
    fi
    dropdb -h "$PGHOST_" -p "$PGPORT_" -U "$PGUSER_" "$scratch" >/dev/null 2>&1 || true
    return $ok
}

if [ "${1:-}" = "--verify-only" ]; then
    verify "$2" && { echo "VERIFIED $2"; exit 0; } || { echo "FAILED to restore $2" >&2; exit 1; }
fi

mkdir -p "$DIR"
DUMP="${DIR}/qevik-${STAMP}.dump"
pg_dump -h "$PGHOST_" -p "$PGPORT_" -U "$PGUSER_" -d "$PGDATABASE_" -Fc -f "$DUMP"
chmod 600 "$DUMP"
echo "wrote $(basename "$DUMP") ($(du -h "$DUMP" | cut -f1))"

if verify "$DUMP"; then
    echo "VERIFIED — restores cleanly"
else
    # Kept for inspection rather than deleted: a backup that failed to verify is
    # evidence about the database, and throwing it away throws that away too.
    mv "$DUMP" "${DUMP}.UNVERIFIED"
    echo "UNVERIFIED — kept as $(basename "$DUMP").UNVERIFIED for inspection" >&2
    exit 1
fi

# Prune only verified backups, newest kept. Never prunes the one just taken.
ls -1t "${DIR}"/qevik-*.dump 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
    rm -f "$old"; echo "pruned $(basename "$old")"
done
echo "retained $(ls -1 "${DIR}"/qevik-*.dump 2>/dev/null | wc -l) verified backup(s)"

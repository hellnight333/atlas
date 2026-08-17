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

# The URL carries the password, so it is read from the 0600 env file and never
# echoed. Nothing below prints $PGPASSWORD or the URL.
set -a; . "$ENV_FILE"; set +a
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
